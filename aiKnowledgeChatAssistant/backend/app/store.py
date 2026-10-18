"""Immutable document snapshots, durable jobs and atomic active-index pointers."""
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .config import settings

INITIAL_FILES = {
    'Attention is all you need.pdf', 'BERT.pdf', 'Chain-of-Thought Prompting.pdf',
    'Crossing the Reward Bridge.pdf', 'Distilling the Knowledge in a Neural Network.pdf',
    'Improving Language Understanding by Generative Pre-Training.pdf',
    'Learning to summarize from human feedback.pdf', 'LORA.pdf',
    'Retentive Network.pdf', 'The Illusion of Thinking.pdf',
}
INDEX_LOCK = threading.Lock()
PDF_LOCK = threading.RLock()

def now():
    return datetime.now(timezone.utc).isoformat()

def connect():
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.storage_dir / 'metadata.sqlite', timeout=30)
    db.row_factory = sqlite3.Row
    return db

def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,name TEXT,hash TEXT UNIQUE,path TEXT,pages INTEGER,created TEXT);
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY,manifest TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT,message TEXT,version TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY,kind TEXT,model TEXT,data TEXT,created TEXT);
        ''')
        db.execute("UPDATE jobs SET status='failed',message='Server restarted during indexing; previous index remains active.' WHERE status IN ('queued','running')")
    from .metrics import SCHEMA
    with connect() as db:
        db.executescript(SCHEMA)
        db.execute("UPDATE request_metrics SET status='interrupted',finished=?,error='Server restarted before response completion.' WHERE status='running'", (now(),))
    # Only the agreed ten files are imported automatically. Other files require upload.
    for name in sorted(INITIAL_FILES):
        path = settings.rag_data_dir / name
        if path.exists():
            register(name, path.read_bytes())

def register(name: str, content: bytes):
    import pymupdf
    with PDF_LOCK, pymupdf.open(stream=content, filetype='pdf') as pdf:
        if pdf.needs_pass or not len(pdf):
            raise ValueError('PDF must be readable and contain at least one page.')
        pages = len(pdf)
    digest = hashlib.sha256(content).hexdigest()
    with connect() as db:
        existing = db.execute('SELECT * FROM documents WHERE hash=?', (digest,)).fetchone()
        if existing:
            return dict(existing)
        doc_id = uuid.uuid4().hex
        path = settings.storage_dir / 'documents' / f'{doc_id}.pdf'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',
                   (doc_id, Path(name.replace('\\', '/')).name, digest, str(path), pages, now()))
        return dict(db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone())

def active():
    with connect() as db:
        row = db.execute("SELECT value FROM config WHERE key='active'").fetchone()
        if not row:
            return None
        version = db.execute('SELECT * FROM versions WHERE id=?', (row['value'],)).fetchone()
        return {'id': version['id'], **json.loads(version['manifest'])}

def documents():
    current = active()
    ids = set(current['document_ids']) if current else set()
    with connect() as db:
        return [{**dict(row), 'status': 'active' if row['id'] in ids else 'pending'}
                for row in db.execute('SELECT id,name,hash,pages,created FROM documents ORDER BY name')]

def document(doc_id):
    with connect() as db:
        row = db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
        return dict(row) if row else None

def job_update(job_id, status, message, version=None):
    with connect() as db:
        db.execute('UPDATE jobs SET status=?,message=?,version=? WHERE id=?', (status,message,version,job_id))

def usage(kind, model, data):
    with connect() as db:
        db.execute('INSERT INTO usage VALUES(?,?,?,?,?)', (uuid.uuid4().hex,kind,model,json.dumps(data),now()))

