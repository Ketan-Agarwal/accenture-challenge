# ControlPlane.ai — Proposal Plan

## 1. Proposal thesis

**ControlPlane.ai is an evidence-aware runtime control layer for enterprise AI.** It sits between an AI-enabled application and a foundation-model API, evaluates the request, response, and intended downstream action, and applies a configurable decision: **allow, warn/edit, hold for human review, or block**.

The central argument is not that hallucination, privacy leakage, or bias can be eliminated. The proposal will show how an enterprise can **measure, govern, and deliberately trade off these risks for each use case** while retaining an audit trail. The product works at the input/output boundary and therefore does not require model weights, fine-tuning, or access to model internals.

### One-sentence pitch

> ControlPlane.ai gives every enterprise AI use case its own evidence requirements, risk budget, and response policy—then proves how each runtime decision was made.

### Differentiation

The proposal should emphasize five differentiators:

1. **Use-case-specific control:** a public support bot, internal copilot, and refund agent do not share one threshold or pipeline.
2. **Evidence fusion, not a single judge:** deterministic rules, source verification, numeric recomputation, PII detection, and model disagreement contribute separate evidence signals.
3. **Honest abstention:** “insufficient evidence” is a supported outcome. Consistent generations increase stability confidence but do not prove factual truth.
4. **Cascade-aware agent governance:** the system considers the intended action and accumulated session risk, not only the latest sentence.
5. **Policy-as-data:** thresholds, checks, geography/industry overlays, escalation rules, and policy versions are configurable and auditable rather than hard-coded.

## 2. Problem framing

Enterprises are deploying generative AI across use cases with materially different consequences. A false FAQ answer may be recoverable; an invented refund policy or autonomous financial action may create direct loss, privacy exposure, and regulatory liability. Existing approaches commonly fail because they:

- apply a uniform safety pipeline regardless of use case or latency budget;
- treat hallucination, privacy, and bias as independent labels even when one output spans several risks;
- assume an authoritative source is always available;
- report only detection accuracy while hiding false-negative cost, human-review load, and alert fatigue;
- assess each response in isolation even when agents create multi-step cascades; and
- encode policy in application logic that becomes stale as organizational or regulatory expectations change.

### Proposed problem statement

> How might an enterprise govern heterogeneous AI applications at runtime, using only API-level inputs and outputs, while balancing latency, user experience, human-review capacity, and the asymmetric cost of missed risks?

## 3. Users and stakeholders

| Stakeholder | Need | Prototype evidence |
|---|---|---|
| Application/product owner | Ship AI features without one-size-fits-all friction | Use-case profiles and latency budgets |
| Risk/compliance owner | Define policy and explain decisions | Versioned policy view and audit records |
| Human reviewer | Understand why a case was held and act quickly | Evidence bundle and override workflow |
| AI/platform engineer | Integrate one control layer across models/apps | Stable middleware API and provider abstraction |
| Executive/auditor | See whether risk is improving without metric theatre | Confusion matrix, coverage, latency, overrides, and cost measures |
| End user | Receive useful output without hidden unsafe behavior | Allow, edited warning, review, and block experiences |

## 4. Solution scope

### In scope for the working prototype

- Three policy profiles: `support_bot`, `internal_copilot`, and `refund_agent`.
- Request/action blast-radius classification using explicit action metadata plus deterministic indicators.
- PII detection and redaction for a bounded set of identifiers.
- Claim extraction and attribution against simulated policy documents.
- Deterministic recomputation of refund values from simulated order data.
- Multi-generation disagreement scoring when no authoritative evidence is available.
- Overlapping risk signals attached to the same claim or output.
- Session-level accumulated risk for a small multi-step agent scenario.
- Tiered decisions: `allow`, `warn_or_edit`, `hold_for_human`, and `block`.
- Versioned policy configuration with use-case and geography/industry overlays.
- SQLite audit trail, human labels/overrides, and a metrics dashboard.
- Simulated LLM responses by default, with a replaceable model-provider interface for a live API demo.

### Explicit non-goals

- Claiming universal hallucination, bias, or PII detection.
- Interpreting consistency across model samples as proof of truth.
- Building a production-grade legal compliance engine.
- Training or fine-tuning a foundation model.
- Supporting every document type, language, geography, or enterprise action.
- Automatically learning new thresholds from a very small demo dataset.

These boundaries make the prototype credible: it demonstrates the control mechanism and measurement discipline without overstating what a limited dataset can establish.

## 5. Core system design

```mermaid
flowchart LR
    A[AI-enabled application] --> B[Request and action preflight]
    B --> C[Use-case and policy router]
    C --> D[Foundation model adapter]
    D --> E[Parallel evidence checks]
    E --> F[Evidence fusion and decision engine]
    F -->|Allow or edit| G[End user / downstream tool]
    F -->|Hold| H[Human review queue]
    F -->|Block| I[Safe fallback]
    B --> J[(Audit store)]
    E --> J
    F --> J
    H --> J
    J --> K[Governance and metrics dashboard]
```

### Runtime sequence

1. The calling application supplies the use case, user request, intended action, region, session ID, and available business context.
2. The router resolves a versioned policy profile and permitted latency budget.
3. Preflight checks identify sensitive input and estimate blast radius before any action is permitted.
4. The model adapter obtains a response. The default demo uses deterministic fixtures; a live provider remains optional.
5. Applicable checks run concurrently where possible:
   - PII/entity detection;
   - policy-claim attribution;
   - refund recomputation;
   - response-sample disagreement when grounding is unavailable; and
   - session/cascade-risk assessment.
6. Each checker returns a structured signal containing severity, confidence, evidence, limitations, and applicable risk labels. Signals may carry multiple labels.
7. The decision engine combines evidence according to the active policy, blast radius, and session history.
8. The complete decision bundle is logged. Held cases can be confirmed, dismissed, or overridden by a human.

### Why these checks are framed as evidence

- **Document similarity is retrieval evidence, not entailment.** A matched paragraph can support review, but a close embedding alone cannot prove that the response follows the policy.
- **Semantic disagreement measures instability, not factuality.** Several consistent wrong answers remain possible. The signal is used mainly when no ground truth exists and is weighted more strongly for high-impact actions.
- **Rules are bounded controls, not universal classifiers.** The demo will show their scope and leave a clear extension point for learned or AI-as-judge detectors.

## 6. Policy and governance design

Governance is a first-class product surface, not a paragraph added after the detector design.

### Policy profile fields

Each versioned profile should define:

- use case and owner;
- allowed model/provider;
- risk appetite and permitted action types;
- required and optional checks;
- thresholds and signal weights;
- maximum latency and timeout behavior;
- decision matrix and safe fallback;
- human-review triggers and reviewer role;
- data-retention/redaction rules;
- geography and industry overlays;
- effective date, version, approver, and change reason.

### Example policy behavior

| Profile | Typical latency target | Evidence requirement | Default under uncertainty | High-impact action behavior |
|---|---:|---|---|---|
| Support bot | Low | PII plus policy grounding when a policy is cited | Warn/edit | Cannot execute financial actions |
| Internal copilot | Moderate | PII plus source attribution where available | Warn with provenance gap | Hold actions leaving the enterprise |
| Refund agent | Higher | Order recomputation, policy grounding, PII, and session risk | Hold | Block mismatch; require approval above configured limit |

The numerical latency targets and approval limits will be presented as **demo assumptions**, not universal benchmarks.

### Change-control workflow

1. A policy owner proposes a new version with a reason and expected impact.
2. The version is evaluated against a labeled regression set before activation.
3. The dashboard compares old and new false-positive, false-negative, latency, and review-load estimates.
4. An authorized approver activates or rejects it.
5. Every runtime record stores the exact policy version used, enabling replay and audit.

The prototype need only demonstrate policy resolution, version display, and replayable audit metadata. Full enterprise identity and approval infrastructure belongs in later phases.

## 7. Decision logic

The decision engine will avoid a naive “count the flags” design. It should use:

- **hard constraints:** for example, a recomputed financial mismatch blocks an automated refund;
- **risk-weighted evidence:** the same uncertainty can be tolerated for a draft FAQ but deferred for a financial action;
- **evidence availability:** missing grounding is different from evidence contradicting a claim;
- **session accumulation:** repeated warnings or a risky chain can escalate a later step; and
- **policy-specific thresholds:** thresholds reflect business risk and review capacity.

Every outcome should include a machine-readable reason code and a plain-language explanation. The system will not collapse all risks into one unexplained score.

## 8. Demo scenarios

The demo should tell one coherent story through seven seeded scenarios:

| # | Scenario | Expected outcome | Capability demonstrated |
|---:|---|---|---|
| 1 | Support bot answers a grounded delivery question | Allow | Low-friction path and attribution |
| 2 | Support response exposes an email and card-like number | Edit/warn | PII redaction and overlapping risk labels |
| 3 | Bot invents a refund-policy clause | Hold | Unsupported policy claim and evidence bundle |
| 4 | Refund agent proposes an amount different from order data | Block | Blast radius plus deterministic recomputation |
| 5 | No source exists and repeated generations materially disagree | Hold for high-risk profile | Ground-truth fallback with honest uncertainty |
| 6 | The same uncertain answer is requested by the low-risk support profile | Warn | Different policies for identical evidence |
| 7 | A multi-step agent moves from lookup to email to refund | Escalate before action | Accumulated cascade risk |

For each scenario, the UI will show the selected policy, checks run, evidence, latency, decision, and audit ID. A reviewer will label at least one held result, after which the metrics view will update.

## 9. Metrics and evaluation plan

### Offline safety evaluation

A small labeled scenario set will include clean, privacy-risk, unsupported-claim, numeric-mismatch, and overlapping-risk examples. Results must be segmented by use case and risk type rather than reported only as one aggregate accuracy number.

Report:

- true positives, false positives, true negatives, and false negatives;
- precision and recall;
- false-positive rate and false-negative rate;
- intervention rate by outcome;
- evidence coverage: fraction of claims for which authoritative evidence was available;
- deferral/review rate and estimated reviewer workload; and
- results at the selected threshold plus at least one stricter/looser alternative.

Because missed high-impact risks are more costly than nuisance warnings, the proposal will include a **cost-weighted loss**:

`expected risk cost = Σ(outcome count × business-assigned outcome cost)`

This makes alert-fatigue tuning explicit. It does not pretend that one threshold is objectively correct.

### Runtime and operational metrics

- median and p95 end-to-end latency;
- per-check latency and timeout rate;
- allow/edit/hold/block distribution;
- human time-to-review;
- reviewer agreement and override rate;
- policy version adoption and drift in intervention rate;
- audit completeness; and
- model/provider error and fallback rate.

### Trustworthiness scorecard

The dashboard should not expose one opaque “trust score.” It will present four dimensions separately:

1. **Safety effectiveness:** recall, false-negative rate, and cost-weighted loss.
2. **Operational burden:** false-positive rate, deferrals, and reviewer workload.
3. **Evidence quality:** grounding coverage, contradiction/unsupported rates, and unavailable-evidence rate.
4. **Reliability:** latency, timeouts, audit completeness, and fallback behavior.

### Feedback loop

Human review creates labels, not automatic truth. The initial feedback loop will:

1. record confirmation, dismissal, or override with a reason;
2. update dashboard metrics;
3. surface recurring false-positive/negative categories; and
4. propose threshold or rule changes for offline evaluation.

No threshold will silently change in production. A policy owner must review a regression comparison and approve a new version.

## 10. Business case

### Value levers

- reduce preventable loss from incorrect automated actions;
- reduce privacy and compliance incident exposure;
- shorten approval cycles for new AI use cases by reusing a common control plane;
- reduce manual review through risk-based routing instead of reviewing every interaction; and
- produce defensible evidence for internal audit and enterprise customers.

### Quantification model

The proposal should use transparent, editable assumptions rather than unsupported savings claims:

- weekly AI interactions by use case;
- baseline harmful-output rate from a labeled sample;
- average cost by incident class;
- detection recall at the chosen policy threshold;
- reviewer volume, minutes per review, and labor cost;
- engineering/compliance hours saved per new AI use case; and
- infrastructure/model cost of additional checks and samples.

Then calculate:

`annual net benefit = avoided incident cost + governance efficiency − review cost − compute/platform cost`

The final proposal should include conservative, expected, and aggressive scenarios, with every assumption labeled. The prototype will expose the measurements needed for this model but will not claim statistically reliable ROI from its small simulated dataset.

### Adoption model

The likely enterprise path is a platform capability deployed as API middleware, initially for a high-value workflow. Commercialization can be framed as usage-based platform pricing plus governance/analytics tiers, while keeping the Round 2 focus on enterprise value rather than speculative revenue.

## 11. Phased roadmap

### Phase 0 — Design and evaluation contract

- agree on use cases, actions, risk taxonomy, decision costs, and human-review capacity;
- construct the labeled regression set; and
- define policy ownership and audit requirements.

### Phase 1 — Round 2 prototype

- three use-case profiles and seven demo scenarios;
- bounded PII, grounding, disagreement, numeric, and cascade checks;
- tiered decision engine;
- audit log, reviewer feedback, and metrics dashboard; and
- deterministic demo mode with optional live model adapter.

### Phase 2 — Controlled pilot

- integrate one real, non-critical enterprise use case in shadow mode;
- connect governed sources and enterprise identity;
- measure baseline, tune thresholds, and capacity-plan review queues;
- add policy regression tests, monitoring, and access controls; and
- complete privacy/security assessment.

### Phase 3 — High-impact workflows

- add action-level authorization and approval boundaries;
- expand claim verification beyond similarity toward entailment/citation validation;
- add stronger PII/entity tooling and adversarial testing;
- introduce session and agent trace analysis; and
- support policy promotion/rollback with formal approvals.

### Phase 4 — Enterprise scale

- multi-region deployment and jurisdiction/industry policy packs;
- model/provider benchmarking and routing;
- continuous drift monitoring and red-team regression suites;
- SIEM/GRC integrations, immutable audit export, and SLOs; and
- federated governance across business units.

## 12. Risks and mitigations

| Risk | Why it matters | Mitigation / honest boundary |
|---|---|---|
| Consistent but false generations | Low disagreement can create false confidence | Never treat agreement as factual proof; increase review for high-impact ungrounded actions |
| Retrieval similarity without entailment | Related text may not support the exact claim | Show source evidence; distinguish supported, contradicted, unsupported, and unavailable |
| Keyword/rule evasion | Simple classifiers miss paraphrases and new patterns | Require explicit action metadata; add learned classifiers later; maintain adversarial regression tests |
| Alert fatigue | Users bypass a noisy system | Tune by cost and review capacity; segment metrics; offer edit/warn instead of binary blocking |
| False negatives | Missed risks can create material harm | Hard constraints for deterministic checks; conservative high-impact defaults; post-hoc sampling and red-team tests |
| Detector/model correlation | An AI judge may repeat the generator’s mistake | Fuse heterogeneous evidence and prioritize deterministic business data when available |
| Sensitive audit logs | Safety telemetry can become a new privacy store | Redact/minimize, role-limit, encrypt, and configure retention; prototype uses synthetic data only |
| Policy drift | Rules become stale or inconsistent | Versioning, ownership, effective dates, regression testing, approval, and rollback |
| Added latency/cost | Extra checks can damage the product experience | Route checks by use case, parallelize, cache governed sources, set timeouts, and measure p95 latency |
| Human review bottleneck | Deferral can halt operations | Capacity-aware thresholds, prioritized queues, clear evidence bundles, and fail-safe workflows |
| Demo overfitting | Seeded cases can exaggerate effectiveness | Separate demo stories from a broader hidden regression set and label sample-size limitations |

## 13. Prototype implementation plan (held until approval)

### Proposed stack

- **Backend:** Python and FastAPI.
- **Decision/audit data:** SQLite for the prototype, behind a repository abstraction.
- **Configuration:** versioned JSON policy profiles validated at startup.
- **Frontend:** a lightweight web dashboard optimized for a clear live demo.
- **Test data:** synthetic policy documents, orders, sessions, and labeled scenarios.
- **Model integration:** provider interface with deterministic fixtures by default and an optional environment-configured live provider.

### Intended repository shape

```text
controlplane-ai/
├── app/                 # API, pipeline, checks, policy, audit, metrics
├── config/              # Versioned use-case and overlay policies
├── data/                # Synthetic policies, orders, and scenarios
├── frontend/            # Demo dashboard
├── tests/               # Unit, policy-regression, and end-to-end tests
├── docs/                # Business proposal, architecture, and demo script
├── README.md
└── requirements/lock files
```

### Definition of done for the prototype

- All seven seeded scenarios execute through the real middleware pipeline.
- At least three profiles demonstrably produce different decisions for shared evidence.
- Each decision names its policy version, signals, evidence availability, and reason codes.
- High-impact numeric mismatch cannot pass due to a weighted-score accident.
- Human feedback changes the displayed evaluation metrics but not live policy automatically.
- The dashboard reports both false positives and false negatives from labeled cases.
- An end-to-end test validates request → checks → decision → audit → review → metrics.
- The repository runs from documented commands without requiring proprietary data.
- A short demo can be completed reliably in under five minutes.

## 14. Submission package plan

### Detailed business proposal

Recommended narrative order:

1. Executive summary and quantified problem.
2. Why existing one-size-fits-all guardrails fail.
3. User/stakeholder needs.
4. ControlPlane.ai value proposition.
5. Architecture and runtime decision flow.
6. Technical novelty and evidence strategy.
7. Governance and configurable policies.
8. Metrics, alert-fatigue tradeoff, and evaluation results.
9. Business case and adoption approach.
10. Phased roadmap.
11. Risks, limitations, and mitigations.
12. Prototype results and next ask.

### Public repository

- concise setup and demo commands;
- architecture diagram and policy examples;
- synthetic-data notice and security limitations;
- automated test instructions and sample output;
- screenshots/GIF where useful; and
- license and contribution notes before publication.

### Demo video (target: 4–5 minutes)

1. **0:00–0:30:** enterprise problem and thesis.
2. **0:30–1:00:** three use-case policies and different risk appetites.
3. **1:00–2:45:** grounded allow, invented-policy hold, and refund-mismatch block.
4. **2:45–3:30:** no-ground-truth disagreement and cascade-risk scenario.
5. **3:30–4:15:** audit explanation, human override, and metrics update.
6. **4:15–4:45:** limitations, business value, and roadmap.

## 15. Decisions required before implementation

The proposal plan recommends the following defaults unless the team changes them:

1. Build a **credible narrow control plane**, not twelve shallow detectors.
2. Make the **refund agent** the high-impact hero workflow.
3. Use **synthetic deterministic responses** for the judged demo, with live API access optional.
4. Treat **governance and metrics as product features**, not documentation-only sections.
5. Show **false positives, false negatives, and review burden** explicitly.
6. Avoid claiming that embeddings or semantic entropy determine truth.
7. Keep automated policy learning out of the MVP; use approval-gated feedback instead.

Implementation should begin only after this scope and narrative are approved.
