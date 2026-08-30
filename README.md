# ControlPlane.ai

ControlPlane.ai is an evidence-aware runtime governance layer for enterprise AI. It evaluates a request, a proposed model response, and the intended downstream action under a versioned use-case policy before deciding to **allow**, **warn/edit**, **hold for human review**, or **block**.

This Round 2 prototype uses synthetic commerce data and deterministic model responses so the judged demo is repeatable. It does not require proprietary data or an external model API.

## What the prototype demonstrates

- Different policies for a support bot, internal copilot, and refund agent.
- Action blast-radius tiers from read-only (`R0`) to irreversible financial action (`R3`).
- Bounded prompt-injection and PII screening.
- Policy-claim attribution with supported, contradicted, unsupported, and unavailable evidence states.
- Deterministic refund recomputation against a synthetic system of record.
- Response disagreement as a fallback when authoritative evidence is unavailable.
- Session-level cascade risk.
- Versioned regional overlays for India- and EU-oriented demo policies.
- Structured reason codes, an audit trail, human review, and honest false-positive/negative metrics.
- A two-phase Action Gateway: the model proposes a refund, while a constrained
  executor alone can authorize and commit it.
- Short-lived HMAC capabilities bound to the action ID, order, amount, policy
  version, expiry, and API route, with restart-safe exactly-once receipts.
- A side-effect-free Policy Simulator that compares the same evidence across
  multiple trust contracts without contaminating runtime audits or metrics.

## Three-minute judge demo

1. Open **Action Gateway**, select `ORD-1001`, and propose INR 2,499.
   Deterministic recomputation blocks it and no
   execution capability is minted. Blocked actions are immutable; correction
   requires a fresh evaluation.
2. Change it to the correct INR 1,499 and propose again. Show the evidence
   receipt and short-lived authorization, then execute it. The commerce order
   changes to `refunded` and the ledger retains a receipt.
3. Replay the execute request through the API. The same receipt is returned and
   no second refund is created.
4. In **Policy Simulator**, run one unsupported policy claim across support,
   copilot, and refund profiles. Compare their thresholds, checks, risk scores,
   and interventions while the production audit count stays unchanged.
5. Finish with the seeded evaluation suite and metrics: precision/recall,
   false-positive and false-negative rates, latency, review overrides, and
   model-call cost by blast radius.

## Run locally

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 20+ for the Next.js dashboard.

### Backend API

```bash
uv sync --group dev
uv run uvicorn app.main:app --reload
```

The default installation is offline-safe and uses the deterministic regex and
Jaccard fallbacks. Optional local detectors can be installed separately:

```bash
# Presidio PII engine (requires a compatible spaCy language model)
uv sync --group dev --extra pii

# Sentence-transformer grounding; pre-cache all-MiniLM-L6-v2 first
uv sync --group dev --extra embeddings
CONTROLPLANE_ENABLE_LOCAL_EMBEDDINGS=1 uv run uvicorn app.main:app --reload
```

Runtime model downloads are disabled. Set `CONTROLPLANE_ALLOW_MODEL_DOWNLOAD=1`
only during an explicit setup step, never for the judged offline demo.

API docs: <http://127.0.0.1:8000/docs>

### Next.js dashboard (recommended demo UI)

```bash
cd web
npm install
npm run dev
```

Open <http://localhost:3000>. The dashboard proxies `/api/*` to the FastAPI backend at `http://127.0.0.1:8000` (override with `API_URL`).

Run the tests:

```bash
uv run pytest
```

## Run with Podman or Docker

The Compose stack builds two non-root production containers and persists the
SQLite audit trail in the `audit-data` volume.

```bash
# Podman
podman compose up --build

# Docker
docker compose up --build
```

Open the Next.js dashboard at <http://localhost:3000>. The backend API and
interactive documentation remain available at <http://localhost:8000/docs>.
The frontend proxies `/api/*` to the internal `backend:8000` service, so the
browser never needs to know the container-network address.

Useful Podman lifecycle commands:

```bash
podman compose ps
podman compose logs -f
podman compose down

# Also remove the persisted synthetic audit database:
podman compose down --volumes
```

The default container intentionally uses the dependency-light regex/Jaccard
detectors. Optional Presidio and sentence-transformer extras are excluded to
keep the judged demo image small, deterministic, and offline-safe.

The Compose file includes a deterministic demo signing secret so authorizations
survive a container restart. Override `CONTROLPLANE_ACTION_SECRET` with a secret
manager-provided random value outside the synthetic demo.

## API

Interactive API documentation is available at <http://127.0.0.1:8000/docs>.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/scenarios` | List the eight seeded demo scenarios |
| `POST` | `/api/scenarios/{id}/run` | Run one deterministic scenario |
| `POST` | `/api/evaluate` | Evaluate a custom request/response pair |
| `POST` | `/api/evaluation-suite/run` | Run the separate 12-case labeled evaluation set |
| `GET` | `/api/policies` | Inspect resolved use-case and regional policies |
| `GET` | `/api/policies/versions` | List active and historical policy versions |
| `POST` | `/api/policy-simulator` | Compare one request across policy profiles without runtime side effects |
| `GET` | `/api/commerce/orders` | Read the synthetic commerce system of record plus executed refunds |
| `GET` | `/api/actions` | Read the capability-free governed action ledger |
| `POST` | `/api/actions/propose` | Evaluate and persist a structured refund proposal |
| `POST` | `/api/actions/{id}/review` | Approve/correct or reject a held action |
| `POST` | `/api/actions/{id}/execute` | Execute an authorized action exactly once |
| `GET` | `/api/audits` | Read recent decision records |
| `POST` | `/api/audits/{id}/review` | Apply a human safety label or decision override |
| `GET` | `/api/metrics` | Read operational and confusion-matrix metrics |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/evaluate \
  -H 'Content-Type: application/json' \
  -d '{
    "use_case": "refund_agent",
    "region": "IN",
    "action": "issue_refund",
    "session_id": "manual-demo",
    "prompt": "Issue INR 2,499 for order ORD-1001",
    "proposed_response": "I will issue INR 2,499 for ORD-1001"
  }'
```

The order total is INR 1,499, so the deterministic business-data check blocks this request with `NUMERIC_MISMATCH`.

## Runtime path

```text
application
  → policy + region router
  → request/action preflight
  → model-provider boundary
  → applicable evidence checks
  → hard constraints + weighted decision policy
  → release, redact, hold, or block
  → signed action capability (only when authorized)
  → constrained exactly-once commerce executor
  → SQLite audit + action receipt + human feedback + metrics
```

Hard constraints are evaluated separately from the weighted evidence score. A numeric mismatch on an automated refund or an injection attempt attached to a privileged action cannot pass because unrelated checks were quiet.

## Repository map

```text
app/                         API, policy router, checks, action gateway, simulator, audit and metrics
config/policies.json         Versioned profiles and regional overlays
data/demo_scenarios.json     Eight judge-facing demo stories
data/evaluation_scenarios.json  Separate labeled evaluation cases
data/orders.csv              Synthetic commerce system of record
data/policy_docs/            Synthetic governed policy corpus
web/                         Next.js demo dashboard
tests/                       Pipeline and API regression tests
ControlPlane_Final_Proposal_Plan.md
```

## Important limitations

- Embedding or lexical similarity retrieves evidence; neither proves entailment.
- Generation agreement measures stability; it does not establish factual truth.
- Regex PII and prompt-injection checks are bounded demonstrations and can miss paraphrases or create false positives.
- The policy overlays demonstrate configuration mechanics and are not legal advice or production compliance mappings.
- Metrics from small synthetic datasets illustrate measurement discipline, not statistically reliable production performance.
- Audit data is local SQLite with synthetic inputs. Production deployment requires access control, encryption, minimization, retention enforcement, and tamper-resistant export.
- The bundled signing secret is only for a repeatable local demo. Production
  requires managed key rotation, authenticated reviewer identities, RBAC, and
  an external transactional commerce adapter.

See [ControlPlane_Final_Proposal_Plan.md](ControlPlane_Final_Proposal_Plan.md) for the full business, governance, metrics, and roadmap plan.
