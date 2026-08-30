"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  EvaluationResult,
  Metrics,
  PolicyVersions,
  PolicyView,
  Scenario,
} from "@/types/api";
import { DecisionPanel } from "@/components/DecisionPanel";
import { GovernancePanel } from "@/components/GovernancePanel";
import { Hero } from "@/components/Hero";
import { MetricsSection } from "@/components/MetricsSection";
import { ScenarioPanel } from "@/components/ScenarioPanel";
import { Toast } from "@/components/Toast";
import { TopBar } from "@/components/TopBar";

export default function DashboardPage() {
  const [online, setOnline] = useState(false);
  const [apiVersion, setApiVersion] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selected, setSelected] = useState<Scenario | null>(null);
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [policies, setPolicies] = useState<PolicyView[]>([]);
  const [versions, setVersions] = useState<PolicyVersions | null>(null);
  const [running, setRunning] = useState(false);
  const [suiteRunning, setSuiteRunning] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2500);
  }, []);

  const refreshMetrics = useCallback(async () => {
    setMetrics(await api.metrics());
  }, []);

  useEffect(() => {
    async function bootstrap() {
      try {
        const health = await api.health();
        setOnline(true);
        setApiVersion(health.version);
        const [scenarioList, metricsData, policyList, versionInfo] = await Promise.all([
          api.scenarios(),
          api.metrics(),
          api.policies(),
          api.policyVersions(),
        ]);
        setScenarios(scenarioList);
        setMetrics(metricsData);
        setPolicies(policyList);
        setVersions(versionInfo);
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Failed to connect to API");
      }
    }
    void bootstrap();
  }, [showToast]);

  async function handleRunScenario() {
    if (!selected) return;
    setRunning(true);
    setReviewed(false);
    try {
      const evaluation = await api.runScenario(selected.id);
      setResult(evaluation);
      await refreshMetrics();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Scenario run failed");
    } finally {
      setRunning(false);
    }
  }

  async function handleRunSuite() {
    setSuiteRunning(true);
    try {
      const suite = await api.runEvaluationSuite();
      setMetrics(suite.metrics);
      showToast(`${suite.count} independent evaluation cases completed`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Evaluation suite failed");
    } finally {
      setSuiteRunning(false);
    }
  }

  async function handleReview(label: "safe" | "unsafe") {
    if (!result) return;
    try {
      await api.review(result.audit_id, label);
      setReviewed(true);
      await refreshMetrics();
      showToast(`Human label recorded: ${label}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Review failed");
    }
  }

  return (
    <div className="shell">
      <TopBar online={online} apiVersion={apiVersion} />
      <main>
        <Hero />
        <section className="workspace-grid">
          <ScenarioPanel
            scenarios={scenarios}
            selectedId={selected?.id ?? null}
            onSelect={(scenario) => {
              setSelected(scenario);
              setResult(null);
              setReviewed(false);
            }}
          />
          <DecisionPanel
            selected={selected}
            result={result}
            running={running}
            reviewed={reviewed}
            onRun={handleRunScenario}
            onReview={handleReview}
          />
        </section>
        <GovernancePanel policies={policies} versions={versions} />
        <MetricsSection
          metrics={metrics}
          suiteRunning={suiteRunning}
          onRunSuite={handleRunSuite}
        />
      </main>
      <Toast message={toast} />
    </div>
  );
}
