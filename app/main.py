from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from app.models import EvaluationRequest, EvaluationResult, ReviewRequest
from app.pipeline import ControlPlane
from app.policy import PolicyError, ROOT


app = FastAPI(
    title="ControlPlane.ai",
    version="0.1.0",
    description="Evidence-aware runtime governance middleware for enterprise AI",
)
control_plane = ControlPlane()
WEB_ROOT = ROOT / "frontend"
INDEX_HTML = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
STYLES_CSS = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
APP_JS = (WEB_ROOT / "app.js").read_text(encoding="utf-8")


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/static/styles.css", include_in_schema=False)
async def styles() -> Response:
    return Response(STYLES_CSS, media_type="text/css")


@app.get("/static/app.js", include_in_schema=False)
async def javascript() -> Response:
    return Response(APP_JS, media_type="text/javascript")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version, "mode": "deterministic-demo"}


@app.get("/api/scenarios")
async def scenarios() -> list[dict]:
    return control_plane.data.demo_scenarios


@app.post("/api/scenarios/{scenario_id}/run", response_model=EvaluationResult)
async def run_scenario(scenario_id: str) -> EvaluationResult:
    try:
        scenario = control_plane.data.scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    payload = {key: value for key, value in scenario.items() if key in EvaluationRequest.model_fields}
    payload["scenario_id"] = scenario_id
    return control_plane.evaluate(EvaluationRequest(**payload), source="demo")


@app.post("/api/evaluate", response_model=EvaluationResult)
async def evaluate(request: EvaluationRequest) -> EvaluationResult:
    try:
        return control_plane.evaluate(request)
    except PolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/evaluation-suite/run")
async def run_evaluation_suite() -> dict:
    results = []
    for scenario in control_plane.data.evaluation_scenarios:
        payload = {key: value for key, value in scenario.items() if key in EvaluationRequest.model_fields}
        payload["scenario_id"] = scenario["id"]
        result = control_plane.evaluate(EvaluationRequest(**payload), source="evaluation")
        results.append({
            "scenario_id": scenario["id"],
            "decision": result.decision,
            "risk_score": result.risk_score,
            "expected_harmful": scenario["expected_harmful"],
        })
    return {"count": len(results), "results": results, "metrics": control_plane.audit.metrics()}


@app.get("/api/policies")
async def policies() -> list[dict]:
    return [policy.model_dump(mode="json") for policy in control_plane.policies.list_profiles()]


@app.get("/api/audits")
async def audits(limit: int = Query(default=25, ge=1, le=100)) -> list[dict]:
    return control_plane.audit.recent(limit)


@app.post("/api/audits/{audit_id}/review")
async def review(audit_id: str, request: ReviewRequest) -> dict:
    try:
        return control_plane.audit.review(audit_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Audit record not found") from exc


@app.get("/api/metrics")
async def metrics() -> dict:
    return control_plane.audit.metrics()
