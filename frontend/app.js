const state = { scenarios: [], selected: null, lastResult: null };

const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  if (!response.ok) throw new Error((await response.json()).detail || 'Request failed');
  return response.json();
}

function renderScenarios() {
  $('scenario-count').textContent = state.scenarios.length;
  $('scenario-list').innerHTML = state.scenarios.map((scenario, index) => `
    <button class="scenario ${state.selected?.id === scenario.id ? 'selected' : ''}" data-id="${scenario.id}">
      <span class="scenario-index">${String(index + 1).padStart(2, '0')}</span>
      <span>
        <h3>${scenario.title}</h3>
        <p>${scenario.description}</p>
        <span class="scenario-tags"><span class="tag">${scenario.use_case.replace('_', ' ')}</span><span class="tag">${scenario.action}</span><span class="tag">${scenario.region}</span></span>
      </span>
    </button>`).join('');
  document.querySelectorAll('.scenario').forEach(button => button.addEventListener('click', () => {
    state.selected = state.scenarios.find(scenario => scenario.id === button.dataset.id);
    $('run-button').disabled = false;
    renderScenarios();
  }));
}

function renderResult(result) {
  state.lastResult = result;
  $('empty-state').classList.add('hidden');
  $('result-view').classList.remove('hidden');
  const badge = $('decision-badge');
  badge.className = `decision-badge ${result.decision}`;
  badge.textContent = result.decision.replaceAll('_', ' ');
  $('risk-score').textContent = `${result.risk_score.toFixed(1)}/100`;
  $('risk-fill').style.width = `${result.risk_score}%`;
  $('safe-response').textContent = result.safe_response || 'Not released — the output was contained by policy.';
  $('meta-row').innerHTML = [
    `${result.policy.profile} · v${result.policy.version}`,
    `${result.blast_radius} · ${result.action}`,
    `${result.region} · retain ${result.policy.retention_days}d`,
    `${result.total_latency_ms.toFixed(2)} ms`,
    `audit ${result.audit_id}`,
  ].map(item => `<span class="meta-pill">${item}</span>`).join('');
  $('signal-count').textContent = `${result.signals.length} signal${result.signals.length === 1 ? '' : 's'}`;
  $('signals').innerHTML = result.signals.length ? result.signals.map(signal => `
    <article class="signal ${signal.severity === 0 ? 'ok' : ''}">
      <span class="signal-dot"></span>
      <div><h4>${signal.summary}</h4><p>${signal.evidence[0] || signal.limitations}</p></div>
      <span class="signal-code">${signal.code}</span>
    </article>`).join('') : '<article class="signal ok"><span class="signal-dot"></span><div><h4>No adverse evidence detected</h4><p>Configured checks completed without raising a risk signal.</p></div><span class="signal-code">CLEAR</span></article>';
  $('review-bar').classList.remove('reviewed');
  document.querySelectorAll('.review-button').forEach(button => { button.disabled = false; });
}

function percent(value) { return value == null ? '—' : `${(value * 100).toFixed(1)}%`; }

async function refreshMetrics() {
  const metrics = await api('/api/metrics');
  $('metric-volume').textContent = metrics.volume;
  $('metric-precision').textContent = percent(metrics.precision);
  $('metric-recall').textContent = percent(metrics.recall);
  $('metric-fnr').textContent = percent(metrics.false_negative_rate);
  $('metric-p95').textContent = metrics.latency_ms.p95 == null ? '—' : `${metrics.latency_ms.p95} ms`;
  ['tp', 'fp', 'fn', 'tn'].forEach(key => $(`matrix-${key}`).textContent = metrics.confusion_matrix[key]);
}

async function init() {
  try {
    const health = await api('/api/health');
    document.querySelector('.pulse').classList.add('online');
    $('api-status').textContent = `· ${health.version}`;
    state.scenarios = await api('/api/scenarios');
    renderScenarios();
    await refreshMetrics();
  } catch (error) { toast(error.message); }
}

$('run-button').addEventListener('click', async () => {
  if (!state.selected) return;
  const button = $('run-button');
  button.disabled = true;
  button.textContent = 'Evaluating…';
  try {
    renderResult(await api(`/api/scenarios/${state.selected.id}/run`, { method: 'POST' }));
    await refreshMetrics();
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.innerHTML = 'Run scenario <span>→</span>'; }
});

$('suite-button').addEventListener('click', async () => {
  const button = $('suite-button');
  button.disabled = true;
  button.textContent = 'Running evaluation…';
  try {
    const result = await api('/api/evaluation-suite/run', { method: 'POST' });
    await refreshMetrics();
    toast(`${result.count} independent evaluation cases completed`);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; button.textContent = 'Run 12-case evaluation'; }
});

document.querySelectorAll('.review-button').forEach(button => button.addEventListener('click', async () => {
  if (!state.lastResult) return;
  try {
    await api(`/api/audits/${state.lastResult.audit_id}/review`, {
      method: 'POST',
      body: JSON.stringify({ human_label: button.dataset.label, note: 'Submitted from demo dashboard' }),
    });
    document.querySelectorAll('.review-button').forEach(item => { item.disabled = true; });
    $('review-bar').classList.add('reviewed');
    await refreshMetrics();
    toast(`Human label recorded: ${button.dataset.label}`);
  } catch (error) { toast(error.message); }
}));

init();
