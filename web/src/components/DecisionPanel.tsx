import type { EvaluationResult, Scenario } from "@/types/api";

type DecisionPanelProps = {
  selected: Scenario | null;
  result: EvaluationResult | null;
  running: boolean;
  reviewed: boolean;
  onRun: () => void;
  onReview: (label: "safe" | "unsafe") => void;
};

export function DecisionPanel({
  selected,
  result,
  running,
  reviewed,
  onRun,
  onReview,
}: DecisionPanelProps) {
  return (
    <section className="decision-panel panel">
      <div className="panel-heading">
        <div>
          <p className="kicker">Live middleware</p>
          <h2>Decision trace</h2>
        </div>
        <button className="primary" disabled={!selected || running} onClick={onRun}>
          {running ? "Evaluating…" : "Run scenario"} {!running && <span>→</span>}
        </button>
      </div>

      {!result ? (
        <div className="empty-state">
          <div className="radar">
            <i />
            <i />
            <i />
          </div>
          <h3>{selected ? "Ready to run" : "Select a scenario"}</h3>
          <p>
            {selected
              ? `"${selected.title}" will run through the real policy router, evidence checks, decision engine and audit store.`
              : "Run a scenario through the actual policy router, evidence checks, decision engine and audit store."}
          </p>
        </div>
      ) : (
        <div className="result-view">
          <div className="result-summary">
            <div>
              <p className="kicker">Final intervention</p>
              <div className={`decision-badge ${result.decision}`}>
                {result.decision.replaceAll("_", " ")}
              </div>
            </div>
            <div className="risk-meter-wrap">
              <div className="risk-label">
                <span>Evidence-weighted risk</span>
                <strong>{result.risk_score.toFixed(1)}/100</strong>
              </div>
              <div className="risk-meter">
                <span style={{ width: `${result.risk_score}%` }} />
              </div>
            </div>
          </div>

          <p className="decision-summary">{result.decision_summary}</p>

          <div className="meta-row">
            {[
              `${result.policy.profile} · v${result.policy.version}`,
              `${result.blast_radius} · ${result.action}`,
              `${result.region} · retain ${result.policy.retention_days}d`,
              `${result.total_latency_ms.toFixed(2)} ms`,
              `${result.check_cost.model_calls} model calls`,
              `audit ${result.audit_id}`,
            ].map((item) => (
              <span key={item} className="meta-pill">
                {item}
              </span>
            ))}
          </div>

          <div className="response-box">
            <p className="kicker">Response released downstream</p>
            <p>
              {result.safe_response ??
                "Not released — the output was contained by policy."}
            </p>
          </div>

          <div className="signals-heading">
            <h3>Evidence bundle</h3>
            <span>
              {result.signals.length} signal{result.signals.length === 1 ? "" : "s"}
            </span>
          </div>

          <div className="signals">
            {result.signals.length ? (
              result.signals.map((signal) => (
                <article
                  key={`${signal.check_id}-${signal.code}`}
                  className={`signal ${signal.severity === 0 ? "ok" : ""}`}
                >
                  <span className="signal-dot" />
                  <div>
                    <h4>{signal.summary}</h4>
                    <p>{signal.evidence[0] ?? signal.limitations}</p>
                  </div>
                  <span className="signal-code">{signal.code}</span>
                </article>
              ))
            ) : (
              <article className="signal ok">
                <span className="signal-dot" />
                <div>
                  <h4>No adverse evidence detected</h4>
                  <p>Configured checks completed without raising a risk signal.</p>
                </div>
                <span className="signal-code">CLEAR</span>
              </article>
            )}
          </div>

          <div className={`review-bar ${reviewed ? "reviewed" : ""}`}>
            <div>
              <p className="kicker">Human feedback</p>
              <span>Was the underlying case actually risky?</span>
            </div>
            <div>
              <button
                type="button"
                className="review-button safe"
                disabled={reviewed}
                onClick={() => onReview("safe")}
              >
                Mark safe
              </button>
              <button
                type="button"
                className="review-button unsafe"
                disabled={reviewed}
                onClick={() => onReview("unsafe")}
              >
                Mark unsafe
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
