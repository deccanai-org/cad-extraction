#!/usr/bin/env python3
"""unit test (local, pure Python, no Modal, no network, no geometry): the per-model orchestrator
(pmpstages/orchestrate.py) with fake stage functions - statuses, retries, class escalation, failure recording, index rows.

usage: python app/tests/test_orchestrate.py        (exit 0 = all cases pass)
Job rows come from jobs/new5.jsonl (no URLs in it); fake URLs are attached here (no SigV4 query: never expire).
"""
import copy, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'app'))
from pmpstages import orchestrate as O  # noqa: E402

O.time.sleep = lambda s: None          # no back-off waits in the test

ROWS = {}
for line in open(os.path.join(ROOT, 'jobs', 'new5.jsonl')):
    r = json.loads(line)
    ROWS[r['tag']] = r


def job(tag, put=True, urls=True, **kw):
    r = copy.deepcopy(ROWS[tag])
    if urls:
        r['urls'] = {'step': 'https://example.invalid/step', 'source': 'https://example.invalid/source'}
    if put:
        r['put_url'] = 'https://example.invalid/put'
    r.update(kw)
    return r


class Fake:
    """records every stage call; behaviour per stage from a script"""

    def __init__(self, pipeline=None, source=None, issues=None, upload=None):
        self.calls = []
        self.beh = dict(pipeline=pipeline or [], source=source or [], issues=issues or [], upload=upload or [])

    def _next(self, stage, default):
        b = self.beh[stage]
        x = b.pop(0) if b else default
        if isinstance(x, Exception):
            raise x
        return x

    def F(self):
        def src(kind):
            return {c: (lambda job, cls, run, c=c: (self.calls.append(('source', cls)),
                                                    self._next('source', {'ok': True, 'ifc': 'm.ifc', 'ifc_path': '/vol/x/source/m.ifc',
                                                                          'sha256': 'ab' * 32, 'cpu_seconds': 1, 'peak_gib': 1}))[1])
                    for c in ('S', 'M', 'L', 'XL')}

        def pipe(job, cls, spec, run):
            self.calls.append(('pipeline', cls, spec['mode']))
            return self._next('pipeline', {'ok': True, 'perfect': False, 'memory_killed_steps': [], 'cpu_seconds': 10, 'peak_gib': 2})

        def iss(job, cls, run):
            self.calls.append(('issues', cls))
            return self._next('issues', {'ok': True, 'bundle': {'path': '/vol/b.tar.gz', 'bytes': 10, 'sha256': 'cd' * 32, 'md5': 'ef' * 16},
                                         'cpu_seconds': 5, 'peak_gib': 3})

        def up(mid, run, url, headers):
            self.calls.append(('upload',))
            return self._next('upload', {'ok': True, 'http': 200, 'etag': 'x'})
        return {'source': {'regenerated_from_db1': src('db1'), 'emitted_from_sds2': src('sds2')},
                'pipeline': {c: pipe for c in ('S', 'M', 'L', 'XL')}, 'issues': {c: iss for c in ('S', 'M', 'L', 'XL')}, 'upload': up}


def go(j, fake, opts=None):
    rows = []
    r = O.orchestrate(j, 'test', opts or {'upload': True, 'escalate': True}, fake.F(), rows.append, log=lambda m: None)
    return r, rows


CASES = []


def case(f):
    CASES.append(f)
    return f


@case
def ifc_done():
    f = Fake()
    r, rows = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'done', r
    assert [c[0] for c in f.calls] == ['pipeline', 'issues', 'upload'], f.calls
    assert f.calls[0] == ('pipeline', 'S', 'package')
    assert rows[-1]['status'] == 'done' and r['cpu_seconds'] == 15 and r['peak_gib'] == 3
    assert r['model_folder'] == 'GRID3' and r['cls_final'] == 'S'


@case
def db1_source_then_volume_ifc():
    f = Fake()
    r, _ = go(job('n1_db1_small'), f)
    assert r['status'] == 'done', r
    assert f.calls[0] == ('source', 'S') and f.calls[1] == ('pipeline', 'S', 'volume'), f.calls


@case
def no_put_url_bundled():
    f = Fake()
    r, _ = go(job('n4_ifc_c2s', put=False), f)
    assert r['status'] == 'bundled' and r['error'] == 'no put_url in the job', r
    assert ('upload',) not in f.calls


@case
def upload_disabled_bundled():
    r, _ = go(job('n4_ifc_c2s'), Fake(), {'upload': False})
    assert r['status'] == 'bundled' and r['error'] is None, r


@case
def source_failed_stops():
    f = Fake(source=[{'ok': False, 'error': 'not reproduced'}])
    r, _ = go(job('n5_sds2'), f)
    assert r['status'] == 'source_failed' and r['error'] == 'not reproduced', r
    assert [c[0] for c in f.calls] == ['source'], f.calls


@case
def memory_kill_escalates():
    f = Fake(pipeline=[{'ok': True, 'memory_killed_steps': ['verify']}, {'ok': True, 'memory_killed_steps': []}])
    r, _ = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'done' and r['cls_final'] == 'M', r
    assert [c for c in f.calls if c[0] == 'pipeline'] == [('pipeline', 'S', 'package'), ('pipeline', 'M', 'package')]
    assert len(r['stages']['pipeline_attempts']) == 2
    assert ('issues', 'M') in f.calls             # the later stages run at the escalated class


@case
def memory_kill_no_escalation_when_disabled():
    f = Fake(pipeline=[{'ok': True, 'memory_killed_steps': ['verify']}])
    r, _ = go(job('n4_ifc_c2s'), f, {'upload': True, 'escalate': False})
    assert r['cls_final'] == 'S' and r['status'] == 'done', r   # recorded in stages.pipeline.memory_killed_steps
    assert r['stages']['pipeline']['memory_killed_steps'] == ['verify']


@case
def container_crash_retried_then_recorded():
    f = Fake(pipeline=[RuntimeError('container died')] * 3)
    r, _ = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'pipeline_failed', r
    assert len(r['stages']['pipeline']['infra_errors']) == 3, r['stages']['pipeline']
    assert [c[0] for c in f.calls] == ['pipeline'] * 3


@case
def crash_then_success():
    f = Fake(pipeline=[RuntimeError('preempted')])
    r, _ = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'done' and r['stages']['pipeline']['infra_errors'] == ['RuntimeError: preempted'], r


@case
def timeout_not_retried():
    class FunctionTimeoutError(Exception):
        pass
    f = Fake(pipeline=[FunctionTimeoutError('24h')])
    r, _ = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'pipeline_failed' and len([c for c in f.calls if c[0] == 'pipeline']) == 1, (r, f.calls)


@case
def issues_failed_recorded():
    f = Fake(issues=[{'ok': False, 'error': 'issues checks failed: [deterministic]'}])
    r, _ = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'issues_failed' and 'deterministic' in r['error'], r
    assert ('upload',) not in f.calls


@case
def upload_failed_recorded():
    f = Fake(upload=[{'ok': False, 'error': 'HTTP 403'}])
    r, _ = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'upload_failed' and r['error'] == 'HTTP 403', r


@case
def too_big_not_run():
    f = Fake()
    r, _ = go(job('n4_ifc_c2s', bytes=10 ** 9, **{'class': None}), f)
    assert r['status'] == 'too_big_v1' and not f.calls, r


@case
def no_urls_not_runnable():
    f = Fake()
    r, _ = go(job('n4_ifc_c2s', urls=False), f)
    assert r['status'] == 'not_runnable:no_step_url' and not f.calls, r


@case
def bad_job_is_error_row():
    r, rows = go({'model_id': 'x/../y', 'pid': 'p'}, Fake())
    assert r['status'] == 'error' and 'safe folder name' in r['error'] and rows, r


@case
def preemption_restarts_counted_and_tokens_distinct():
    seen = []

    class F2(Fake):
        def F(self):
            d = super().F()
            p = d['pipeline']['S']

            def pipe(job, cls, spec, run):
                seen.append(job.get('_call'))
                if len(seen) == 1:
                    raise RuntimeError('container died')
                return dict(p(job, cls, spec, run), container_starts=2)
            d['pipeline'] = {c: pipe for c in d['pipeline']}
            return d
    f = F2()
    r, _ = go(job('n4_ifc_c2s'), f)
    assert r['status'] == 'done' and r['container_restarts'] == 1, r
    assert len(seen) == 2 and all(seen) and seen[0] != seen[1], seen


@case
def index_rows_have_no_urls():
    f = Fake()
    _, rows = go(job('n4_ifc_c2s'), f)
    assert all('example.invalid' not in json.dumps(x, default=str) for x in rows)


@case
def db1_host_unsuitable_redrawn_and_recorded():
    hu = {'ok': False, 'retryable': True, 'verdict': 'host_unsuitable', 'error': 'host_unsuitable: avx2', 'cpu_seconds': 1}
    f = Fake(source=[dict(hu), dict(hu)])
    r, _ = go(job('n1_db1_small'), f)
    assert r['status'] == 'done', r
    assert r['stages']['source']['attempts'] == 3 and [d['verdict'] for d in r['stages']['source']['host_draws']][:2] == ['host_unsuitable'] * 2, r


@case
def db1_host_unsuitable_bounded():
    hu = {'ok': False, 'retryable': True, 'verdict': 'host_unsuitable', 'error': 'host_unsuitable: avx2'}
    f = Fake(source=[dict(hu) for _ in range(20)])
    r, _ = go(job('n1_db1_small'), f)
    assert r['status'] == 'source_failed' and r['stages']['source']['attempts'] == O.HOST_DRAWS, r
    assert sum(1 for c in f.calls if c[0] == 'source') == O.HOST_DRAWS


bad = 0
for c in CASES:
    try:
        c()
        print(f'ok   {c.__name__}')
    except Exception as e:
        bad += 1
        print(f'FAIL {c.__name__}: {type(e).__name__}: {str(e)[:600]}')
print(f'{len(CASES) - bad}/{len(CASES)} passed')
sys.exit(1 if bad else 0)
