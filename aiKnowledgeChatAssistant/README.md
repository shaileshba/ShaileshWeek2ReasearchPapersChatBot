# Paper Atlas

Local research assistant for the ten PDFs in `../RAG data`. React + FastAPI, LangChain hybrid retrieval, LangGraph orchestration, OpenAI text/image interpretation, Chroma and SQLite. PDF content is data, never application instructions.

## Start on Windows

Backend (PowerShell):

```powershell
cd aiKnowledgeChatAssistant/backend
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
Copy-Item .env.example .env
# Set OPENAI_API_KEY in .env. Never put this key in the frontend.
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend, in another terminal:

```powershell
cd aiKnowledgeChatAssistant/frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. Click **Reindex library** once, wait for success, then ask questions. Uploads remain pending until a successful explicit reindex. During indexing, existing answers continue using the old active index. Files uploaded after indexing starts wait for the next index. Run only one backend worker (the indexing lock is process-local).

## Architecture

- `backend/app/store.py`: SQLite metadata and immutable PDF snapshots, initial ten-file allowlist, active-version pointer.
- `backend/app/indexing.py`: page text and tables with PyMuPDF, overlapping LangChain chunks, OpenAI embeddings, Chroma + BM25 reciprocal-rank fusion. Scanned/sparse pages receive visual transcription during indexing.
- `backend/app/workflow.py`: LangGraph plan -> retrieve -> visually read -> answer -> conditional verification or abstention, with one bounded revision if verification rejects a draft. Evidence notes are scoped to their page batches so missing content elsewhere does not invalidate a cited finding. Visual reading uses all retrieved pages, in batches of five. Whole-paper summaries inspect every page of the selected paper(s). Comparisons reserve retrieval candidates per paper.
- `backend/app/main.py`: uploads, reindex jobs, document access, chat/SSE and token usage. Chat requests snapshot the active version. History resolves follow-ups but is never factual evidence.
- `frontend/src/App.tsx`: paper scope, staged uploads, indexing progress, streamed stages, Markdown/LaTeX, citation buttons and source-page viewer and original PDF links.

Answers are withheld until citation and model evidence checks pass. No web search tools are provided. The app abstains on missing evidence. This reduces unsupported answers; it is not a guarantee that model interpretation is flawless. Check cited source pages, especially for dense equations or small tables. Standard PDF page numbers are one-based and can differ from printed page labels.

## Configuration

See `backend/.env.example`. Defaults: `gpt-5.4`, `text-embedding-3-large`. Changing the embedding model requires reindexing; existing versions retain their original embedding model. Extraction text, embeddings, and relevant page images are sent to OpenAI. API key stays server-side. Responses use `store=False`; provider account data policies still apply. Do not enable LangSmith tracing without reviewing PDF disclosure requirements.

This is a localhost assignment app without authentication. Bind to loopback only. PDF uploads are limited to 50 MB each. Old immutable indexes are retained; storage cleanup is intentionally manual. Pending documents have no PDF viewer endpoint. Original filenames can repeat when different contents are uploaded; identities use content hashes.

## Validation

```powershell
cd backend
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m evals.run
cd ../frontend
npm run build
```

Offline tests cover pending/active separation, failed-index rollback, upload snapshots, initial allowlist, citation validation, unsupported-claim rejection, and summary coverage. Evals require a configured key and an active index. See `backend/evals/README.md` for scope and limitations. Model-backed results must be reviewed; automated grading is advisory.

`GET /api/usage` records response-model token usage. Embedding usage and monetary cost are not included; use the OpenAI dashboard for complete billing. Chat history lives only in browser memory and resets on reload. Indexes/jobs persist across restarts.


## Current validation status

- The active knowledge base contains exactly the ten approved source PDFs: 237 pages and 770 indexed passages. The persisted index uses `text-embedding-3-large`.
- Backend: 15 offline regression tests pass, including source-page access restrictions, batch-scoped evidence notes, bounded revision, and API request formatting.
- All 14 live development evaluation cases pass answerability checks: 8 supported questions and 6 expected abstentions. All 8 supported answers pass model correctness/grounding grading; mean model-scored citation accuracy is 0.98. These are development seed cases, not a held-out benchmark or a guarantee of correctness.
- Live upload lifecycle check passes in an isolated synthetic corpus: a pending upload cannot influence answers or source access, and reindexing activates it with a page citation. The main ten-paper corpus remains unchanged.
- React production build and browser tests pass, including a real streamed OpenAI answer and opening its actual source page. Sources display rendered PDF pages and offer original PDF links; no browser PDF plugin is needed for the page preview.
- Frontend dependency audit after updating KaTeX: zero vulnerabilities.

Detailed reports are under `backend/storage/evals/`: `20261018T165034Z.json` for the final 14-case run, `lifecycle-report.json` for upload activation, and earlier runs retained for diagnostics. The failed early runs helped identify and fix over-abstention caused by unscoped page-batch gaps.

Browser tests use the installed Chrome executable in `frontend/playwright.config.ts`; change that path or install Playwright Chromium on another machine. Start both development servers first, then run `npx playwright test` from frontend for offline browser checks. Set `RUN_LIVE_UI=1` to include the funded live browser test. Tests never expose the API key.

After setup, run `./start-backend.ps1` and `./start-frontend.ps1` in separate PowerShell terminals from this application directory. Open http://127.0.0.1:5173. Development servers used for verification are stopped after testing. The index remains on disk, so no initial reindex is needed on the next launch.

## Admin performance dashboard

Open **Admin performance** in the sidebar or visit http://127.0.0.1:5173/admin. Restart the backend after installing this update; the frontend updates through Vite. The admin page is part of the same localhost-only assignment app and has no separate authentication.

The dashboard records new requests persistently in SQLite and provides overall and per-question average/maximum TTFT and total response time, individual request history, model/transport, status, search, pagination, and ten-second refresh. Repeated questions are grouped ignoring case and repeated whitespace. Navigating to admin and back preserves the current in-memory chat.

TTFT here is elapsed server time from request handling to the first verified answer result being emitted. It excludes progress events, internal model tokens, browser rendering and network latency. Because the pipeline sends a whole answer after verification, TTFT and total response time can be nearly identical. JSON responses have a single delivery point, so their first-answer and total times are equal. All durations are stored in milliseconds and displayed in seconds. Average and maximum metrics include only completed requests (including evidence-based abstentions); failures and interrupted requests are listed separately. Requests rejected before a valid active-corpus chat is prepared are not recorded. Earlier questions cannot be reconstructed from token-usage logs.

`GET /api/admin/metrics?view=questions` returns grouped metrics; `view=requests` returns individual attempts. Optional query parameters: `q`, `limit` (1–100), and `offset`. Existing document/index tables are preserved by the additive schema update. Requests still marked running after a backend restart become interrupted rather than receiving invented completion timings.
