"""Funded integration check in an isolated corpus; never changes the ten-paper index."""
import json
from datetime import datetime,timezone
import pymupdf
from fastapi.testclient import TestClient
from app.config import settings
from app import indexing
from app.main import app


def pdf_bytes(text):
    with pymupdf.open() as doc:
        page=doc.new_page()
        page.insert_textbox(pymupdf.Rect(60,60,535,780),text,fontsize=12)
        return doc.tobytes()


def main():
    original_storage=settings.storage_dir
    folder=original_storage/'lifecycle'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    settings.storage_dir=folder/'storage'
    settings.rag_data_dir=folder/'empty-source'
    settings.rag_data_dir.mkdir(parents=True)
    indexing.client.cache_clear();indexing.corpus.cache_clear()
    with TestClient(app) as client:
        baseline=client.post('/api/upload',files={'file':('Juniper overview.pdf',pdf_bytes('Project Juniper is a controlled laboratory calibration study. The researchers inspect measurement instruments and record their calibration procedures in laboratory notebooks. This overview describes the study scope and contains no calibration token.'),'application/pdf')})
        assert baseline.status_code==200
        first=client.post('/api/reindex');assert first.status_code==202
        assert client.get('/api/jobs/'+first.json()['job_id']).json()['status']=='succeeded'
        old_version=client.get('/api/documents').json()['active_version']['id']
        pending=client.post('/api/upload',files={'file':('Juniper calibration.pdf',pdf_bytes('Project Juniper calibration specification. The official calibration token for Project Juniper is ORCHID-6824. This identifier is used by the laboratory team to label the calibration run and cross-reference its notebook entry. The token must be copied exactly, including the hyphen.'),'application/pdf')})
        assert pending.status_code==200
        question={'question':"According to the documents, what is Project Juniper's calibration token?"}
        before=client.post('/api/chat',json=question);assert before.status_code==200
        assert before.json()['answerable'] is False
        assert client.get('/api/documents/'+pending.json()['id']+'/pdf').status_code==404
        print('PASS pending upload excluded from answers and PDF access',flush=True)
        second=client.post('/api/reindex');assert second.status_code==202
        assert client.get('/api/jobs/'+second.json()['job_id']).json()['status']=='succeeded'
        after=client.post('/api/chat',json=question);assert after.status_code==200
        answer=after.json()
        assert answer['answerable'] is True and 'ORCHID-6824' in answer['answer']
        assert any(s['document_id']==pending.json()['id'] for s in answer['sources'])
        assert answer['version']!=old_version
        report={'passed':True,'pending_excluded':True,'reindex_activates_upload':True,'before':before.json(),'after':answer,
                'note':'Synthetic isolated corpus; the active ten-paper corpus was not modified.'}
        path=original_storage/'evals/lifecycle-report.json'
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('PASS reindex activates uploaded content with a page citation',flush=True);print(path)

if __name__=='__main__':main()
