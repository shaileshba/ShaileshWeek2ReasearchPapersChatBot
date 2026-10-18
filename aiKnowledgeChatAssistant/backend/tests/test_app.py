import pytest
from fastapi.testclient import TestClient
import pymupdf
from app.config import settings
from app import store, indexing, workflow
from app.main import app
REAL_MODEL_JSON = workflow.model_json

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,'storage_dir',tmp_path/'storage')
    monkeypatch.setattr(settings,'rag_data_dir',tmp_path/'source')
    monkeypatch.setattr(settings,'openai_api_key','test-key')
    settings.rag_data_dir.mkdir()
    monkeypatch.setattr(workflow,'model_json',lambda *args: (_ for _ in ()).throw(AssertionError('Live model calls are forbidden in offline tests')))
    indexing.corpus.cache_clear()
    indexing.client.cache_clear()
    with TestClient(app) as test:
        yield test
    if store.INDEX_LOCK.locked():
        store.INDEX_LOCK.release()

def pdf_bytes(text='Test research evidence'):
    doc=pymupdf.open(); page=doc.new_page(); page.insert_text((70,70),text)
    data=doc.tobytes(); doc.close(); return data

def activate(doc_ids,version='v1'):
    import json
    with store.connect() as db:
        db.execute('INSERT INTO versions VALUES(?,?,?)',(version,json.dumps({'document_ids':doc_ids,'embedding_model':'test'}),store.now()))
        db.execute("INSERT OR REPLACE INTO config VALUES('active',?)",(version,))

def test_upload_pending_and_duplicate(client):
    data=pdf_bytes()
    first=client.post('/api/upload',files={'file':('paper.pdf',data,'application/pdf')})
    assert first.status_code==200
    second=client.post('/api/upload',files={'file':('again.pdf',data,'application/pdf')})
    assert first.json()['id']==second.json()['id']
    result=client.get('/api/documents').json()
    assert result['active_version'] is None
    assert len(result['documents'])==1
    assert result['documents'][0]['status']=='pending'
    assert client.get(f"/api/documents/{first.json()['id']}/pdf").status_code==404
    assert client.post('/api/chat',json={'question':'What does it say?'}).status_code==409

def test_pending_cannot_be_selected(client):
    a=store.register('active.pdf',pdf_bytes('active'))
    b=store.register('pending.pdf',pdf_bytes('pending'))
    activate([a['id']])
    assert client.post('/api/chat',json={'question':'hello','document_ids':[b['id']]}).status_code==400
    docs=client.get('/api/documents').json()['documents']
    assert {d['name']:d['status'] for d in docs}=={'active.pdf':'active','pending.pdf':'pending'}
    assert client.get(f"/api/documents/{a['id']}/pdf").status_code==200
    assert client.get(f"/api/documents/{a['id']}/pages/1.png").headers['content-type']=='image/png'
    assert client.get(f"/api/documents/{a['id']}/pages/0.png").status_code==404
    assert client.get(f"/api/documents/{b['id']}/pages/1.png").status_code==404

def test_failed_reindex_preserves_active(client,monkeypatch):
    a=store.register('paper.pdf',pdf_bytes())
    activate([a['id']])
    monkeypatch.setattr(indexing,'extract',lambda d: (_ for _ in ()).throw(RuntimeError('failure')))
    response=client.post('/api/reindex')
    assert response.status_code==202
    job=client.get('/api/jobs/'+response.json()['job_id']).json()
    assert job['status']=='failed'
    assert store.active()['id']=='v1'
    assert not store.INDEX_LOCK.locked()

def test_reindex_activates_only_snapshot(client,monkeypatch):
    a=store.register('paper.pdf',pdf_bytes('one'))
    class Embed:
        def embed_documents(self,texts): return [[1.,0.,0.] for _ in texts]
    monkeypatch.setattr(indexing,'embeddings',lambda *args:Embed())
    monkeypatch.setattr(workflow,'model_json',lambda *args:{'text':'Scanned research page with enough transcribed content for this indexing test.'})
    original=indexing.extract
    def extract(doc):
        store.register('later.pdf',pdf_bytes('uploaded during build'))
        return original(doc)
    monkeypatch.setattr(indexing,'extract',extract)
    result=client.post('/api/reindex')
    assert client.get('/api/jobs/'+result.json()['job_id']).json()['status']=='succeeded'
    assert store.active()['document_ids']==[a['id']]
    assert next(d for d in store.documents() if d['name']=='later.pdf')['status']=='pending'

def test_initial_import_is_allowlisted(client):
    (settings.rag_data_dir/'BERT.pdf').write_bytes(pdf_bytes('BERT source'))
    (settings.rag_data_dir/'extra.pdf').write_bytes(pdf_bytes('must not import'))
    store.init()
    assert [d['name'] for d in store.documents()]==['BERT.pdf']

def test_invalid_upload_and_no_key(client,monkeypatch):
    assert client.post('/api/upload',files={'file':('x.pdf',b'not pdf')}).status_code==400
    monkeypatch.setattr(settings,'openai_api_key','')
    assert client.post('/api/reindex').status_code==503

def test_citation_validation():
    sources=[{'source_id':'S1'}]
    assert workflow.validate_result({'answerable':True,'answer':'A claim [S99]','citations':['S99']},sources)['answerable'] is False
    assert workflow.validate_result({'answerable':True,'answer':'No citation','citations':[]},sources)['answerable'] is False
    assert workflow.validate_result({'answerable':True,'answer':'Claim [S1]','citations':['S1']},sources)['answerable'] is True
    assert workflow.validate_result({'answerable':False,'answer':'Invented answer [S1]','citations':['S1']},sources)['answer']==workflow.ABSTENTION

def test_verifier_rejects_unsupported_claim(client,monkeypatch):
    monkeypatch.setattr(workflow,'model_json',lambda *args:{'supported':False})
    result=workflow.verify({'question':'q','result':{'answerable':True,'answer':'Unsupported [S1]','citations':['S1']},
        'sources':[{'source_id':'S1'}],'notes':[],'version':{'id':'v1'},'plan':{'task':'qa'}})['result']
    assert result['answerable'] is False
    assert result['sources']==[]

def test_summary_covers_all_selected_pages(client,monkeypatch):
    chunks=[{'id':'x','text':'attention','metadata':{'document_id':'a','name':'a','page':1}}]
    pages=[{'document_id':'a','name':'a','page':p,'text':f'page {p}'} for p in range(1,9)]
    monkeypatch.setattr(indexing,'corpus',lambda _: (chunks,pages))
    class Embed:
        def embed_query(self,q):return [1,0,0]
    class Collection:
        def query(self,**kwargs): return {'ids':[['x']]}
    class Client:
        def get_collection(self,*args): return Collection()
    monkeypatch.setattr(indexing,'embeddings',lambda *args:Embed())
    monkeypatch.setattr(indexing,'client',lambda:Client())
    result=indexing.retrieve({'id':'v1','document_ids':['a'],'embedding_model':'test'},'summary',['a'],'summary')
    assert [s['page'] for s in result]==list(range(1,9))


def test_chat_stream_progress_and_result(client,monkeypatch):
    a=store.register('paper.pdf',pdf_bytes())
    activate([a['id']])
    from app.main import graph
    def invoke(state):
        assert state['version']['id']=='v1'
        state['emit']('Checking source pages')
        return {'result':{'answerable':False,'answer':workflow.ABSTENTION,'citations':[],'sources':[],'version':'v1','task':'qa'}}
    monkeypatch.setattr(graph,'invoke',invoke)
    response=client.post('/api/chat/stream',json={'question':'unsupported question'})
    assert response.status_code==200
    assert 'event: progress' in response.text
    assert 'event: result' in response.text
    assert workflow.ABSTENTION in response.text


def test_compiled_graph_uses_fresh_evidence(client,monkeypatch):
    a=store.register('paper.pdf',pdf_bytes())
    version={'id':'v1','document_ids':[a['id']]}
    source={'source_id':'S1','document_id':a['id'],'name':'paper.pdf','page':1,'text':'The measured value is 42.'}
    monkeypatch.setattr(indexing,'retrieve',lambda *args:[source])
    monkeypatch.setattr(workflow,'image_part',lambda *args:{'type':'input_text','text':'page image fixture'})
    responses=iter([
        {'task':'qa','query':'measured value','document_ids':[a['id']]},
        {'evidence':[{'source_id':'S1','findings':'The measured value is 42.'}],'gaps':[]},
        {'answerable':True,'answer':'The measured value is 42. [S1]','citations':['S1']},
        {'supported':True},
    ])
    monkeypatch.setattr(workflow,'model_json',lambda *args:next(responses))
    result=workflow.graph.invoke({'question':'What is the measured value?','history':[],'selected':[],'version':version})['result']
    assert result['answerable'] is True
    assert result['sources'][0]['page']==1
    assert result['version']=='v1'

def test_provider_quota_error_is_actionable():
    import httpx
    from openai import RateLimitError
    from app.errors import public_error
    response=httpx.Response(429,request=httpx.Request('POST','https://api.openai.com/v1/embeddings'))
    error=RateLimitError('no credits remaining',response=response,body={'code':'credit_balance_exhausted'})
    assert 'credits are exhausted' in public_error(error)


def test_json_mode_contract(client,monkeypatch):
    from types import SimpleNamespace
    def create(**kwargs):
        assert kwargs['text']['format']['type']=='json_object'
        assert any('json' in part.get('text','').lower() for part in kwargs['input'][0]['content'])
        assert kwargs['store'] is False
        return SimpleNamespace(usage=None,output_text='{"ok":true}')
    monkeypatch.setattr(workflow,'OpenAI',lambda **kwargs:SimpleNamespace(responses=SimpleNamespace(create=create)))
    assert REAL_MODEL_JSON('Return an object',[workflow.text_part({'test':'contract'})])=={'ok':True}

def test_revision_is_bounded_and_keeps_verification(client,monkeypatch):
    a=store.register('paper.pdf',pdf_bytes())
    version={'id':'v1','document_ids':[a['id']]}
    source={'source_id':'S1','document_id':a['id'],'name':'paper.pdf','page':1,'text':'The value is 42.'}
    monkeypatch.setattr(indexing,'retrieve',lambda *args:[source])
    monkeypatch.setattr(workflow,'image_part',lambda *args:{'type':'input_text','text':'fixture'})
    for final_supported in (True,False):
        responses=iter([
            {'task':'qa','query':'value','document_ids':[a['id']]},
            {'evidence':[{'source_id':'S1','findings':'The value is 42.'}],'gaps':[]},
            {'answerable':True,'answer':'The value is 43. [S1]','citations':['S1']},
            {'supported':False,'reason':'The source reports 42, not 43.'},
            {'answerable':True,'answer':'The value is 42. [S1]','citations':['S1']},
            {'supported':final_supported,'reason':'Test verdict'},
        ])
        monkeypatch.setattr(workflow,'model_json',lambda *args:next(responses))
        state=workflow.graph.invoke({'question':'What value?','history':[],'selected':[],'version':version})
        assert state['revision_count']==1
        assert state['result']['answerable'] is final_supported
        if final_supported:
            assert '42' in state['result']['answer']
        else:
            assert state['result']['answer']==workflow.ABSTENTION

def test_read_notes_are_scoped_to_their_source_batch(client,monkeypatch):
    sources=[{'source_id':f'S{i}','document_id':'a','name':'a.pdf','page':i,'text':'Page text'} for i in range(1,7)]
    monkeypatch.setattr(workflow.store,'document',lambda _: {'path':'fixture'})
    monkeypatch.setattr(workflow,'image_part',lambda *args:{'type':'input_text','text':'fixture'})
    replies=iter([
        {'evidence':[{'source_id':'S1','findings':'Table value 42'},{'source_id':'S999','findings':'Invalid source'}],'gaps':[]},
        {'evidence':[],'gaps':['This batch does not contain the table.']},
    ])
    monkeypatch.setattr(workflow,'model_json',lambda *args:next(replies))
    result=workflow.read({'question':'value?','plan':{'query':'value','task':'qa'},'sources':sources})
    assert [e['source_id'] for e in result['notes'][0]['evidence']]==['S1']
    assert result['notes'][1]['source_ids']==['S6']
    assert result['notes'][1]['gaps_in_this_batch_only']==['This batch does not contain the table.']

def test_metrics_aggregate_repeated_questions_and_exclude_failures(client):
    from app.metrics import RequestTimer
    clock=[10.0]
    first=RequestTimer('What is attention?', 'test-model','v1','sse',started=10.0,clock=lambda:clock[0])
    clock[0]=10.12; first.first_answer()
    clock[0]=10.35; first.finish('completed',{'answer':'A cited answer','answerable':True})
    clock[0]=11; first.finish('failed',error='Must not overwrite a completed record')
    second=RequestTimer('  WHAT   is attention?  ', 'test-model','v1','sse',started=20,clock=lambda:clock[0])
    clock[0]=20.3; second.first_answer()
    clock[0]=20.6; second.finish('completed',{'answer':'Insufficient evidence','answerable':False})
    third=RequestTimer('What is attention?', 'test-model','v1','sse',started=30,clock=lambda:clock[0])
    clock[0]=32; third.finish('failed',error='Test failure')
    response=client.get('/api/admin/metrics')
    assert response.status_code==200
    data=response.json();summary=data['summary']
    assert summary['requests']==3 and summary['completed']==2 and summary['failed']==1
    assert summary['avg_ttft_ms']==pytest.approx(210)
    assert summary['max_ttft_ms']==pytest.approx(300)
    assert summary['avg_total_ms']==pytest.approx(475)
    assert summary['max_total_ms']==pytest.approx(600)
    assert data['total']==1
    assert data['rows'][0]['requests']==3
    assert data['rows'][0]['avg_ttft_ms']==pytest.approx(210)
    history=client.get('/api/admin/metrics?view=requests&limit=2').json()
    assert history['total']==3 and len(history['rows'])==2
    failed=next(r for r in client.get('/api/admin/metrics?view=requests').json()['rows'] if r['status']=='failed')
    assert failed['ttft_ms'] is None


def test_metrics_empty_search_and_restart(client):
    from app.metrics import RequestTimer
    empty=client.get('/api/admin/metrics').json()
    assert empty['summary']['avg_ttft_ms'] is None and empty['total']==0
    timer=RequestTimer('A 100% literal_question', 'test-model','v1','sse')
    assert client.get('/api/admin/metrics?q=100%25').json()['total']==1
    assert client.get('/api/admin/metrics?q=_question').json()['total']==1
    assert client.get('/api/admin/metrics?q=missing').json()['total']==0
    store.init()
    row=client.get('/api/admin/metrics?view=requests').json()['rows'][0]
    assert row['id']==timer.id and row['status']=='interrupted'
    assert row['total_ms'] is None and row['ttft_ms'] is None
    assert client.get('/api/admin/metrics?limit=0').status_code==422
    assert client.get('/api/admin/metrics?offset=-1').status_code==422


def test_stream_records_answer_not_progress_and_records_failures(client,monkeypatch):
    from app.main import graph
    a=store.register('paper.pdf',pdf_bytes());activate([a['id']])
    def invoke(state):
        state['emit']('Retrieving PDF evidence')
        # A progress message is not an answer token.
        with store.connect() as db:
            row=db.execute('SELECT * FROM request_metrics').fetchone()
        assert row['ttft_ms'] is None and row['status']=='running'
        return {'result':{'answerable':False,'answer':workflow.ABSTENTION,'citations':[],'sources':[],'version':'v1','task':'qa'}}
    monkeypatch.setattr(graph,'invoke',invoke)
    streamed=client.post('/api/chat/stream',json={'question':'Where is the evidence?'})
    assert streamed.status_code==200 and 'request_id' in streamed.text
    row=client.get('/api/admin/metrics?view=requests').json()['rows'][0]
    assert row['status']=='completed' and row['answerable']==0
    assert 0<=row['ttft_ms']<=row['total_ms']
    def fail(state):raise RuntimeError('Internal details should not be exposed')
    monkeypatch.setattr(graph,'invoke',fail)
    assert 'event: error' in client.post('/api/chat/stream',json={'question':'Will this fail?'}).text
    assert client.post('/api/chat',json={'question':'Will JSON fail?'}).status_code==502
    report=client.get('/api/admin/metrics?view=requests').json()
    assert report['summary']['completed']==1 and report['summary']['failed']==2
    assert all(r['ttft_ms'] is None for r in report['rows'] if r['status']=='failed')


def test_json_request_records_total_and_first_answer(client,monkeypatch):
    from app.main import graph
    a=store.register('paper.pdf',pdf_bytes());activate([a['id']])
    monkeypatch.setattr(graph,'invoke',lambda state:{'result':{'answer':'Test answer','answerable':True,'sources':[]}})
    result=client.post('/api/chat',json={'question':'A JSON question'}).json()
    row=client.get('/api/admin/metrics?view=requests').json()['rows'][0]
    assert row['id']==result['request_id'] and row['transport']=='json'
    assert row['ttft_ms']==row['total_ms'] and row['status']=='completed'
