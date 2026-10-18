import { useEffect, useState } from 'react';
import { ArrowLeft, Check, Clock3, Gauge, LoaderCircle, RefreshCw, Search } from 'lucide-react';

type Summary = { requests: number; completed: number; failed: number; interrupted: number; running: number; avg_ttft_ms: number | null; max_ttft_ms: number | null; avg_total_ms: number | null; max_total_ms: number | null };
type QuestionRow = Summary & { question_key: string; question: string; last_asked: string };
type RequestRow = { id: string; question: string; created: string; model: string; transport: string; status: string; answerable: number | null; ttft_ms: number | null; total_ms: number | null; error: string | null };
type Report = { view: 'questions' | 'requests'; summary: Summary; rows: (QuestionRow | RequestRow)[]; total: number; limit: number; offset: number; recording_since: string | null; generated_at: string; timing_definition: string };
function duration(ms: number | null | undefined) {
  if (ms == null) return '\u2014';
  return `${(ms / 1000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} s`;
}
function date(value: string) { return new Date(value).toLocaleString(); }

export default function AdminPage({ onBack }: { onBack: () => void }) {
  const [view, setView] = useState<'questions' | 'requests'>('questions');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [data, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    let inFlight = false;
    const controller = new AbortController();
    async function load() {
      if (inFlight) return;
      inFlight = true;
      setLoading(true);
      try {
        const params = new URLSearchParams({ view, q: query, offset: String(offset), limit: '25' });
        const response = await fetch(`/api/admin/metrics?${params}`, { signal: controller.signal });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(response.status === 404 ? 'Restart the backend to enable the admin metrics endpoint.' : body.detail || 'Could not load performance metrics.');
        }
        const data = await response.json();
        if (alive) { setReport(data); setError(''); }
      } catch (e) { if (alive) setError((e as Error).message); }
      finally { inFlight = false; if (alive) setLoading(false); }
    }
    setReport(null);
    const debounce = setTimeout(() => void load(), 250);
    const interval = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 10000);
    return () => { alive = false; clearTimeout(debounce); clearInterval(interval); controller.abort(); };
  }, [view, query, offset, refresh]);
  const report = data?.view === view ? data : null;
  const stats = report?.summary;
  const cards = [
    { title: 'Average first answer', key: 'avg_ttft_ms' as const, hint: 'TTFT · verified answer content' },
    { title: 'Maximum first answer', key: 'max_ttft_ms' as const, hint: 'Slowest first answer' },
    { title: 'Average total response', key: 'avg_total_ms' as const, hint: 'Full backend response time' },
    { title: 'Maximum total response', key: 'max_total_ms' as const, hint: 'Slowest completed response' },
  ];
  return <div className="admin-page">
    <header className="admin-header"><button className="admin-brand" onClick={onBack}><img src="/paperatlas-crest.png" alt="Paper Atlas heraldic crest"/><span>paperatlas <small>ADMIN</small></span></button><button className="admin-back" onClick={onBack}><ArrowLeft size={15}/> Back to chat</button></header>
    <main className="admin-main">
      <div className="admin-title-row"><div><div className="eyebrow"><Gauge size={14}/> LOCAL WORKSPACE ANALYTICS</div><h1>Response performance</h1><p>Time to first verified answer and total response time, for every question.</p></div><button className="admin-refresh" onClick={() => setRefresh(n => n + 1)} disabled={loading}>{loading ? <LoaderCircle size={15} className="spin"/> : <RefreshCw size={15}/>} Refresh</button></div>
      {error && <div className="banner error" role="alert">{error}</div>}
      <div className="admin-stat-grid">{cards.map(card => <section className="admin-stat" key={card.key}><span>{card.title}</span><strong>{duration(stats?.[card.key])}</strong><small>{card.hint}</small></section>)}</div>
      <div className="admin-counts" aria-live="polite"><span><Clock3 size={13}/>{stats?.requests ?? 0} recorded requests</span><span><Check size={13}/>{stats?.completed ?? 0} completed</span><span>{stats?.running ?? 0} running</span><span>{stats?.failed ?? 0} failed</span><span>{stats?.interrupted ?? 0} interrupted</span></div>
      <div className="admin-method"><strong>What the timings mean</strong><p>{report?.timing_definition || 'TTFT measures the first verified answer content sent by the backend, not progress updates or an internal model token. Answers are sent as one result after evidence checks, so TTFT and total response time can be similar. Timings exclude network latency and browser rendering. Averages and maximums include completed requests only.'}</p><p>Records start with this feature; earlier questions have no timing data. Repeated questions are grouped ignoring letter case and extra whitespace.</p></div>
      <section className="admin-records">
        <div className="admin-toolbar"><div className="admin-tabs" role="tablist" aria-label="Performance view"><button role="tab" aria-selected={view === 'questions'} onClick={() => { setView('questions'); setOffset(0); }}>By question</button><button role="tab" aria-selected={view === 'requests'} onClick={() => { setView('requests'); setOffset(0); }}>Request history</button></div><label className="admin-search"><Search size={15}/><input aria-label="Search recorded questions" placeholder="Search questions" value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }}/></label></div>
        {loading && !report ? <div className="admin-empty" role="status"><LoaderCircle size={18} className="spin"/> Loading performance records...</div> : report && !report.rows.length ? <div className="admin-empty"><Gauge size={28}/><strong>{query ? 'No matching questions' : 'No recorded questions yet'}</strong><p>{query ? 'Try another search.' : 'Ask a new question in chat. Its timings will appear here automatically.'}</p></div> : report && <div className="admin-table-wrap"><table className="admin-table"><caption className="sr-only">{view === 'questions' ? 'Average and maximum response timings by question' : 'Individual question request timings'}</caption><thead><tr><th>Question</th>{view === 'questions' ? <><th>Runs</th><th>Avg TTFT</th><th>Max TTFT</th><th>Avg total</th><th>Max total</th><th>Last asked</th></> : <><th>Status</th><th>TTFT</th><th>Total</th><th>Model</th><th>Asked</th></>}</tr></thead><tbody>{report.rows.map(row => view === 'questions' ? (() => {
          const r = row as QuestionRow;
          return <tr key={r.question_key}><td className="admin-question">{r.question}</td><td><strong>{r.requests}</strong><small>{r.completed} completed{r.failed ? ` · ${r.failed} failed` : ''}{r.interrupted ? ` · ${r.interrupted} interrupted` : ''}{r.running ? ` · ${r.running} running` : ''}</small></td><td>{duration(r.avg_ttft_ms)}</td><td>{duration(r.max_ttft_ms)}</td><td>{duration(r.avg_total_ms)}</td><td>{duration(r.max_total_ms)}</td><td className="admin-date">{date(r.last_asked)}</td></tr>;
        })() : (() => {
          const r = row as RequestRow;
          return <tr key={r.id}><td className="admin-question">{r.question}<small title={r.id}>Request {r.id.slice(0, 8)} · {r.transport.toUpperCase()}</small>{r.error && <small className="admin-request-error">{r.error}</small>}</td><td><span className={`admin-status ${r.status}`}>{r.status}</span>{r.status === 'completed' && r.answerable === 0 && <small>Insufficient evidence</small>}</td><td>{duration(r.ttft_ms)}</td><td>{duration(r.total_ms)}</td><td>{r.model}</td><td className="admin-date">{date(r.created)}</td></tr>;
        })())}</tbody></table></div>}
        {report && <div className="admin-pagination"><span>{report.total ? `${offset + 1}–${Math.min(offset + report.limit, report.total)} of ${report.total}` : '0 records'}</span><button onClick={() => setOffset(Math.max(0, offset - 25))} disabled={!offset || loading}>Previous</button><button onClick={() => setOffset(offset + 25)} disabled={offset + 25 >= report.total || loading}>Next</button></div>}
      </section>
      <footer className="admin-footer"><span>{report?.recording_since ? `Recording since ${date(report.recording_since)}` : 'Timings are stored locally in SQLite.'}</span><span>{report ? `Updated ${date(report.generated_at)} · auto-refresh every 10 s` : 'Auto-refresh every 10 s'}</span></footer>
    </main>
  </div>;
}
