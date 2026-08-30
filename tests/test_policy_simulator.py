from pathlib import Path

from app.audit import AuditRepository
from app.models import EvaluationRequest
from app.pipeline import ControlPlane
from app.policy_simulator import PolicySimulationRequest, PolicySimulator


def proposed_request(**updates: object) -> EvaluationRequest:
    values: dict[str, object] = {
        "prompt": "Tell the customer our refund policy.",
        "action": "answer",
        "proposed_response": "Damaged goods qualify for a full refund.",
        "session_id": "customer-session",
    }
    values.update(updates)
    return EvaluationRequest(**values)


def test_simulator_compares_all_three_profiles() -> None:
    response = PolicySimulator().compare(PolicySimulationRequest(
        evaluation=proposed_request(),
        regions=["IN"],
    ))

    assert response.comparison_count == 3
    assert {result.profile for result in response.results} == {
        "support_bot",
        "internal_copilot",
        "refund_agent",
    }
    assert all(result.region == "IN" for result in response.results)
    assert all(result.policy_version for result in response.results)
    assert all(result.thresholds for result in response.results)
    assert all("blast_radius" in result.checks for result in response.results)
    assert all(result.decision_summary for result in response.results)


def test_simulator_does_not_mutate_runtime_audit(tmp_path: Path) -> None:
    runtime_audit = AuditRepository(tmp_path / "runtime.db")
    runtime_plane = ControlPlane(audit=runtime_audit)
    runtime_plane.evaluate(proposed_request())
    before = runtime_audit.recent(limit=100)

    simulator = PolicySimulator.from_control_plane(runtime_plane)
    response = simulator.compare(PolicySimulationRequest(
        evaluation=proposed_request(session_id="customer-session"),
        profiles=["support_bot", "refund_agent"],
        regions=["IN"],
    ))

    assert response.comparison_count == 2
    assert runtime_audit.recent(limit=100) == before
    assert runtime_audit.session_risk("customer-session") == before[0]["risk_score"]


def test_simulator_compares_regions() -> None:
    response = PolicySimulator().compare(PolicySimulationRequest(
        evaluation=proposed_request(
            prompt="Contact the customer at 203.0.113.42.",
            proposed_response="Contact the customer at 203.0.113.42.",
        ),
        profiles=["support_bot"],
        regions=["IN", "EU"],
    ))

    assert response.comparison_count == 2
    by_region = {result.region: result for result in response.results}
    assert set(by_region) == {"IN", "EU"}
    assert by_region["IN"].thresholds == by_region["EU"].thresholds
    assert by_region["IN"].check_cost["blast_radius"] == "R0"
    assert by_region["EU"].check_cost["blast_radius"] == "R0"
