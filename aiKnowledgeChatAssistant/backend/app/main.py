import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, Response
import pymupdf
from pydantic import BaseModel, Field
from .config import settings
from . import store, indexing
from .workflow import graph
from .errors import public_error
from .metrics import RequestTimer, report as metrics_report

@asynccontextmanager
async def lifespan(app):
    store.init()
    yield

app = FastAPI(title='Paper Atlas',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],
                   allow_methods=['GET','POST'],allow_headers=['Content-Type'])

@app.middleware('http')
async def request_clock(request: Request, call_next):
    request.state.started = time.perf_counter()
    return await call_next(request)

@app.get('/api/admin/metrics')
def admin_metrics(q: str = Query('', max_length=500), view: Literal['questions','requests'] = 'questions',
                  limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return metrics_report(q, view, limit, offset)

class Message(BaseModel):
    role: Literal['user','assistant']
    content: str = Field(max_length=30000)
class Question(BaseModel):
    question: str = Field(min_length=1,max_length=8000)
    document_ids: list[str] = Field(default_factory=list,max_length=100)
    history: list[Message] = Field(default_factory=list,max_length=30)

def require_key():
    if not settings.openai_api_key:
        raise HTTPException(503,'Set OPENAI_API_KEY in backend/.env and restart the backend.')

@app.get('/api/health')
def health():
    return {'status':'ok','api_key_configured':bool(settings.openai_api_key),'model':settings.answer_model}

@app.get('/api/documents')
def documents():
    return {'documents':store.documents(),'active_version':store.active()}

@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400,'Choose a PDF file.')
    data = await file.read(50*1024*1024+1)
    if len(data)>50*1024*1024:
        raise HTTPException(413,'PDF exceeds the 50 MB limit.')
    try:
        doc = await asyncio.to_thread(store.register,file.filename,data)
        return {'id':doc['id'],'name':doc['name'],'message':'Saved. Reindex to include this document in answers.'}
    except Exception:
        raise HTTPException(400,'PDF could not be opened. Use an unencrypted, valid PDF.')

@app.post('/api/reindex',status_code=202)
def reindex(background: BackgroundTasks):
    require_key()
    if not store.INDEX_LOCK.acquire(blocking=False):
        raise HTTPException(409,'An indexing job is already running.')
    try:
        # Snapshot now: uploads arriving later remain pending until another build.
        with store.connect() as db:
            docs = [dict(row) for row in db.execute('SELECT * FROM documents ORDER BY name')]
            if not docs:
                raise HTTPException(400,'No PDFs are available.')
            job_id = uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(job_id,'queued','Preparing index',None,store.now()))
        background.add_task(indexing.build,job_id,docs)
        return {'job_id':job_id}
    except Exception:
        store.INDEX_LOCK.release()
        raise

@app.get('/api/jobs/{job_id}')
def job(job_id: str):
    with store.connect() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
    if not row:
        raise HTTPException(404,'Job not found.')
    return dict(row)

@app.get('/api/documents/{doc_id}/pdf')
def pdf(doc_id: str):
    current = store.active()
    if not current or doc_id not in current['document_ids']:
        raise HTTPException(404,'Document is not in the active knowledge base.')
    doc = store.document(doc_id)
    return FileResponse(doc['path'],media_type='application/pdf',filename=doc['name'],content_disposition_type='inline')

@app.get('/api/documents/{doc_id}/pages/{page_number}.png')
def source_page(doc_id: str, page_number: int):
    current = store.active()
    if not current or doc_id not in current['document_ids']:
        raise HTTPException(404,'Document is not in the active knowledge base.')
    doc = store.document(doc_id)
    if page_number < 1 or page_number > doc['pages']:
        raise HTTPException(404,'Page not found.')
    with store.PDF_LOCK, pymupdf.open(doc['path']) as pdf:
        png = pdf[page_number-1].get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False).tobytes('png')
    return Response(content=png,media_type='image/png',headers={'Cache-Control':'private, max-age=3600'})

@app.get('/api/usage')
def usage():
    with store.connect() as db:
        rows = [dict(row) for row in db.execute('SELECT kind,model,data,created FROM usage ORDER BY created DESC LIMIT 1000')]
    return {'calls':rows,'note':'Token usage for response calls; embedding usage and monetary cost are not included.'}

def prepare(request):
    require_key()
    current = store.active()
    if not current:
        raise HTTPException(409,'Build the knowledge base with Reindex before asking questions.')
    if not set(request.document_ids).issubset(set(current['document_ids'])):
        raise HTTPException(400,'Selected documents must belong to the active knowledge base.')
    return {'question':request.question,'history':[m.model_dump() for m in request.history],
            'selected':request.document_ids,'version':current}

def begin_timing(request, http_request, state, transport):
    return RequestTimer(request.question, settings.answer_model, state['version']['id'], transport,
                        started=getattr(http_request.state,'started',None))

@app.post('/api/chat')
def chat(request: Question, http_request: Request):
    state = prepare(request)
    timer = begin_timing(request,http_request,state,'json')
    try:
        result = graph.invoke(state)['result']
        timer.finish('completed',result)
        return {**result,'request_id':timer.id}
    except Exception as error:
        logging.exception('Chat failed')
        message = public_error(error)
        timer.finish('failed',error=message)
        raise HTTPException(502,message)

@app.post('/api/chat/stream')
def stream(request: Question, http_request: Request):
    state = prepare(request)
    timer = begin_timing(request,http_request,state,'sse')
    events = queue.Queue()
    stop = threading.Event()
    state['emit'] = lambda message: events.put(('progress',{'message':message}))
    def run():
        try:
            result = graph.invoke(state)['result']
            events.put(('result',{**result,'request_id':timer.id}))
        except Exception as error:
            logging.exception('Chat failed')
            events.put(('error',{'message':public_error(error)}))
        finally:
            events.put(('done',{}))
    async def generate():
        threading.Thread(target=run,daemon=True).start()
        result = None
        failure = None
        try:
            while not stop.is_set():
                try:
                    kind,data = events.get_nowait()
                except queue.Empty:
                    yield ': keepalive\n\n'
                    await asyncio.sleep(0.3)
                    continue
                if kind=='result':
                    result = data
                    if data.get('answer'):
                        timer.first_answer()
                elif kind=='error':
                    failure = data['message']
                elif kind=='done':
                    timer.finish('failed' if failure else 'completed',result,error=failure)
                yield f'event: {kind}\ndata: {json.dumps(data)}\n\n'
                if kind=='done':
                    break
        finally:
            stop.set()
            timer.finish('interrupted',error='Client disconnected before response completion.')
    return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
