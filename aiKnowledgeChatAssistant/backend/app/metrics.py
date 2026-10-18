"""Durable request timings. Progress events never count as answer content."""
import re
import threading
import time
import uuid
from . import store

SCHEMA = '''
CREATE TABLE IF NOT EXISTS request_metrics(
 id TEXT PRIMARY KEY, question TEXT NOT NULL, question_key TEXT NOT NULL,
 created TEXT NOT NULL, finished TEXT, model TEXT NOT NULL, version TEXT,
 transport TEXT NOT NULL, status TEXT NOT NULL, answerable INTEGER,
 ttft_ms REAL, total_ms REAL, error TEXT
);
CREATE INDEX IF NOT EXISTS request_metrics_created ON request_metrics(created DESC);
CREATE INDEX IF NOT EXISTS request_metrics_question ON request_metrics(question_key);
'''

class RequestTimer:
    def __init__(self, question, model, version, transport, started=None, clock=None):
        self.clock = clock or time.perf_counter
        self.started = self.clock() if started is None else started
        self.first_ms = None
        self.finished = False
        self.lock = threading.Lock()
        self.id = uuid.uuid4().hex
        key = re.sub(r'\s+', ' ', question.strip()).casefold()
        with store.connect() as db:
            db.execute('''INSERT INTO request_metrics
                (id,question,question_key,created,model,version,transport,status)
                VALUES(?,?,?,?,?,?,?,?)''',
                (self.id, question.strip(), key, store.now(), model, version, transport, 'running'))

    def first_answer(self):
        with self.lock:
            if not self.finished and self.first_ms is None:
                self.first_ms = max(0, (self.clock()-self.started)*1000)

    def finish(self, status, result=None, error=None):
        with self.lock:
            if self.finished:
                return
            elapsed = max(0, (self.clock()-self.started)*1000)
            first = self.first_ms
            if status == 'completed' and first is None and result and result.get('answer'):
                first = elapsed
            answerable = int(bool(result.get('answerable'))) if result is not None else None
            with store.connect() as db:
                db.execute('''UPDATE request_metrics SET finished=?,status=?,answerable=?,ttft_ms=?,total_ms=?,error=?
                    WHERE id=? AND status='running' ''',
                    (store.now(), status, answerable, first, max(elapsed, first or 0), error, self.id))
            self.finished = True


def report(query='', view='questions', limit=50, offset=0):
    # Search is literal, including user-entered percent and underscore characters.
    escaped = query.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    where = "WHERE question LIKE ? ESCAPE '\\'" if escaped else ''
    params = [f'%{escaped}%'] if escaped else []
    with store.connect() as db:
        summary = dict(db.execute(f'''SELECT COUNT(*) AS requests,
            COALESCE(SUM(status='completed'),0) AS completed,
            COALESCE(SUM(status='failed'),0) AS failed,
            COALESCE(SUM(status='interrupted'),0) AS interrupted,
            COALESCE(SUM(status='running'),0) AS running,
            AVG(CASE WHEN status='completed' THEN ttft_ms END) AS avg_ttft_ms,
            MAX(CASE WHEN status='completed' THEN ttft_ms END) AS max_ttft_ms,
            AVG(CASE WHEN status='completed' THEN total_ms END) AS avg_total_ms,
            MAX(CASE WHEN status='completed' THEN total_ms END) AS max_total_ms
            FROM request_metrics {where}''', params).fetchone())
        if view == 'requests':
            total = summary['requests']
            rows = [dict(row) for row in db.execute(f'''SELECT * FROM request_metrics {where}
                ORDER BY created DESC,id DESC LIMIT ? OFFSET ?''', [*params,limit,offset])]
        else:
            total = db.execute(f'''SELECT COUNT(DISTINCT question_key) FROM request_metrics {where}''',params).fetchone()[0]
            rows = [dict(row) for row in db.execute(f'''SELECT question_key,MAX(question) AS question,
                COUNT(*) AS requests,COALESCE(SUM(status='completed'),0) AS completed,
                COALESCE(SUM(status='failed'),0) AS failed,
                COALESCE(SUM(status='interrupted'),0) AS interrupted,
                COALESCE(SUM(status='running'),0) AS running,
                AVG(CASE WHEN status='completed' THEN ttft_ms END) AS avg_ttft_ms,
                MAX(CASE WHEN status='completed' THEN ttft_ms END) AS max_ttft_ms,
                AVG(CASE WHEN status='completed' THEN total_ms END) AS avg_total_ms,
                MAX(CASE WHEN status='completed' THEN total_ms END) AS max_total_ms,
                MAX(created) AS last_asked
                FROM request_metrics {where} GROUP BY question_key
                ORDER BY last_asked DESC,question_key LIMIT ? OFFSET ?''', [*params,limit,offset])]
        since = db.execute('SELECT MIN(created) FROM request_metrics').fetchone()[0]
    return {'summary':summary,'rows':rows,'total':total,'view':view,'limit':limit,'offset':offset,
            'recording_since':since,'generated_at':store.now(),
            'timing_definition':'Server elapsed time from request handling to the first verified answer result and response completion. Progress updates do not count as tokens. Answers are delivered as one verified result, so TTFT and total may be similar. Browser rendering and network latency are excluded. Averages and maximums include completed requests only, including grounded abstentions.'}
