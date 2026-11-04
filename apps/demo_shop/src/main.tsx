import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Product = { id: string; name: string; description: string; category: string; price: number; icon: string };
type Measurement = { ms: number; id: string; status: number; version: string };

function Shop() {
  const [query, setQuery] = useState('');
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<Product | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [searched, setSearched] = useState('');

  async function request(path: string) {
    setLoading(true); setError('');
    const start = performance.now();
    try {
      const res = await fetch(path, { cache: 'no-store' });
      const body = await res.json();
      setMeasurement({ ms: performance.now() - start, id: res.headers.get('X-Request-ID') || 'unavailable', status: res.status, version: res.headers.get('X-Config-Version') || 'unavailable' });
      if (!res.ok) throw new Error(body.detail || 'Request failed');
      return body;
    } catch (e) { setError(e instanceof Error ? e.message : 'Request failed'); return null; }
    finally { setLoading(false); }
  }
  async function search(value: string) {
    setSelected(null); setSearched(value.trim());
    const data = await request(`/api/catalog?q=${encodeURIComponent(value.trim())}`);
    if (data) setProducts(data.products);
  }
  async function openProduct(id: string) {
    const data = await request(`/api/products/${encodeURIComponent(id)}`);
    if (data) setSelected(data.product);
  }
  useEffect(() => { void search(''); }, []);
  return <><header><div className="nav"><a className="brand" href="/">demo<span>shop</span><b>.</b></a><span className="nav-note">Thoughtful goods for everyday life</span></div></header>
    <main><section className="hero"><div><p className="eyebrow">THE EVERYDAY COLLECTION</p><h1>Good things for<br/><em>wherever you’re going.</em></h1><p>Useful, considered essentials made for the little adventures in your day.</p></div><div className="hero-art">✳</div></section>
    <section className="catalog"><div className="section-heading"><div><p className="eyebrow">FIND YOUR EVERYDAY</p><h2>Explore the collection</h2></div><span className="count">{products.length} items</span></div>
      <form onSubmit={e => { e.preventDefault(); void search(query); }}><label className="search"><span>⌕</span><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search for something..." aria-label="Search products"/><button disabled={loading}>Search</button></label></form>
      {measurement && <p className="measurement">Last request: {Math.round(measurement.ms)} ms · HTTP {measurement.status} · config v{measurement.version} · ID {measurement.id}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {loading ? <div className="loading" role="status"><span className="spinner"/> Loading products…</div> : selected ? <article className="detail"><button className="back" onClick={() => setSelected(null)}>← Back to results</button><div className="detail-body"><div className="detail-art">{selected.icon}</div><div><p className="eyebrow">{selected.category}</p><h2>{selected.name}</h2><p>{selected.description}</p><strong>${selected.price.toFixed(2)}</strong></div></div></article> : <><p className="results">{searched ? `Results for “${searched}”` : 'All products'}</p><div className="grid">{products.map(p => <button className="card" key={p.id} onClick={() => void openProduct(p.id)}><div className="card-art">{p.icon}</div><div className="card-info"><span>{p.category}</span><h3>{p.name}</h3><p>{p.description}</p><strong>${p.price.toFixed(2)}</strong></div></button>)}</div>{!products.length && <p>No products found. Try another search.</p>}</>}
    </section></main><footer>DemoShop <span>·</span> A little better, every day.</footer></>;
}

type State = { config: { version: number; generation: number; delay_ms: number }; audit: { id: string; action: string; version: number; generation: number; created_at: string }[] };
function Presenter() {
  const [token, setToken] = useState(''); const [state, setState] = useState<State | null>(null); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false);
  async function call(path: string, method = 'GET') {
    setBusy(true); setMessage('');
    try { const r = await fetch(`/presenter/api/${path}`, { method, headers: { 'X-Presenter-Token': token }, cache: 'no-store' }); const body = await r.json(); if (!r.ok) throw new Error(body.detail); return body; }
    catch (e) { setMessage(e instanceof Error ? e.message : 'Request failed'); return null; } finally { setBusy(false); }
  }
  async function refresh() { const s = await call('state'); if (s) setState(s); }
  async function action(name: string) { const result = await call(name, 'POST'); if (result) { await refresh(); setMessage(`${result.action} recorded. Receipt ${result.receipt}`); } }
  return <main className="presenter"><p className="eyebrow">LOCAL PRESENTER CONTROLS</p><h1>Demo environment</h1><p>These controls simulate a slow catalog dependency. Emergency reset is a manual teardown action, not agent recovery.</p><label>Presenter token<input type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" /></label><button disabled={busy || !token} onClick={() => void refresh()}>Connect / refresh</button>{state && <><div className="panel"><h2>Catalog configuration</h2><p>Version {state.config.version} · fault generation {state.config.generation}</p><p>{state.config.delay_ms ? `Latency fault active: ${state.config.delay_ms} ms server-side delay` : 'Normal: no injected delay'}</p><div className="actions"><button disabled={busy} onClick={() => void action('inject')}>Inject latency</button><button disabled={busy} className="secondary" onClick={() => void action('emergency-reset')}>Emergency reset</button></div></div><h2>Control audit</h2>{state.audit.length ? <ul>{state.audit.map(a => <li key={a.id}>{a.created_at} UTC · {a.action} · v{a.version} / generation {a.generation}</li>)}</ul> : <p>No control actions yet.</p>}</>}{message && <p role="status">{message}</p>}<p><a href="/" target="_blank" rel="noreferrer">Open DemoShop ↗</a></p></main>;
}

type ProbeSample = { id: string; request_id: string | null; started_at: number; elapsed_ms: number; status: number | null; valid: number; error: string | null; config_version: number | null; fault_generation: number | null };
type Alert = { id: string; fault_generation: number; created_at: number; status: string; sample_ids: string };
type Proposal = { action: string; target: string; expected_generation: number; expected_config_version: number; restore_version: number; restore_config_digest: string; expires_at: number; evidence_ids: string[]; baseline_evidence_ids: string[] };
type WindowSummary = { count: number; correct_count: number; errors: number; median_ms: number | null; min_ms: number | null; max_ms: number | null };
type Incident = { agentcore_analysis: { provider: string; status?: string; count?: number; median_ms?: number; min_ms?: number; max_ms?: number } | null; temporal_url: string | null; windows: Record<string, WindowSummary>; id: string; alert_id: string; phase: string; proposal: Proposal | null; proposal_hash: string | null; reason: string | null; action_id: string | null; applied_version: number | null; verification_ids: string[] };
type MonitorData = { cloudwatch_enabled: boolean; diagnosis_mode: string; probe_running: boolean; telemetry: string; samples: ProbeSample[]; alerts: Alert[]; incidents: Incident[]; config: { version: number; generation: number } };
function MissionControl() {
  const [token, setToken] = useState(''); const [connected, setConnected] = useState(false); const [data, setData] = useState<MonitorData | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!connected) return;
    let active = true;
    async function refresh() {
      try {
        const response = await fetch('/presenter/api/monitor', { headers: { 'X-Presenter-Token': token }, cache: 'no-store' });
        if (!response.ok) throw new Error(response.status === 403 ? 'Presenter authorization required' : 'Could not load measurements');
        const next = await response.json(); if (active) { setData(next); setError(''); }
      } catch (e) { if (active) { setData(null); setError(e instanceof Error ? e.message : 'Could not load measurements'); } }
    }
    void refresh(); const interval = window.setInterval(refresh, 3000);
    return () => { active = false; window.clearInterval(interval); };
  }, [connected, token]);
  async function command(path: string, body?: object) {
    setBusy(true); setError('');
    try {
      const response = await fetch(`/presenter/api/${path}`, { method: 'POST', headers: { 'X-Presenter-Token': token, ...(body ? { 'Content-Type': 'application/json' } : {}) }, body: body ? JSON.stringify(body) : undefined });
      const result = await response.json(); if (!response.ok) throw new Error(result.detail || 'Action failed');
      const updated = await fetch('/presenter/api/monitor', { headers: { 'X-Presenter-Token': token }, cache: 'no-store' });
      if (updated.ok) setData(await updated.json());
    } catch (e) { setError(e instanceof Error ? e.message : 'Action failed'); } finally { setBusy(false); }
  }
  return <main className="mission"><div className="mission-top"><div><p className="eyebrow">LOCAL DEMO · MANUAL INVESTIGATION</p><h1>Mission Control</h1><p>Measured catalog requests and alerts</p></div><a href="/" target="_blank" rel="noreferrer">Open DemoShop ↗</a></div>
    {!connected ? <div className="panel"><label>Presenter token<input type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" /></label><button disabled={!token} onClick={() => setConnected(true)}>View monitoring</button></div> : <button className="secondary" onClick={() => { setConnected(false); setData(null); setToken(''); }}>Disconnect</button>}
    {error && <p role="alert" className="error">{error}</p>}
    {data && <><div className="monitor-grid"><div className="stat"><span>PROBE</span><strong>{data.probe_running ? 'Running' : 'Stopped'}</strong></div><div className="stat"><span>TELEMETRY</span><strong className={data.telemetry === 'stale' ? 'warn' : ''}>{data.telemetry === 'stale' ? 'Stale' : 'Receiving'}</strong></div><div className="stat"><span>CURRENT CONFIGURATION</span><strong>v{data.config.version} · generation {data.config.generation}</strong></div></div>
    <div className="monitor-section"><h2>Alerts</h2>{data.cloudwatch_enabled && <p><a href="https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#alarmsV2:" target="_blank" rel="noopener noreferrer">View CloudWatch alarms ↗</a> · CloudWatch evaluates the same measured probe latency separately.</p>}<p>An alert opens when at least 3 of the last 5 observations are valid requests over 2,000 ms within 60 seconds. No investigation starts automatically.</p>{data.alerts.length === 0 ? <p className="muted">No measured latency alerts yet.</p> : data.alerts.map(a => <article className="alert-card" key={a.id}><div><span className="badge">{a.status}</span> <span className="muted">{new Date(a.created_at * 1000).toLocaleString()}</span></div><h3>Catalog search latency</h3><p>GET /api/catalog?q=backpack · fault generation {a.fault_generation}</p><p className="muted">Alert {a.id} · Evidence: {JSON.parse(a.sample_ids).join(', ')}</p>{!data.incidents.some(i => i.alert_id === a.id) && <button disabled={busy || !data.probe_running || data.telemetry !== 'receiving' || a.fault_generation !== data.config.generation} onClick={() => void command(`alerts/${a.id}/investigate`)}>Investigate with SRE</button>}<p className="muted">{data.diagnosis_mode}. Evidence gathering and restore run with the application; no AWS runbook is connected.</p></article>)}</div>
    <div className="monitor-section"><h2>Investigations</h2>{!data.incidents.length && <p className="muted">No investigations started.</p>}{data.incidents.map(i => <article className="alert-card" key={i.id}><span className="badge">{i.phase.replace(/_/g, ' ')}</span><p>Incident {i.id}</p>{i.temporal_url && <p><a href={i.temporal_url} target="_blank" rel="noopener noreferrer">Open workflow in Temporal Cloud ↗</a></p>}{i.reason && <p role="status">{i.reason}</p>}{i.agentcore_analysis && <p>{i.agentcore_analysis.status === "unavailable" ? "AgentCore analysis unavailable; continuing with local evidence." : `AgentCore Code Interpreter analyzed ${i.agentcore_analysis.count} measured requests: median ${Math.round(i.agentcore_analysis.median_ms ?? 0)} ms (${Math.round(i.agentcore_analysis.min_ms ?? 0)}–${Math.round(i.agentcore_analysis.max_ms ?? 0)} ms).`}</p>}{i.proposal && <><h3>Proposed configuration restore</h3><p>Measured slow catalog requests coincide with configuration v{i.proposal.expected_config_version}, generation {i.proposal.expected_generation}. Restore the previously probe-verified settings from v{i.proposal.restore_version} (digest {i.proposal.restore_config_digest}).</p><p className="muted">Baseline sample IDs: {i.proposal.baseline_evidence_ids.join(', ')}<br/>Triggering window sample IDs: {i.proposal.evidence_ids.join(', ')}<br/>Proposal hash: {i.proposal_hash}<br/>Expires: {new Date(i.proposal.expires_at * 1000).toLocaleString()}</p>{i.phase === 'WAITING_APPROVAL' && <><p>Approval authorizes this single local restore. After approval, it cannot be cancelled.</p><div className="actions"><button disabled={busy} onClick={() => void command(`incidents/${i.id}/decision`, { decision: 'APPROVE', proposal_hash: i.proposal_hash, request_id: crypto.randomUUID() })}>Approve restore</button><button className="secondary" disabled={busy} onClick={() => void command(`incidents/${i.id}/decision`, { decision: 'REJECT', proposal_hash: i.proposal_hash, request_id: crypto.randomUUID() })}>Reject</button></div></>}{i.action_id && <p>Action receipt {i.action_id} · Applied config v{i.applied_version}</p>}{i.phase === 'VERIFYING' && <p>Waiting for five correct, fast post-action probe requests.</p>}{i.verification_ids.length > 0 && <p>Verified with five new correct, fast probe requests: {i.verification_ids.join(', ')}</p>}{Object.keys(i.windows).length > 0 && <><h3>Probe evidence windows</h3><p>HTTP probe timings only. The triggering window may contain baseline and slow requests.</p><div className="table-wrap"><table><thead><tr><th>Window</th><th>Samples</th><th>Correct</th><th>Errors</th><th>Median</th><th>Range</th></tr></thead><tbody>{Object.entries(i.windows).map(([label,w]) => <tr key={label}><td>{label}</td><td>{w.count}</td><td>{w.correct_count}</td><td>{w.errors}</td><td>{w.median_ms == null ? '—' : `${Math.round(w.median_ms)} ms`}</td><td>{w.min_ms == null || w.max_ms == null ? '—' : `${Math.round(w.min_ms)}–${Math.round(w.max_ms)} ms`}</td></tr>)}</tbody></table></div></>}</>}</article>)}</div>
    <div className="monitor-section"><h2>Recent probe measurements</h2><p>Independent HTTP elapsed time; failures are retained. Browser and server timings have different scopes.</p><div className="table-wrap"><table><thead><tr><th>Started</th><th>Elapsed</th><th>Result</th><th>Config / generation</th><th>Sample ID</th><th>Request ID</th></tr></thead><tbody>{data.samples.map(s => <tr key={s.id}><td>{new Date(s.started_at * 1000).toLocaleTimeString()}</td><td>{Math.round(s.elapsed_ms)} ms</td><td>{s.valid ? `HTTP ${s.status} · correct` : `${s.status ? `HTTP ${s.status} · ` : ''}${s.error || 'invalid'}`}</td><td>{s.config_version ?? '—'} / {s.fault_generation ?? '—'}</td><td className="mono">{s.id}</td><td className="mono">{s.request_id || '—'}</td></tr>)}</tbody></table></div>{!data.samples.length && <p className="muted">No probe measurements yet. Start the probe from the terminal.</p>}</div></>}
  </main>;
}

createRoot(document.getElementById('root')!).render(location.pathname === '/presenter' ? <Presenter /> : location.pathname === '/mission-control' ? <MissionControl /> : <Shop />);
