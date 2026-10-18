import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import AdminPage from './AdminPage';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { ArrowUp, BookOpen, Check, ChevronRight, Copy, FileText, Gauge, LoaderCircle, Plus, RefreshCw, Search, Sparkles, Upload, X } from 'lucide-react';

type Doc = { id: string; name: string; pages: number; status: 'active' | 'pending' };
type Source = { source_id: string; document_id: string; name: string; page: number; excerpt: string };
type Result = { answer: string; answerable: boolean; sources: Source[]; version: string; task: string };
type Message = { role: 'user' | 'assistant'; content: string; result?: Result };
function CopyMessage({ message }: { message: Message }) {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  async function copy() {
    if (timer.current) clearTimeout(timer.current);
    const references = message.result?.sources || [];
    const text = message.content + (references.length ? '\n\nSources:\n' + references.map(source =>
      `[${source.source_id}] ${source.name}, PDF page ${source.page}`).join('\n') : '');
    try {
      await navigator.clipboard.writeText(text);
      setCopyState('copied');
      timer.current = setTimeout(() => setCopyState('idle'), 2000);
    } catch {
      setCopyState('error');
    }
  }
  const label = message.role === 'user' ? 'Copy question' : 'Copy response';
  return <div className="message-actions">
    <button className="copy-message" type="button" aria-label={label} title={label} onClick={() => void copy()}>
      {copyState === 'copied' ? <Check size={13}/> : <Copy size={13}/>}
      <span role="status" aria-live="polite">{copyState === 'copied' ? 'Copied' : label}</span>
    </button>
    {copyState === 'error' && <span className="copy-error" role="alert">Could not copy. Select the text and copy it manually.</span>}
  </div>;
}

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `Request failed (${res.status})`); }
  return res.json();
}
const prompts = [
  { title: 'Understand a concept', text: 'Explain scaled dot-product attention and its equation in Attention Is All You Need.', tag: 'EXPLAIN' },
  { title: 'Compare approaches', text: 'Compare BERT and generative pre-training: objectives, architecture, and downstream adaptation.', tag: 'COMPARE' },
  { title: 'Read the results', text: 'What do the LoRA paper\'s results tables show about parameter efficiency and model quality?', tag: 'ANALYZE' },
  { title: 'See the bigger picture', text: 'Summarize The Illusion of Thinking, including its methods, findings, and limitations.', tag: 'SUMMARIZE' },
];
function ChatPage({ onOpenAdmin }: { onOpenAdmin: () => void }) {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [version, setVersion] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [job, setJob] = useState<string | null>(() => localStorage.getItem('paper-atlas-job'));
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [source, setSource] = useState<Source | null>(null);
  const [health, setHealth] = useState<{ api_key_configured: boolean; model: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  async function refresh() {
    const data = await api('/documents'); setDocs(data.documents); setVersion(data.active_version?.id || null);
    setSelected(prev => prev.filter(id => data.documents.some((d: Doc) => d.id === id && d.status === 'active')));
  }
  useEffect(() => { Promise.all([refresh(), api('/health').then(setHealth)]).catch(e => setError(e.message)); }, []);
  useEffect(() => { if (messages.length || busy) bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, status, busy]);
  useEffect(() => {
    if (!job) return;
    let alive = true;
    const poll = async () => {
      try {
        const data = await api(`/jobs/${job}`); if (!alive) return;
        setStatus(data.message);
        if (['succeeded', 'failed'].includes(data.status)) {
          setJob(null); localStorage.removeItem('paper-atlas-job');
          if (data.status === 'failed') setError(data.message);
          else { setNotice('Knowledge base updated. New questions use the new index.'); await refresh(); }
          setStatus('');
        }
      } catch (e) { if (alive) { setError((e as Error).message); setJob(null); localStorage.removeItem('paper-atlas-job'); } }
    };
    void poll(); const timer = setInterval(poll, 1500); return () => { alive = false; clearInterval(timer); };
  }, [job]);
  async function reindex() {
    setError('');
    try { const data = await api('/reindex', { method: 'POST' }); setJob(data.job_id); localStorage.setItem('paper-atlas-job', data.job_id); }
    catch (e) { setError((e as Error).message); }
  }
  async function upload(files: FileList | null) {
    if (!files) return; setUploading(true); setError('');
    try { for (const file of Array.from(files)) { const form = new FormData(); form.append('file', file); await api('/upload', { method: 'POST', body: form }); }
      await refresh(); setNotice('Files saved as pending. Reindex to include them in answers.');
    } catch (e) { setError((e as Error).message); } finally { setUploading(false); if (fileInput.current) fileInput.current.value = ''; }
  }
  async function ask(text = question) {
    if (!text.trim() || busy || !version) return;
    const history = messages.slice(-20).map(m => ({ role: m.role, content: m.content }));
    setMessages(prev => [...prev, { role: 'user', content: text }]); setQuestion(''); setBusy(true); setError(''); setStatus('Finding evidence');
    try {
      const response = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: text, document_ids: selected, history }) });
      if (!response.ok) { const e = await response.json(); throw new Error(e.detail || 'Request failed'); }
      const reader = response.body!.getReader(); const decoder = new TextDecoder(); let buffer = ''; let received = false;
      while (true) {
        const { value, done } = await reader.read(); buffer += decoder.decode(value, { stream: !done });
        let end;
        while ((end = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, end); buffer = buffer.slice(end + 2);
          const event = block.split('\n').find(l => l.startsWith('event: '))?.slice(7);
          const raw = block.split('\n').find(l => l.startsWith('data: '))?.slice(6); if (!raw) continue;
          const data = JSON.parse(raw);
          if (event === 'progress') setStatus(data.message);
          if (event === 'error') throw new Error(data.message);
          if (event === 'result') { received = true; setMessages(prev => [...prev, { role: 'assistant', content: data.answer, result: data }]); }
        }
        if (done) break;
      }
      if (!received) throw new Error('Connection ended before an answer arrived. Please retry.');
    } catch (e) { setError((e as Error).message); setQuestion(text); }
    finally { setBusy(false); if (!job) setStatus(''); }
  }
  const active = docs.filter(d => d.status === 'active');
  const pending = docs.length - active.length;
  return <div className={`app ${source ? 'has-source' : ''}`}>
    <aside className="library">
      <a className="brand" href="/" aria-label="Paper Atlas home"><span className="brand-icon"><img src="/paperatlas-crest.png" alt="Paper Atlas heraldic crest" /></span><span>paper<span className="brand-light">atlas</span><small>YOUR RESEARCH, CONNECTED</small></span></a>
      <button className="new-chat" disabled={busy} onClick={() => { setMessages([]); setSource(null); setError(''); }}><Plus size={16}/> New conversation</button>
      <div className="section-label">KNOWLEDGE LIBRARY <span>{docs.length.toString().padStart(2, '0')}</span></div>
      <label className="search"><Search size={15}/><input aria-label="Find a paper" placeholder="Find a paper" value={filter} onChange={e => setFilter(e.target.value)}/></label>
      <button className={`all-papers ${!selected.length ? 'chosen' : ''}`} onClick={() => setSelected([])}><BookOpen size={17}/><span>All active papers</span>{!selected.length && <Check size={15}/>}</button>
      <div className="document-list">{docs.filter(d => d.name.toLowerCase().includes(filter.toLowerCase())).map((d, i) => <button key={d.id} className={`document ${selected.includes(d.id) ? 'selected' : ''}`} disabled={d.status === 'pending'} title={d.name} onClick={() => setSelected(prev => prev.includes(d.id) ? prev.filter(x => x !== d.id) : [...prev, d.id])}>
        <span className="doc-number">{(i + 1).toString().padStart(2, '0')}</span><span className="doc-text">{d.name.replace(/\.pdf$/i, '')}<small>{d.pages} pages <span className={d.status}>{d.status === 'active' ? 'Indexed' : 'Pending index'}</span></small></span>{selected.includes(d.id) && <Check size={14}/>}</button>)}</div>
      <div className="library-actions"><input ref={fileInput} type="file" accept="application/pdf,.pdf" multiple hidden onChange={e => void upload(e.target.files)}/>
        <button className="upload" disabled={uploading} onClick={() => fileInput.current?.click()}><Upload size={15}/>{uploading ? 'Saving PDFs...' : 'Upload papers'}</button>
        <button className="reindex" disabled={!!job || busy || uploading} onClick={() => void reindex()}>{job ? <LoaderCircle size={15} className="spin"/> : <RefreshCw size={15}/>} {job ? 'Indexing...' : 'Reindex library'}{pending > 0 && <span>{pending}</span>}</button>
        <p>Uploads enter the knowledge base after reindexing.</p>
      </div>
      <button type="button" className="admin-navigation" onClick={onOpenAdmin}><Gauge size={15}/> Admin performance</button>
      <div className="local-status"><span className="dot"/> Local workspace <span>PDF-grounded</span></div>
    </aside>
    <main>
      <header><div><span className="breadcrumb">Workspace</span><ChevronRight size={13}/><strong>Research assistant</strong></div><span className="grounded"><span className="dot"/> Evidence first</span></header>
      <div className="conversation">
        {error && <div className="banner error" role="alert">{error}<button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        {notice && <div className="banner" role="status">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={16}/></button></div>}
        {health && !health.api_key_configured && <div className="banner setup">Add your OpenAI API key to <code>backend/.env</code> and restart the backend to index and chat.</div>}
        {!messages.length ? <section className="welcome"><div className="eyebrow"><span/> FROM PAPERS TO PERSPECTIVE</div><h1>A clearer view of<br/>your research.</h1><p>Explore ideas, unpack equations, and connect findings.<br/>Every answer starts with your papers.</p>
          <div className="scope-pill"><FileText size={14}/>{version ? `${active.length} papers in your knowledge base` : `${docs.length} papers ready to index`}<span>·</span> Sources included</div>
          {!version && <div className="first-index"><strong>Your library is ready for its first index.</strong><p>Choose Reindex library to prepare text, tables, and source pages.</p></div>}
          <div className="prompt-grid">{prompts.map(p => <button key={p.tag} disabled={!version || busy} onClick={() => void ask(p.text)}><span>{p.tag}<ChevronRight size={14}/></span><strong>{p.title}</strong><p>{p.text}</p></button>)}</div>
          <div className="evidence-note"><Sparkles size={15}/> Grounded in your PDFs. Clear when the evidence is missing.</div>
        </section> : <div className="messages">{messages.map((m, i) => <article key={i} className={`message ${m.role}`}><div className="message-label">{m.role === 'user' ? 'YOU' : <><span className="mini-brand"><img src="/paperatlas-crest.png" alt="Paper Atlas heraldic crest" /></span> PAPER ATLAS</>}{m.result && <small>{m.result.answerable ? 'Source-checked' : 'Insufficient evidence'}</small>}</div><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{m.content}</ReactMarkdown></div><CopyMessage message={m}/>{m.result && m.result.sources.length > 0 && <div className="citations">{m.result.sources.map(s => <button key={s.source_id} onClick={() => setSource(s)}><FileText size={13}/><b>{s.source_id}</b> {s.name.replace(/\.pdf$/i, '')}<span>p. {s.page}</span></button>)}</div>}{m.result && <div className="answer-meta">{m.result.task} · index {m.result.version.slice(0, 8)}</div>}</article>)}</div>}
        {busy && <div className="thinking" role="status"><LoaderCircle size={16} className="spin"/>{status}</div>}
        {job && <div className="index-progress" role="status"><LoaderCircle size={15} className="spin"/>{status || 'Preparing index...'}</div>}
        <div ref={bottom}/>
      </div>
      <div className="composer-wrap"><div className="scope-line"><BookOpen size={13}/>{selected.length ? `${selected.length} selected papers` : 'All active papers'}<span>{health?.model || 'OpenAI'} · PDF evidence only</span></div><form className="composer" onSubmit={e => { e.preventDefault(); void ask(); }}><textarea aria-label="Ask about your research papers" placeholder={version ? 'Ask a question about your papers...' : 'Index your library to start exploring...'} value={question} disabled={busy} rows={2} onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void ask(); } }}/><button aria-label="Send question" disabled={busy || !version || !question.trim()}>{busy ? <LoaderCircle size={18} className="spin"/> : <ArrowUp size={20}/>}</button></form><p className="composer-note">Verify important details in the cited pages. Tables and equations are read with page images.</p></div>
    </main>
    {source && <aside className="source-panel"><div className="source-heading"><span><FileText size={15}/> SOURCE EVIDENCE</span><button aria-label="Close source" onClick={() => setSource(null)}><X size={18}/></button></div><h2>{source.name.replace(/\.pdf$/i, '')}</h2><p className="source-page">{source.source_id} · PDF page {source.page}</p><details><summary>Extracted passage</summary><p className="excerpt">{source.excerpt}</p></details><a href={`/api/documents/${source.document_id}/pdf#page=${source.page}`} target="_blank" rel="noreferrer">Open PDF in a new tab ↗</a><div className="page-preview"><a href={`/api/documents/${source.document_id}/pages/${source.page}.png`} target="_blank" rel="noreferrer" aria-label="Open source page at full resolution"><img key={`${source.document_id}:${source.page}`} alt={`${source.name}, PDF page ${source.page}`} src={`/api/documents/${source.document_id}/pages/${source.page}.png`}/></a></div></aside>}
  </div>;
}

export default function App() {
  const [admin, setAdmin] = useState(() => window.location.pathname.replace(/\/$/, '') === '/admin');
  useEffect(() => {
    const update = () => setAdmin(window.location.pathname.replace(/\/$/, '') === '/admin');
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);
  useEffect(() => { document.title = admin ? 'Paper Atlas | Admin performance' : 'Paper Atlas | Research with evidence'; }, [admin]);
  function navigate(toAdmin: boolean) {
    window.history.pushState({}, '', toAdmin ? '/admin' : '/');
    setAdmin(toAdmin);
  }
  return <><div hidden={admin}><ChatPage onOpenAdmin={() => navigate(true)}/></div>{admin && <AdminPage onBack={() => navigate(false)}/>}</>;
}
