import type { Metrics } from "@/types/api";

type MetricsSectionProps = {
  metrics: Metrics | null;
  suiteRunning: boolean;
  onRunSuite: () => void;
};

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function MetricsSection({ metrics, suiteRunning, onRunSuite }: MetricsSectionProps) {
  const matrix = metrics?.confusion_matrix;

  return (
    <section className="metrics-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">No opaque trust score</p>
          <h2>Operational scorecard</h2>
        </div>
        <button className="secondary" disabled={suiteRunning} onClick={onRunSuite}>
          {suiteRunning ? "Running evaluation…" : "Run 12-case evaluation"}
        </button>
      </div>

      <div className="metric-grid">
        <article className="metric-card">
          <p>Interactions</p>
          <strong>{metrics?.volume ?? 0}</strong>
          <small>audited decisions</small>
        </article>
        <article className="metric-card">
          <p>Precision</p>
          <strong>{percent(metrics?.precision)}</strong>
          <small>flagged cases confirmed risky</small>
        </article>
        <article className="metric-card">
          <p>Recall</p>
          <strong>{percent(metrics?.recall)}</strong>
          <small>known risky cases detected</small>
        </article>
        <article className="metric-card">
          <p>False-negative rate</p>
          <strong>{percent(metrics?.false_negative_rate)}</strong>
          <small>missed known-risk cases</small>
        </article>
        <article className="metric-card">
          <p>p95 latency</p>
          <strong>
            {metrics?.latency_ms.p95 == null ? "—" : `${metrics.latency_ms.p95} ms`}
          </strong>
          <small>middleware overhead</small>
        </article>
      </div>

      {metrics?.verification_sample_calls_by_radius && (
        <div className="verification-row">
          {Object.entries(metrics.verification_sample_calls_by_radius).map(([radius, count]) => (
            <span key={radius} className="meta-pill">
              {radius}: {count} verification calls
            </span>
          ))}
        </div>
      )}

      <div className="matrix-card">
        <div>
          <p className="kicker">Threshold honesty</p>
          <h3>Confusion matrix</h3>
          <p>
            Warn/edit, hold and block count as interventions. Seeded labels are replaced by
            human review when available.
          </p>
        </div>
        <div className="matrix">
          <div className="matrix-label" />
          <div className="matrix-label">Actually risky</div>
          <div className="matrix-label">Actually safe</div>
          <div className="matrix-label">Intervened</div>
          <div className="matrix-cell good">
            <b>{matrix?.tp ?? 0}</b>
            <span>TP</span>
          </div>
          <div className="matrix-cell warn">
            <b>{matrix?.fp ?? 0}</b>
            <span>FP</span>
          </div>
          <div className="matrix-label">Allowed</div>
          <div className="matrix-cell danger">
            <b>{matrix?.fn ?? 0}</b>
            <span>FN</span>
          </div>
          <div className="matrix-cell neutral">
            <b>{matrix?.tn ?? 0}</b>
            <span>TN</span>
          </div>
        </div>
      </div>
    </section>
  );
}
