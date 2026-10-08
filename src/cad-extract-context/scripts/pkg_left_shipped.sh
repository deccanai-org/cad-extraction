#!/bin/bash
# Packaging 'left shipped set' removals (owner-approved): packaged STEP rows / whole packaged projects whose model(s) are STILL not
# class 1 after the IFC + SDS2 re-runs drained. DRY RUN unless APPLY=1 below (the lead flips it after reviewing the dry-run output).
# Run on the coordinator box via: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/pkg_left_shipped.sh 900
#  - input: _state/packaging/removals_pending.jsonl entries with reason 'left shipped set: ...' (rows) or 'left_shipped_set_project'
#    (whole projects) ONLY. dedup_non_primary*, 'model no longer in the index', sha_mismatch / orphan / dup objects are NOT touched.
#    Keys already in any removals_done/*.jsonl log are skipped.
#  - APPLY guard: refuses to change anything unless conv_status (< 30 min old) shows ifc, sds2 and db1 open = 0 and rerun_open = 0
#  - re-check against the CURRENT index (adapter conv_rows + ship_decision) and primary map, per item, at run time:
#      a model is removed only if its current class (or grader_class) is not 1. Skipped and logged: a model that is class 1 again
#      (shipped, or class 1 held back only by verification), a model shipped again with its primary elsewhere (that is dedup, not
#      this approval), a model no longer in the index
#      a whole project is removed only if it is not a target (no shipped model has it as primary) and EVERY model placed in it
#      (ledger part) is currently not class 1; a project with no placements in its ledger part is skipped (check by hand)
#      a STEP file shared by several models (also_models, same content) is deleted only if all of them qualify; a qualifying model
#      that is only attached to another model's file is detached (manifest row edit, no delete); otherwise skipped
#  - project lock: the same per-project lock the package jobs take (pkg.lock); a project whose lock is held is skipped this run
#  - deletes only keys under bim cad-disk-extract/dataset/packages/3d/<pid>/ (refuses anything else; never conversions/, extracted/,
#    _state/ - except our own packaging records: ledger parts and the removals_done log)
#  - whole projects: delete every object under the prefix (delete_objects errors logged), confirm it is empty, ledger part rewritten
#    with no placements (pkg_delta then neither counts nor queues it; a model that returns to class 1 later is packaged again by a
#    normal create job)
#  - STEP rows: rewrite manifest.jsonl, patch project.json's manifest-derived fields (files, bytes, slots, formats, conversions,
#    pii), delete the object, pkg verify (non-shipped rows still present count as expected, not failures), ledger part minus the
#    removed / detached models (written whatever the verify result: it only drops entries)
#  - done record: _state/packaging/removals_done/<UTC date>.jsonl (per key; detaches logged with key '<manifest>#detach:<model>').
#    The queue file itself is NOT rewritten (pkg_delta appends to it every round; its count is recomputed from the ledger)
#  - outputs on the box: $O/report.<APPLY>.txt, $O/items.<APPLY>.json (every planned / skipped item), $O/log.<APPLY>.txt
#  - idempotent: the first call starts transient unit z3pkg-leftship (exits when done); later calls print progress / the report
APPLY=0
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; O=/opt/pkgleft_r1; K=/opt/z3c/kit/coord
mkdir -p $O
if [ -f $O/finished.$APPLY ]; then echo "finished $(cat $O/finished.$APPLY) (APPLY=$APPLY)"; cat $O/report.$APPLY.txt; exit 0; fi
if systemctl is-active -q z3pkg-leftship; then echo "running since $(cat $O/started.$APPLY 2>/dev/null)"; tail -n 8 $O/log.$APPLY.txt; exit 0; fi
grep -m1 -o "pkg-2026-10-02[a-z]" $K/pkgcore.py
cat > $O/run.py <<'PYEOF'
import os, sys, json, time, datetime, collections
sys.path.insert(0, '/opt/z3c/kit/coord')
APPLY = os.environ.get('APPLY') == '1'
os.environ['PKG_ALLOW_WRITE'] = '1' if APPLY else '0'
import pkgcore as pc, pkg
B = pc.BUCKET; ST = pc.PSTATE; BASE = f'{pc.DATASET}/{pc.ROUTE}/'
O = os.environ.get('PKGLEFT_O', '/opt/pkgleft')
DAY = time.strftime('%Y-%m-%d', time.gmtime()); LOGK = f'{ST}/removals_done/{DAY}.jsonl'
CONV_STATUS = 'cad-disk-extract/zenitude-data-3/_state/conv_status.json'
s3 = pc.s3c()
rep = []; log_rows = []; skip = []; items = []
agg = collections.defaultdict(lambda: [0, 0]); samples = collections.defaultdict(list)


def say(*a):
    m = ' '.join(str(x) for x in a); rep.append(m); print(m, flush=True)


def finish(code=0):
    write_log()
    sk = collections.Counter(r for _, _, r in skip)
    say(f'skipped {len(skip)} by reason: {dict(sk)}')
    say(f'skipped (first 30): {skip[:30]}')
    open(f'{O}/report.{int(APPLY)}.txt', 'w').write('\n'.join(rep) + '\n')
    json.dump({'apply': APPLY, 'at': pc.now(), 'items': items, 'skipped': skip}, open(f'{O}/items.{int(APPLY)}.json', 'w'), indent=1)
    sys.exit(code)


def safe(key, pid):
    return key.startswith(f'{BASE}{pid}/') and not any(x in key for x in ('/conversions/', '/extracted/', '/_state/'))


def write_log():
    if APPLY and log_rows:
        prev = pc.get_bytes(B, LOGK) or b''
        s3.put_object(Bucket=B, Key=LOGK, Body=prev + ''.join(json.dumps(r) + '\n' for r in log_rows).encode(), ContentType='application/x-ndjson')
        log_rows.clear()


# ---- guard: the re-runs must have drained (the owner's approval covers models still not class 1 AFTER the re-runs)
cs = pc.get_json(B, CONV_STATUS) or {}
eta = cs.get('eta') or {}
opn = {p: ((eta.get(p) or {}).get('open'), (eta.get(p) or {}).get('rerun_open')) for p in ('ifc', 'sds2', 'db1')}
try:
    age = time.time() - datetime.datetime.strptime(cs.get('updated', ''), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()
except ValueError:
    age = 1e9
drained = age < 1800 and all(o == 0 and r == 0 for o, r in opn.values())
say(f'APPLY={int(APPLY)} packager {pc.VERSION}; conv_status {cs.get("updated")} (age {age / 60:.0f} min) open/rerun_open {opn}; '
    f'verification_complete {cs.get("verification_complete")}; re-runs drained: {drained}')
if APPLY and not drained:
    say('REFUSED: IFC / SDS2 / DB1 re-runs not drained (or conv_status stale): nothing changed')
    finish(3)

queue = [json.loads(l) for l in (pc.get_bytes(B, f'{ST}/removals_pending.jsonl') or b'').decode().splitlines() if l.strip()]
done_keys = set()
for k, _, _ in pc.list_keys(B, f'{ST}/removals_done/'):
    for l in (pc.get_bytes(B, k) or b'').decode().splitlines():
        if l.strip():
            done_keys.add(json.loads(l).get('key'))
pm = (pc.get_json(B, pkg.PRIMARY_KEY) or {}).get('map') or {}
ad = pkg.load_adapter('zen3')
rows_now = ad.conv_rows()
byk = {r['model_key']: r for r in rows_now}
shipped, targets, _refs, _nots, _why, _unk = pkg.shipped_by_project(ad, rows_now, None, primary=pm)
shipped_ids = {r['id']: r['step_key'] for r in rows_now if pc.ship_decision(r)[0]}


def why_kept(mk):
    """None when the model qualifies (currently not class 1), else the reason it is kept"""
    r = byk.get(mk)
    if r is None:
        return 'model no longer in the index (not covered)'
    ok, reason = pc.ship_decision(r)
    if ok:
        p = (pm.get(mk) or {}).get('primary')
        return f'model shipped again (primary {p})' + (': dedup, not this approval' if p else '')
    if r.get('class') == 1 and r.get('grader_class') in (None, 1):
        return f'model is class 1, not shipped only for: {reason} (not covered)'
    return None


cats = collections.Counter(str(q.get('reason', ''))[:24] for q in queue)
want_p = sorted({q['project_id'] for q in queue if q.get('reason') == 'left_shipped_set_project'})
want_r = [q for q in queue if str(q.get('reason', '')).startswith('left shipped set') and q.get('model_key')]
say(f'queue entries {len(queue)} by reason prefix: {dict(cats)}')
say(f'in scope: left_shipped_set_project {len(want_p)}, left shipped set rows {len(want_r)}; keys already in the done logs {len(done_keys)}')


# ---- whole projects
def whole(pid):
    objs = [(k, sz) for k, sz, _ in pc.list_keys(B, f'{BASE}{pid}/') if k not in done_keys]
    bad = [k for k, _ in objs if not safe(k, pid)]
    if bad:
        skip.append((pid, None, f'unsafe keys {bad[:2]}')); return
    agg['left_shipped_set_project'][0] += len(objs); agg['left_shipped_set_project'][1] += sum(sz for _, sz in objs)
    if len(samples['left_shipped_set_project']) < 5 and objs:
        samples['left_shipped_set_project'].append(objs[0][0])
    items.append({'kind': 'project', 'project_id': pid, 'objects': len(objs), 'bytes': sum(sz for _, sz in objs), 'placed_classes': cls_of(pid)})
    whole_p.add(pid)
    if not APPLY:
        return
    errs = []
    keys = [k for k, _ in objs]
    for i in range(0, len(keys), 1000):
        r = s3.delete_objects(Bucket=B, Delete={'Objects': [{'Key': k} for k in keys[i:i + 1000]], 'Quiet': True})
        errs += r.get('Errors') or []
    if errs:
        say(f'ERRORS {pid}: {len(errs)} delete errors, e.g. {errs[:2]}')
    ebad = {e.get('Key') for e in errs}
    for k, sz in objs:
        if k not in ebad:
            log_rows.append({'key': k, 'bytes': sz, 'reason': 'left_shipped_set_project', 'project_id': pid, 'at': pc.now()})
    left = pc.list_keys(B, f'{BASE}{pid}/')
    if left:
        say(f'WARNING {pid}: {len(left)} objects still present after delete (ledger part not changed)')
    else:
        part = pc.get_json(B, f'{ST}/ledger_parts/{pid}.json') or {}
        pc.put_json(B, f'{ST}/ledger_parts/{pid}.json', dict(part, placements={}, removed={'reason': 'left_shipped_set_project',
                                                                                        'at': pc.now(), 'objects': len(objs)}))
    write_log()


whole_p, lock_p = set(), set()


def cls_of(pid):
    plc = (pc.get_json(B, f'{ST}/ledger_parts/{pid}.json') or {}).get('placements') or {}
    return dict(collections.Counter(f"class {(byk.get(mk) or {}).get('class')}" for mk in plc))


for pid in want_p:
    if pid in targets:
        skip.append((pid, None, 'project has a shipped model with this project as primary again')); continue
    plc = (pc.get_json(B, f'{ST}/ledger_parts/{pid}.json') or {}).get('placements') or {}
    if not plc:
        skip.append((pid, None, 'no placements in the ledger part (already removed, or check by hand)')); continue
    kept = {mk: why_kept(mk) for mk in plc}
    kept = {mk: w for mk, w in kept.items() if w}
    if kept:
        skip.append((pid, None, 'a placed model does not qualify: ' + sorted(kept.values())[0])); continue
    if APPLY and not pkg.lock(pid, 'pkg_left_shipped'):
        lock_p.add(pid); skip.append((pid, None, 'project lock held by a package job: next run')); continue
    try:
        whole(pid)
    finally:
        if APPLY: pkg.unlock(pid)

# ---- STEP rows in projects that stay packaged
by_pid = collections.defaultdict(dict)
for q in want_r:
    pid, mk = q['project_id'], q['model_key']
    if pid in whole_p or pid in lock_p:
        continue                                  # removed as a whole project above / its lock was held: next run
    w = why_kept(mk)
    if w:
        skip.append((pid, mk, w)); continue
    by_pid[pid][mk] = q

PJ_MAN_KEYS = ('slots', 'model_formats', 'drawing_formats', 'missing', 'files', 'bytes', 'conversions', 'model_step_by_source', 'pii')


def rows_of(pid, qs):
    base = f'{BASE}{pid}'
    man = pc.read_manifest(B, base)
    pj = pc.get_json(B, f'{base}/project.json') or {}
    if not man or not pj:
        skip.append((pid, None, 'manifest or project.json missing: rows left in place')); return
    elig = {}                                     # (step_source, model_id) -> model_key
    for mk in qs:
        _, src, mid = mk.split(':', 2) if mk.count(':') >= 2 else (None, None, mk)
        elig[(src, mid)] = mk
    drop, detach, found = [], [], set()
    for r in man:
        if r.get('modality') != 'step' or r.get('step_source') not in ('ifc', 'db1', 'sds2'):
            continue
        me = (r['step_source'], r.get('model_id'))
        also = [((a.get('step_source') or r['step_source']), a.get('model_id')) for a in r.get('also_models') or []]
        if me in elig:
            found.add(me)
            if all(x in elig for x in also):
                key = f"{base}/{r['relpath']}"
                if not safe(key, pid):
                    skip.append((pid, elig[me], f'unsafe key {key}')); continue
                if key in done_keys:
                    skip.append((pid, elig[me], 'key already in the done log')); continue
                drop.append(r); found.update(also)
            else:
                skip.append((pid, elig[me], 'shared STEP file also serves model(s) that do not qualify: not deleted'))
                found.update(x for x in also if x in elig)
                for x in also:
                    if x in elig:
                        skip.append((pid, elig[x], 'attached to a shared file whose own model is kept: left in place'))
        else:
            dx = [x for x in also if x in elig]
            if dx:
                detach.append((r, dx)); found.update(dx)
    for x, mk in elig.items():
        if x not in found:
            skip.append((pid, mk, 'row not in the manifest (already gone)'))
    if (drop or detach) and not any(r.get('modality') == 'step' and r.get('step_source') in ('ifc', 'db1', 'sds2') and not any(r is d for d in drop)
                                    for r in man):
        for mk in qs:
            skip.append((pid, mk, 'every shipped STEP row would go: whole-project case (wait for its left_shipped_set_project entry)'))
        return
    for r in drop:
        agg['left shipped set (row)'][0] += 1; agg['left shipped set (row)'][1] += r.get('bytes') or 0
        if len(samples['left shipped set (row)']) < 5:
            samples['left shipped set (row)'].append(f"{base}/{r['relpath']}")
        items.append({'kind': 'row', 'project_id': pid, 'relpath': r['relpath'], 'model_id': r.get('model_id'), 'bytes': r.get('bytes'),
                      'also_model_ids': r.get('also_model_ids') or [],
                      'class': (byk.get(f"{pj.get('disk')}:{r['step_source']}:{r.get('model_id')}") or {}).get('class')})
    for r, dx in detach:
        agg['left shipped set (detach only)'][0] += len(dx)
        items.append({'kind': 'detach', 'project_id': pid, 'relpath': r['relpath'], 'kept_model_id': r.get('model_id'), 'detach': [m for _, m in dx]})
    if not APPLY or not (drop or detach):
        return
    new_man = []
    for r in man:
        if any(r is d for d in drop):
            continue
        dx = next((d for rr, d in detach if rr is r), None)
        if dx:
            r = dict(r); gone = {m for _, m in dx}
            r['also_models'] = [a for a in r.get('also_models') or [] if a.get('model_id') not in gone]
            if r['also_models']:
                r['also_converted_from'] = sorted({a['converted_from'] for a in r['also_models'] if a.get('converted_from')})
                r['also_model_ids'] = [a['model_id'] for a in r['also_models']]
            else:
                for f_ in ('also_models', 'also_converted_from', 'also_model_ids'):
                    r.pop(f_, None)
        new_man.append(r)
    fake_plan = {'project_id': pid, 'source': pj.get('source'), 'excluded_non_asset_files': pj.get('excluded_non_asset_files'),
                 'duplicates_collapsed': pj.get('duplicates_collapsed'), 'disk': pj.get('disk'), 'source_archive': pj.get('source_archive'),
                 'steps_not_shipped': [], 'native_steps_not_graded': [], 'unresolved_files': []}
    fresh = pc.project_json(fake_plan, new_man)
    new_pj = dict(pj, **{k: fresh[k] for k in PJ_MAN_KEYS})
    body = ('\n'.join(json.dumps(r, ensure_ascii=False) for r in new_man) + '\n').encode('utf-8', 'surrogateescape')
    s3.put_object(Bucket=B, Key=f'{base}/manifest.jsonl', Body=body, ContentType='application/x-ndjson')
    s3.put_object(Bucket=B, Key=f'{base}/project.json', Body=json.dumps(new_pj, indent=1, ensure_ascii=False).encode(), ContentType='application/json')
    for r in drop:
        s3.delete_object(Bucket=B, Key=f"{base}/{r['relpath']}")
        log_rows.append({'key': f"{base}/{r['relpath']}", 'bytes': r.get('bytes'), 'reason': 'left shipped set', 'project_id': pid,
                         'model_id': r.get('model_id'), 'also_model_ids': r.get('also_model_ids') or [], 'at': pc.now()})
    for r, dx in detach:
        for _, m in dx:
            log_rows.append({'key': f"{base}/manifest.jsonl#detach:{m}", 'bytes': 0, 'reason': 'left shipped set (detach)', 'project_id': pid,
                             'model_id': m, 'file_kept': r['relpath'], 'at': pc.now()})
    keys = dict(shipped_ids)
    for r in new_man:                            # rows still present that are not shipped (skipped / other queues): expected
        if r.get('modality') == 'step' and r.get('model_id') and r['model_id'] not in keys:
            keys[r['model_id']] = r.get('step_key')
        for a in r.get('also_models') or []:
            if a.get('model_id') and a['model_id'] not in keys:
                keys[a['model_id']] = a.get('step_key') or r.get('step_key')
    ver = pc.verify_project(B, pid, keys)
    say(f'verify {pid[:90]}: ok={ver["ok"]} checks={ver["checks"]}')
    gone_mk = set()
    for r in drop:
        gone_mk.add(f"{pj.get('disk')}:{r['step_source']}:{r['model_id']}")
        for a in r.get('also_models') or []:
            gone_mk.add(f"{pj.get('disk')}:{a.get('step_source') or r['step_source']}:{a['model_id']}")
    for r, dx in detach:
        gone_mk.update(f"{pj.get('disk')}:{s}:{m}" for s, m in dx)
    part = pc.get_json(B, f'{ST}/ledger_parts/{pid}.json') or {}
    if part.get('placements') is not None:
        part['placements'] = {k: v for k, v in part['placements'].items() if k not in gone_mk}
        part['updated'] = pc.now(); part['left_shipped_removed'] = sorted(gone_mk)
        pc.put_json(B, f'{ST}/ledger_parts/{pid}.json', part)
    write_log()


for pid, qs in sorted(by_pid.items()):
    if APPLY and not pkg.lock(pid, 'pkg_left_shipped'):
        for mk in qs:
            skip.append((pid, mk, 'project lock held by a package job: next run'))
        continue
    try:
        rows_of(pid, qs)
    finally:
        if APPLY: pkg.unlock(pid)
for reason, (n, b) in agg.items():
    say(f'{reason}: items {n}, GB {b / 1e9:.2f}; samples: {samples[reason][:5]}')
finish(0)
PYEOF
date -u +%FT%TZ > $O/started.$APPLY
systemctl reset-failed z3pkg-leftship 2>/dev/null
systemd-run --unit=z3pkg-leftship --collect --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=APPLY=$APPLY --setenv=PKGLEFT_O=$O /bin/bash -c \
  "$PY $O/run.py > $O/log.$APPLY.txt 2>&1; rc=\$?; echo rc=\$rc >> $O/log.$APPLY.txt; if [ \$rc = 3 ]; then mv $O/report.$APPLY.txt $O/refused.$APPLY.txt; else date -u +%FT%TZ > $O/finished.$APPLY; fi"
sleep 60
if [ -f $O/finished.$APPLY ]; then cat $O/report.$APPLY.txt 2>/dev/null || tail -n 30 $O/log.$APPLY.txt
elif [ $O/refused.$APPLY.txt -nt $O/started.$APPLY ]; then cat $O/refused.$APPLY.txt   # refused: no finished marker, so a later call re-checks
else echo "running"; tail -n 8 $O/log.$APPLY.txt; fi
