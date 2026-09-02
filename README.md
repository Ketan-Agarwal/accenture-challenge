# ControlPlane.ai

ControlPlane.ai is an evidence-aware runtime governance layer for enterprise
AI. It sits between an application and an LLM, evaluates the request, proposed
response, and intended downstream action under a versioned trust policy, then
decides whether to **allow**, **warn/edit**, **hold for human review**, or
**block**.

This hackathon prototype uses synthetic commerce data and deterministic model
responses, making the complete demo repeatable without proprietary data or an
external model API. The full business case, governance model, metrics strategy,
and roadmap are documented in
[ControlPlane_Final_Proposal_Plan.md](ControlPlane_Final_Proposal_Plan.md).


## Table of contents

- [Problem and solution](#problem-and-solution)
- [Key capabilities](#key-capabilities)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Recommended optional integrations](#recommended-optional-integrations)
- [Installation](#installation)
- [Configuration](#configuration)
- [Three-minute judge demo](#three-minute-judge-demo)
- [API](#api)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Repository structure](#repository-structure)
- [Limitations](#limitations)
- [Maintainers](#maintainers)


## Problem and solution

Enterprise AI applications often send model output directly to users or tools.
That creates overlapping risks: a hallucinated policy may trigger a financial
action, expose personal data, and cascade through a multi-step agent before a
human notices. Different use cases also require different latency, risk, and
regulatory trade-offs.

ControlPlane.ai adds a configurable enforcement boundary at the model's
input/output layer. It combines deterministic checks, evidence-based signals,
use-case and regional policies, tiered decisions, human review, and auditable
action execution. It works through model APIs and does not require model
weights, fine-tuning, or internal activations.


## Key capabilities

- Use-case trust profiles for a support bot, internal copilot, and refund agent.
- Regional policy overlays for India- and EU-oriented demo contexts.
- Blast-radius classification from read-only (`R0`) to consequential financial
  action (`R3`).
- Prompt-injection and PII screening with structured evidence and limitations.
- Policy-claim attribution with supported, contradicted, unsupported, and
  unavailable evidence states.
- Deterministic refund recomputation against a synthetic system of record.
- Semantic disagreement as a fallback when no authoritative source exists.
- Session-level cascade-risk detection for multi-turn agent workflows.
- Tiered decisions: allow, warn/edit, hold for review, or block.
- SQLite audit history, reviewer feedback, and honest false-positive/negative
  metrics.
- Side-effect-free policy simulation across profiles and regions.
- Two-phase execution in which an AI may propose a refund, but only a constrained
  Action Gateway may authorize and commit it.
- Short-lived HMAC capabilities bound to the action, route, order, amount,
  policy version, and expiry.
- Persistent exactly-once receipts that prevent duplicate refund execution.


## Architecture

```text
commerce application
  → use-case and regional policy router
  → request and action preflight
  → model-provider boundary
  → applicable evidence checks in parallel
  → hard constraints and weighted decision policy
  → allow, redact, hold, or block
  → signed action capability, only when authorized
  → constrained exactly-once commerce executor
  → SQLite audit, action receipt, feedback, and metrics
```

Hard constraints are separate from the weighted score. A numeric mismatch on an
automated refund or an injection attempt attached to a privileged action cannot
pass simply because unrelated checks were quiet.


## Requirements

Choose either the containerized installation or the local development stack.

### Containerized installation

- [Podman](https://podman.io/) with Compose support, recommended; or
- Docker with Docker Compose.

### Local development

- Python 3.12 or newer.
- [uv](https://docs.astral.sh/uv/).
- Node.js 20 or newer with npm.

The default prototype requires no external LLM API, vector database, or
proprietary dataset.


## Recommended optional integrations

The core installation remains dependency-light and offline-safe. Install only
the detector family needed for an experiment:

- Microsoft Presidio for broader local PII detection.
- `sentence-transformers` with `all-MiniLM-L6-v2` for embedding-based grounding
  and semantic comparison.

Runtime model downloads are disabled by default so the judged demo remains
deterministic.


## Installation

### Podman, recommended

```bash
podman compose up --build
```

### Docker

```bash
docker compose up --build
```

The Compose stack builds non-root backend and frontend containers and persists
the SQLite audit and action ledger in the `audit-data` volume.

Open:

- Dashboard: <http://localhost:3000>
- API documentation: <http://localhost:8000/docs>

Useful Podman commands:

```bash
podman compose ps
podman compose logs -f
podman compose down
```

Remove the synthetic persisted state only when a completely clean demo is
required:

```bash
podman compose down --volumes
```

### Local development

Install and start the backend:

```bash
uv sync --group dev
uv run uvicorn app.main:app --reload
```

In a second terminal, install and start the dashboard:

```bash
cd web
npm install
npm run dev
```


## Configuration

The default policy configuration is stored in
[`config/policies.json`](config/policies.json). It defines profile owners,
permitted actions, checks, signal weights, decision thresholds, disagreement
sample counts, latency budgets, regional overlays, and retention metadata.

Supported environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `CONTROLPLANE_DB_PATH` | SQLite audit and action-ledger location | `controlplane.db` |
| `CONTROLPLANE_ACTION_SECRET` | HMAC key for action capabilities | Ephemeral locally; deterministic demo value in Compose |
| `CONTROLPLANE_ENABLE_LOCAL_EMBEDDINGS` | Enable the pre-cached embedding model | `0` |
| `CONTROLPLANE_ALLOW_MODEL_DOWNLOAD` | Permit an explicit model setup download | Disabled |
| `API_URL` | Backend URL used by the Next.js server-side proxy | `http://127.0.0.1:8000` locally |

Override `CONTROLPLANE_ACTION_SECRET` with a secret-manager-provided random value
outside the synthetic demo. Changing it invalidates unexecuted capabilities.

Optional detector installation:

```bash
# Presidio PII detection; requires a compatible spaCy language model.
uv sync --group dev --extra pii

# Pre-cache all-MiniLM-L6-v2 before enabling local embeddings.
uv sync --group dev --extra embeddings
CONTROLPLANE_ENABLE_LOCAL_EMBEDDINGS=1 uv run uvicorn app.main:app --reload
```

Set `CONTROLPLANE_ALLOW_MODEL_DOWNLOAD=1` only during an explicit setup step,
not during the judged offline demo.


## Three-minute judge demo

1. Open **Action Gateway**, select `ORD-1001`, and propose INR 2,499.
   Deterministic recomputation blocks it, and no execution capability is minted.
2. Change the amount to the valid INR 1,499 and propose again. Show the evidence
   receipt and short-lived authorization, then execute it. The commerce order
   becomes `refunded`, and the action ledger retains a receipt.
3. Replay the execute request through the API. ControlPlane returns the original
   receipt and creates no second refund.
4. Open **Policy Simulator** and run the unsupported-policy example. The same
   evidence produces a warning for lower-risk profiles and a human hold for the
   refund profile without changing production audit metrics.
5. Run the seeded evaluation suite and show precision, recall, false-positive
   and false-negative rates, latency, review overrides, and model-call cost by
   blast radius.


## API

Interactive OpenAPI documentation is available at
<http://127.0.0.1:8000/docs>.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Check runtime health and version |
| `GET` | `/api/scenarios` | List the eight judge-facing scenarios |
| `POST` | `/api/scenarios/{id}/run` | Run one deterministic scenario |
| `POST` | `/api/evaluate` | Evaluate a custom request and proposed response |
| `POST` | `/api/evaluation-suite/run` | Run the independent 12-case labeled suite |
| `GET` | `/api/policies` | Inspect resolved policies |
| `GET` | `/api/policies/versions` | List active and historical policy versions |
| `POST` | `/api/policy-simulator` | Compare profiles without runtime audit side effects |
| `GET` | `/api/commerce/orders` | Read synthetic commerce state and executed refunds |
| `GET` | `/api/actions` | Read the capability-free governed-action ledger |
| `POST` | `/api/actions/propose` | Evaluate and persist a structured refund proposal |
| `POST` | `/api/actions/{id}/review` | Approve, correct, or reject a held action |
| `POST` | `/api/actions/{id}/execute` | Execute an authorized action exactly once |
| `GET` | `/api/audits` | Read recent decision records |
| `POST` | `/api/audits/{id}/review` | Apply a human label or decision override |
| `GET` | `/api/metrics` | Read operational and quality metrics |

Example blocked evaluation:

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

The verified amount is INR 1,499, so the deterministic check returns
`NUMERIC_MISMATCH` and blocks execution.


## Testing

Run the backend test suite:

```bash
uv run pytest
```

Validate and build the dashboard:

```bash
cd web
npm run lint
npm run build
```

The tests cover policy routing, detector behavior, decision constraints, audit
metrics, simulator isolation, signed authorization, token tampering and expiry,
route binding, restart persistence, human review, and exactly-once replay.


## Troubleshooting

### The dashboard cannot reach the API

- Confirm the backend responds at <http://127.0.0.1:8000/api/health>.
- For local development, verify `API_URL` points to the backend.
- For Compose, keep the internal value `http://backend:8000`; do not replace it
  with the host-only address from inside the frontend container.

### A Podman service remains in `starting`

Inspect container status and logs:

```bash
podman compose ps
podman compose logs backend
podman compose logs frontend
```

The frontend waits for the backend health check before starting.

### Local embedding mode does not start

Install the embeddings extra and pre-cache `all-MiniLM-L6-v2`. Runtime downloads
remain disabled unless `CONTROLPLANE_ALLOW_MODEL_DOWNLOAD=1` is explicitly set.

### A previously authorized action can no longer execute

Capabilities expire after five minutes and are invalidated if the signing secret
changes. Submit the action for a fresh evaluation instead of reusing an expired
token.

### The demo contains old audit or refund records

Compose intentionally persists synthetic state. Use
`podman compose down --volumes` only when losing the current demo audit history
is acceptable.


## FAQ

**Q: Does ControlPlane.ai need access to model internals?**

**A:** No. It operates at the application and model API boundary using requests,
responses, evidence sources, and structured intended actions.

**Q: Does semantic agreement prove that a claim is true?**

**A:** No. It measures response stability when ground truth is unavailable. The
signal is reported with that limitation and receives policy-dependent weight.

**Q: Why are blocked actions immutable?**

**A:** A blocked proposal never receives an execution capability. Correcting it
requires a new evaluation, preserving the original decision and audit trail.

**Q: Can the same authorization issue two refunds?**

**A:** No. The SQLite transaction stores one receipt per action and one refund per
order. A valid replay returns the existing receipt without creating a new one.

**Q: Is this a production compliance product?**

**A:** No. It is a working governance prototype demonstrating configurable
controls, honest measurement, and constrained action execution.


## Repository structure

```text
app/                            FastAPI, checks, policy routing, action gateway,
                                simulator, audit, and metrics
config/policies.json            Versioned profiles and regional overlays
data/demo_scenarios.json        Eight judge-facing demo stories
data/evaluation_scenarios.json  Independent labeled evaluation cases
data/orders.csv                 Synthetic commerce system of record
data/policy_docs/               Synthetic governed policy corpus
web/                            Next.js dashboard
tests/                          Backend and API regression tests
compose.yaml                    Podman/Docker Compose stack
ControlPlane_Final_Proposal_Plan.md
```


## Limitations

- Embedding or lexical similarity retrieves related evidence; it does not prove
  entailment.
- Generation agreement measures stability; it does not establish factual truth.
- Regex PII and prompt-injection checks are bounded demonstrations and may miss
  paraphrases or create false positives.
- Policy overlays demonstrate configuration mechanics and are not legal advice
  or production compliance mappings.
- Metrics from small synthetic datasets demonstrate measurement discipline, not
  statistically reliable production performance.
- The local SQLite audit requires production-grade access control, encryption,
  minimization, retention enforcement, and tamper-resistant export.
- Production deployment also requires managed key rotation, authenticated
  reviewer identities, RBAC, and an external transactional commerce adapter.


## Maintainers

- Ketan Agarwal - [Ketan-Agarwal](https://github.com/Ketan-Agarwal)
- Ritika Batra - [Ritika Batra](https://github.com/ritgit24)
- Yatin Bhojwani - [Yatin Bhojwani](https://github.com/yatin-bhojwani)
