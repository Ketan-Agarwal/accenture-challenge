import asyncio

import httpx

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
