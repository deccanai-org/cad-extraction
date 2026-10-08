#!/usr/bin/env python3
"""offline test of /tmp/z3c/pkg_left_shipped.sh's run.py against an in-memory bucket (no AWS calls)"""
import sys, os, json, re, time, shutil
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/z3conv/package')
import pkgcore as pc, pkg

SRC = open('/tmp/z3c/pkg_left_shipped.sh').read()
RUN = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF", SRC, re.S).group(1)
OUT = '/tmp/z3c/lefttest'
D = 'Zenitude-data-3'
B = pc.BUCKET; ST = pc.PSTATE; BASE = f'{pc.DATASET}/{pc.ROUTE}/'
ok = True


def check(name, cond):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name); ok &= bool(cond)


def setup(fresh=True):
    S = {}
    def put(k, v):
        S[k] = v if isinstance(v, bytes) else json.dumps(v).encode()
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - (60 if fresh else 7200)))
    put('cad-disk-extract/zenitude-data-3/_state/conv_status.json', {'updated': now, 'verification_complete': True,
        'eta': {p: {'open': 0, 'rerun_open': 0} for p in ('ifc', 'sds2', 'db1')}})
    rows = []
    def model(mid, cls, arch, verified=True, step=True, pipe='ifc'):
        rows.append({'model_key': f'{D}:{pipe}:{mid}', 'id': mid, 'pipeline': pipe, 'class': cls, 'grader_class': cls, 'status': 'converted',
                     'step_key': f's/{mid}.step' if step else None, 'verified': verified, 'verify_verdict': 'PASS' if verified else None,
                     'source_paths': [(arch, f'{mid}.ifc')]})
    def man_row(rel, mid=None, also=(), size=100, pipe='ifc'):
        r = {'relpath': rel, 'bytes': size, 'modality': 'step' if rel.startswith('model/step/') else 'ifc', 'sha256': rel[-1] * 64,
             'pii_redacted': False, 'source_key': 'x'}
        if mid:
            r.update(step_source=pipe, model_id=mid, step_key=f's/{mid}.step', converted_from=f'model/ifc/{mid}.ifc')
            if also:
                r['also_models'] = [{'model_id': a, 'step_source': 'ifc', 'step_key': f's/{a}.step', 'converted_from': f'model/ifc/{a}.ifc'} for a in also]
                r['also_model_ids'] = list(also); r['also_converted_from'] = [f'model/ifc/{a}.ifc' for a in also]
        return r
    def project(pid, man, placed, pipe='ifc'):
        base = f'{BASE}{pid}'
        put(f'{base}/manifest.jsonl', ('\n'.join(json.dumps(r) for r in man) + '\n').encode())
        plan = {'project_id': pid, 'source': 'zen3', 'excluded_non_asset_files': 0, 'duplicates_collapsed': 0, 'disk': D, 'source_archive': pid,
                'steps_not_shipped': [], 'native_steps_not_graded': [], 'unresolved_files': [{'path': 'u'}]}
        pj = pc.project_json(plan, man); pj['extra_field'] = 'kept'
        put(f'{base}/project.json', pj)
        for r in man:
            put(f"{base}/{r['relpath']}", b'x' * r['bytes'])
        put(f'{ST}/ledger_parts/{pid}.json', {'project_id': pid, 'disk': D, 'placements': {f'{D}:{pipe}:{m}': {'step_key': f's/{m}.step'} for m in placed}})
    q = []
    def queue(pid, mid=None):
        q.append({'model_key': f'{D}:ifc:{mid}' if mid else None, 'project_id': pid, 'relpath': None, 'queued_at': 'x',
                  'reason': 'left shipped set: class 2' if mid else 'left_shipped_set_project'})
    # P1: whole project, its only model class 2 -> deleted
    model('a', 2, 'P1'); project('P1', [man_row('model/ifc/a.ifc'), man_row('model/step/a.step', 'a')], ['a']); queue('P1')
    # P2: whole project, a placed model class 1 held only by verification -> skipped
    model('v', 1, 'P2', verified=False, pipe='sds2'); project('P2', [man_row('model/ifc/v.ifc'), man_row('model/step/v.step', 'v', pipe='sds2')], ['v'], pipe='sds2'); queue('P2')
    # P3: stays packaged: s1 shipped (primary P3) with c attached; b own row (class 2) dropped; c detached; d class 1 shipped -> skip;
    #     e own row shared with f (class 1 shipped) -> skip; g row missing -> skip
    for m, c in (('s1', 1), ('b', 2), ('c', 3), ('d', 1), ('e', 2), ('f', 1), ('g', 2)):
        model(m, c, 'P3')
    project('P3', [man_row('model/ifc/s1.ifc'), man_row('model/step/s1.step', 's1', also=('c',)), man_row('model/step/b.step', 'b', size=300),
                   man_row('model/step/d.step', 'd'), man_row('model/step/e.step', 'e', also=('f',))], ['s1', 'b', 'c', 'd', 'e', 'f'])
    for m in ('b', 'c', 'd', 'e', 'g'):
        queue('P3', m)
    # P4: rows-only queue but every shipped STEP row would go -> skipped (whole-project case)
    model('h', 2, 'P4'); project('P4', [man_row('model/ifc/h.ifc'), man_row('model/step/h.step', 'h')], ['h']); queue('P4', 'h')
    # P5: queued as a whole project but a target again (s5 shipped, primary P5): rows still processed (k dropped)
    model('s5', 1, 'P5'); model('k', 3, 'P5')
    project('P5', [man_row('model/step/s5.step', 's5'), man_row('model/step/k.step', 'k')], ['s5', 'k']); queue('P5'); queue('P5', 'k')
    put(f'{ST}/removals_pending.jsonl', ''.join(json.dumps(x) + '\n' for x in q).encode())
    pm = {f'{D}:ifc:s1': {'primary': 'P3'}, f'{D}:ifc:d': {'primary': 'P3'}, f'{D}:ifc:f': {'primary': 'P3'}, f'{D}:ifc:s5': {'primary': 'P5'}}
    put(pkg.PRIMARY_KEY, {'map': pm})
    return S, rows


def run(apply, fresh=True):
    S, rows = setup(fresh)
    deleted = []

    class C:
        def put_object(self, Bucket, Key, Body, **kw): S[Key] = Body
        def delete_object(self, Bucket, Key): deleted.append(Key); S.pop(Key, None)
        def delete_objects(self, Bucket, Delete):
            for o in Delete['Objects']:
                deleted.append(o['Key']); S.pop(o['Key'], None)
            return {}

    class Ad:
        def conv_rows(self, idx=None): return rows
        def project_ref(self, a): return {'project_id': a, 'source_key': a, 'size': 1}
        def project_of(self, a): return a

    pc.s3c = lambda: C()
    pc.get_bytes = lambda b, k: S.get(k)
    pc.get_json = lambda b, k: json.loads(S[k]) if k in S else None
    pc.put_json = lambda b, k, v, **kw: S.__setitem__(k, json.dumps(v).encode())
    pc.list_keys = lambda b, p, cap=None: [(k, len(v), None) for k, v in sorted(S.items()) if k.startswith(p)]
    vcalls = []

    def verify(b, pid, keys, **kw):
        man = pc.read_manifest(b, f'{BASE}{pid}'); pj = json.loads(S[f'{BASE}{pid}/project.json'])
        bad = []
        for r in man:
            if f"{BASE}{pid}/{r['relpath']}" not in S: bad.append('missing ' + r['relpath'])
            if r.get('step_source') and r['model_id'] not in keys: bad.append('not_shipped ' + r['relpath'])
            for a in r.get('also_models') or []:
                if a['model_id'] not in keys: bad.append('also_not_shipped ' + r['relpath'])
        if pj['files'] != len(man) or pj['bytes'] != sum(r['bytes'] for r in man): bad.append('pj')
        vcalls.append((pid, bad))
        return {'ok': not bad, 'checks': {'bad': len(bad)}}
    pc.verify_project = verify
    pkg.lock = lambda pid, o: True
    pkg.unlock = lambda pid: None
    pkg.load_adapter = lambda n: Ad()
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
    os.environ['APPLY'] = '1' if apply else '0'; os.environ['PKGLEFT_O'] = OUT
    code = 0
    try:
        exec(compile(RUN, 'run.py', 'exec'), {'__name__': '__main__'})
    except SystemExit as e:
        code = e.code
    return S, deleted, vcalls, code


print('--- dry run')
S, deleted, vc, code = run(False)
it = json.load(open(f'{OUT}/items.0.json'))
check('dry run: rc 0, nothing deleted or written', code == 0 and not deleted)
kinds = sorted((i['kind'], i['project_id'], i.get('relpath') or '') for i in it['items'])
print(kinds)
check('dry run plans P1 whole, P3 b row + c detach, P5 k row', kinds == [('detach', 'P3', 'model/step/s1.step'), ('project', 'P1', ''),
                                                                   ('row', 'P3', 'model/step/b.step'), ('row', 'P5', 'model/step/k.step')])
sk = {(s[0], (s[1] or '').rsplit(':', 1)[-1]): s[2] for s in it['skipped']}
for k, v in sorted(sk.items()):
    print('  skip', k, v)
check('P2 skipped (class 1 held by verification)', 'class 1' in sk.get(('P2', ''), ''))
check('P3 d skipped (shipped again)', 'shipped again' in sk.get(('P3', 'd'), ''))
check('P3 e skipped (shared with kept model)', 'shared' in sk.get(('P3', 'e'), ''))
check('P3 g skipped (not in manifest)', 'not in the manifest' in sk.get(('P3', 'g'), ''))
check('P4 h skipped (whole-project case)', 'whole-project' in sk.get(('P4', 'h'), ''))
check('P5 whole skipped (target again)', 'primary again' in sk.get(('P5', ''), ''))

print('--- apply with stale conv_status')
S, deleted, vc, code = run(True, fresh=False)
check('apply refused (rc 3), nothing deleted', code == 3 and not deleted)

print('--- apply')
S, deleted, vc, code = run(True)
check('apply rc 0', code == 0)
check('P1 emptied', not any(k.startswith(f'{BASE}P1/') for k in S))
check('P1 ledger placements empty', json.loads(S[f'{ST}/ledger_parts/P1.json'])['placements'] == {})
check('P2 untouched', f'{BASE}P2/model/step/v.step' in S)
m3 = pc.read_manifest(B, f'{BASE}P3')
check('P3 b row + object gone', not any(r['relpath'] == 'model/step/b.step' for r in m3) and f'{BASE}P3/model/step/b.step' not in S)
s1 = next(r for r in m3 if r['relpath'] == 'model/step/s1.step')
check('P3 c detached from s1 (file kept)', 'also_models' not in s1 and f'{BASE}P3/model/step/s1.step' in S)
check('P3 d, e rows kept', {'model/step/d.step', 'model/step/e.step'} <= {r['relpath'] for r in m3})
pj3 = json.loads(S[f'{BASE}P3/project.json'])
check('P3 project.json patched (files/bytes) and other fields kept', pj3['files'] == len(m3) and pj3['bytes'] == sum(r['bytes'] for r in m3)
      and pj3.get('extra_field') == 'kept' and pj3.get('unresolved_files_count') == 1)
lp3 = json.loads(S[f'{ST}/ledger_parts/P3.json'])['placements']
check('P3 ledger minus b, c', set(lp3) == {f'{D}:ifc:{m}' for m in ('s1', 'd', 'e', 'f')})
check('P3 verify ok', dict(vc).get('P3') == [])
check('P4 untouched', f'{BASE}P4/model/step/h.step' in S)
check('P5 k gone, s5 kept', f'{BASE}P5/model/step/k.step' not in S and f'{BASE}P5/model/step/s5.step' in S)
done = [json.loads(l) for k, v in S.items() if '/removals_done/' in k for l in v.decode().splitlines() if l.strip()]
check('done log: P1 objects + b + k + c detach', sorted(d['reason'] for d in done).count('left_shipped_set_project') == 4
      and {d['model_id'] for d in done if d.get('model_id')} == {'b', 'k', 'c'})
print('ALL PASS' if ok else 'SOME FAILED')
