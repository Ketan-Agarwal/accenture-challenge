import type { Scenario } from "@/types/api";

type ScenarioPanelProps = {
  scenarios: Scenario[];
  selectedId: string | null;
  onSelect: (scenario: Scenario) => void;
};

export function ScenarioPanel({ scenarios, selectedId, onSelect }: ScenarioPanelProps) {
  return (
    <aside className="scenario-panel panel">
      <div className="panel-heading">
        <div>
          <p className="kicker">Demo runbook</p>
          <h2>Scenarios</h2>
        </div>
        <span className="count">{scenarios.length}</span>
      </div>
      <div className="scenario-list" aria-live="polite">
        {scenarios.map((scenario, index) => (
          <button
            key={scenario.id}
            type="button"
            className={`scenario ${selectedId === scenario.id ? "selected" : ""}`}
            onClick={() => onSelect(scenario)}
          >
            <span className="scenario-index">{String(index + 1).padStart(2, "0")}</span>
            <span>
              <h3>{scenario.title}</h3>
              <p>{scenario.description}</p>
              <span className="scenario-tags">
                <span className="tag">{scenario.use_case.replaceAll("_", " ")}</span>
                <span className="tag">{scenario.action}</span>
                <span className="tag">{scenario.region}</span>
              </span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
