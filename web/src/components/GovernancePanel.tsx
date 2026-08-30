import type { PolicyVersions, PolicyView } from "@/types/api";

type GovernancePanelProps = {
  policies: PolicyView[];
  versions: PolicyVersions | null;
};

export function GovernancePanel({ policies, versions }: GovernancePanelProps) {
  if (!versions) return null;

  const uniqueProfiles = [...new Set(policies.map((policy) => policy.profile))];

  return (
    <section className="governance-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Policy-as-data</p>
          <h2>Governance surface</h2>
        </div>
        <div className="version-badge">
          Active policy <strong>{versions.active_version}</strong>
        </div>
      </div>

      <div className="governance-grid">
        <article className="governance-card">
          <p className="kicker">Version control</p>
          <h3>Policy lineage</h3>
          <ul className="version-list">
            {versions.version_history.map((version) => (
              <li key={version} className={version === versions.active_version ? "active" : ""}>
                <span>{version}</span>
                {version === versions.active_version ? (
                  <em>active</em>
                ) : (
                  <em>superseded</em>
                )}
              </li>
            ))}
          </ul>
        </article>

        <article className="governance-card wide">
          <p className="kicker">Resolved profiles</p>
          <h3>Use-case × region matrix</h3>
          <div className="policy-table-wrap">
            <table className="policy-table">
              <thead>
                <tr>
                  <th>Profile</th>
                  <th>Region</th>
                  <th>Risk appetite</th>
                  <th>Checks</th>
                  <th>Retention</th>
                  <th>Consent</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((policy) => (
                  <tr key={`${policy.profile}-${policy.region}`}>
                    <td>{policy.profile.replaceAll("_", " ")}</td>
                    <td>{policy.region}</td>
                    <td>{policy.risk_appetite}</td>
                    <td>{policy.checks.join(", ")}</td>
                    <td>{policy.retention_days}d</td>
                    <td>{policy.consent_required ? "required" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="governance-card">
          <p className="kicker">Coverage</p>
          <h3>Configured scope</h3>
          <div className="scope-tags">
            {uniqueProfiles.map((profile) => (
              <span key={profile} className="tag">
                {profile.replaceAll("_", " ")}
              </span>
            ))}
          </div>
          <p className="scope-note">
            {versions.regions.length} jurisdiction overlays · schema {versions.schema_version}
          </p>
        </article>
      </div>
    </section>
  );
}
