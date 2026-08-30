"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { PolicySimulationRow } from "@/types/api";

type Props = { onNotify: (message: string) => void };

const EXAMPLES = {
  unsupported: {
    prompt: "Can I get a refund even though the return window closed?",
    response: "Yes. Our goodwill policy guarantees a full refund after the return window.",
    action: "answer",
  },
  privacy: {
    prompt: "Summarize this customer issue for the team.",
    response: "Customer Priya can be reached at priya@example.com and requested an escalation.",
    action: "answer",
  },
};

export function PolicySimulator({ onNotify }: Props) {
  const [prompt, setPrompt] = useState(EXAMPLES.unsupported.prompt);
  const [response, setResponse] = useState(EXAMPLES.unsupported.response);
  const [action, setAction] = useState(EXAMPLES.unsupported.action);
  const [region, setRegion] = useState("IN");
  const [results, setResults] = useState<PolicySimulationRow[]>([]);
  const [running, setRunning] = useState(false);

  function loadExample(name: keyof typeof EXAMPLES) {
    const example = EXAMPLES[name];
    setPrompt(example.prompt);
    setResponse(example.response);
    setAction(example.action);
    setResults([]);
  }

  async function run() {
    setRunning(true);
    try {
      const simulation = await api.simulatePolicies({
        prompt,
        proposed_response: response,
        action,
        region,
        profiles: ["support_bot", "internal_copilot", "refund_agent"],
      });
      setResults(simulation.results);
      onNotify("One request evaluated against three trust contracts");
    } catch (error) {
      onNotify(error instanceof Error ? error.message : "Simulation failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="simulator-section" id="policy-simulator">
      <div className="section-heading simulator-heading">
        <div>
          <p className="eyebrow">Context changes the decision</p>
          <h2>Policy Simulator</h2>
          <p className="section-copy">Same evidence. Different use case. Deliberately different intervention.</p>
        </div>
        <div className="example-switch"><button onClick={() => loadExample("unsupported")}>Unsupported policy</button><button onClick={() => loadExample("privacy")}>PII disclosure</button></div>
      </div>
      <div className="simulator-shell">
        <div className="simulator-inputs">
          <label>Customer prompt<textarea rows={3} value={prompt} onChange={(event) => setPrompt(event.target.value)} /></label>
          <label>Proposed model response<textarea rows={4} value={response} onChange={(event) => setResponse(event.target.value)} /></label>
          <div className="simulator-controls"><label>Intended action<select value={action} onChange={(event) => setAction(event.target.value)}><option value="answer">Answer only</option><option value="draft_email">Draft email</option><option value="send_email">Send email</option><option value="issue_refund">Issue refund</option></select></label><label>Region<select value={region} onChange={(event) => setRegion(event.target.value)}><option value="IN">India</option><option value="EU">European Union</option></select></label></div>
          <button className="secondary simulator-run" disabled={running || !prompt || !response} onClick={run}>{running ? "Comparing policies…" : "Compare trust contracts"} <span>→</span></button>
        </div>
        <div className="simulation-results">
          {results.length === 0 ? <div className="comparison-empty"><div><span>S</span><span>I</span><span>R</span></div><h3>Three profiles, one request</h3><p>Run the simulator to reveal how risk appetite and blast radius change enforcement.</p></div> : results.map((result, index) => <article className="comparison-card" key={`${result.profile}-${result.region}`}>
            <header><span className="profile-index">0{index + 1}</span><div><p>{result.profile.replaceAll("_", " ")}</p><small>{result.region} · {result.policy_version ?? "active policy"}</small></div><span className={`decision-badge ${result.decision}`}>{result.decision.replaceAll("_", " ")}</span></header>
            <div className="comparison-risk"><span>Risk</span><div><i style={{ width: `${result.risk_score}%` }} /></div><b>{result.risk_score.toFixed(1)}</b></div>
            <p>{result.decision_summary}</p>
            <footer>{(result.reason_codes ?? []).slice(0, 3).map((code) => <span key={code}>{code}</span>)}{result.checks_run && <em>{result.checks_run.length} checks</em>}</footer>
          </article>)}
        </div>
      </div>
    </section>
  );
}
