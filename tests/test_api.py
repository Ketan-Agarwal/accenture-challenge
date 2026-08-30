import asyncio

import httpx
import pytest

import app.main as main_module
from app.action_gateway import ActionGateway
from app.audit import AuditRepository
from app.main import app


async def async_request(method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def request(method: str, path: str, **kwargs):
    return asyncio.run(async_request(method, path, **kwargs))


def test_health_and_scenarios():
    assert request("GET", "/api/health").status_code == 200
    scenarios = request("GET", "/api/scenarios").json()
    assert len(scenarios) == 8


def test_backend_root_redirects_to_api_documentation():
    response = request("GET", "/")
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_scenario_run_returns_auditable_decision():
    response = request("POST", "/api/scenarios/refund-mismatch/run")
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "block"
    assert payload["audit_id"].startswith("cp_")
    assert "NUMERIC_MISMATCH" in payload["reason_codes"]


def test_unknown_policy_is_rejected():
    response = request("POST", "/api/evaluate", json={
        "use_case": "unknown",
        "prompt": "hello",
        "proposed_response": "hello",
    })
    assert response.status_code == 422


def test_policy_versions_endpoint():
    response = request("GET", "/api/policies/versions")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_version"] == "2026.08.1"
    assert "2026.07.1" in payload["superseded_versions"]
    assert set(payload["profiles"]) == {"support_bot", "internal_copilot", "refund_agent"}
    assert set(payload["regions"]) == {"IN", "EU"}


@pytest.fixture()
def isolated_action_runtime(tmp_path, monkeypatch):
    original_audit = main_module.control_plane.audit
    audit = AuditRepository(tmp_path / "runtime.db")
    main_module.control_plane.audit = audit
    gateway = ActionGateway(
        audit.path,
        main_module.control_plane.data,
        "api-test-action-secret-is-long-enough",
        token_ttl_seconds=300,
    )
    monkeypatch.setattr(main_module, "action_gateway", gateway)
    yield gateway
    main_module.control_plane.audit = original_audit


def test_action_gateway_authorizes_executes_and_replay_protects(isolated_action_runtime):
    proposed = request("POST", "/api/actions/propose", json={
        "use_case": "refund_agent",
        "region": "IN",
        "session_id": "api-action-test",
        "order_id": "ORD-1001",
        "amount_inr": 1499,
        "reason": "wrong_item",
    })
    assert proposed.status_code == 200
    payload = proposed.json()
    assert payload["action"]["status"] == "authorized"
    assert payload["evaluation"]["decision"] == "allow"
    token = payload["authorization_token"]
    action_id = payload["action"]["action_id"]

    first = request("POST", f"/api/actions/{action_id}/execute", json={
        "authorization_token": token,
    })
    replay = request("POST", f"/api/actions/{action_id}/execute", json={
        "authorization_token": token,
    })
    assert first.status_code == replay.status_code == 200
    assert first.json()["receipt"]["refund_id"] == replay.json()["receipt"]["refund_id"]
    assert first.json()["action"]["status"] == "executed"

    orders = request("GET", "/api/commerce/orders").json()
    order = next(item for item in orders if item["order_id"] == "ORD-1001")
    assert order["status"] == "refunded"
    assert order["refunded_amount_inr"] == 1499


def test_policy_simulator_flat_api_contract_does_not_add_runtime_audits(
    isolated_action_runtime,
):
    before = main_module.control_plane.audit.metrics()["volume"]
    response = request("POST", "/api/policy-simulator", json={
        "prompt": "Can I get a refund after the return window?",
        "proposed_response": "Our goodwill policy guarantees a full refund.",
        "action": "issue_refund",
        "region": "IN",
        "profiles": ["support_bot", "internal_copilot", "refund_agent"],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison_count"] == 3
    assert {row["profile"] for row in payload["results"]} == {
        "support_bot", "internal_copilot", "refund_agent",
    }
    assert all("checks_run" in row for row in payload["results"])
    assert main_module.control_plane.audit.metrics()["volume"] == before
