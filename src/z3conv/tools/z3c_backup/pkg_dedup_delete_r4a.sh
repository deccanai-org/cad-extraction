#!/bin/bash
# Packaging dedup removals (owner-approved 00:40Z): the dedup_non_primary_project packages and the dedup_non_primary STEP rows of
# projects that stay packaged. DRY RUN unless APPLY=1 below (the lead flips it after reviewing the dry-run output).
# Run on the coordinator box via: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/pkg_dedup_delete.sh 900
#  - input: _state/packaging/removals_pending.jsonl entries with reason dedup_non_primary_project / dedup_non_primary (...) only;
#    'left shipped set' entries are NOT touched (owner: later); entries already in the removals_done log are skipped
#  - re-check against the current primary map (_state/packaging/cache/primary_map.json): a project that is now some model's primary,
#    or a model whose primary is now this project, is skipped and logged
#  - project lock: the same per-project lock the package jobs take (pkg.lock); a project whose lock is held is skipped this run
#  - deletes only keys under bim cad-disk-extract/dataset/packages/3d/<pid>/ (refuses anything else; never conversions/, extracted/,
#    _state/ - except our own packaging records: ledger parts and the removal log)
#  - whole projects: delete every object under the prefix (delete_objects errors logged), confirm it is empty, ledger part rewritten
#    with no placements (pkg_delta then no longer counts or queues the project)
#  - STEP rows: delete the object, rewrite manifest.jsonl + project.json without the row (pkgcore.project_json from the project's
#    latest create plan: files, bytes, slots, step counts), pkg verify (all checks 0), ledger part without the model
#  - done record: _state/packaging/removals_done/2026-10-03.jsonl (per key). The queue file itself is NOT rewritten (pkg_delta appends
#    to it every round); its removals count is recomputed from the ledger each round, so done items drop out of it
#  - idempotent: the first call starts systemd unit z3pkg-dedupdel; later calls of the same command print its progress / report
APPLY=1
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; O=/opt/pkgdel_r4; K=/opt/z3c/kit/coord      # run 4 (2026-10-04): dedup demotions after run 3 (e.g. Technical Library 610 Walnut)
mkdir -p $O
if [ -f $O/finished.$APPLY ]; then echo "finished $(cat $O/finished.$APPLY) (APPLY=$APPLY)"; cat $O/report.$APPLY.txt; exit 0; fi
if systemctl is-active -q z3pkg-dedupdel; then echo "running since $(cat $O/started.$APPLY 2>/dev/null)"; tail -n 8 $O/log.$APPLY.txt; exit 0; fi
grep -m1 -o "pkg-2026-10-02[a-z]" $K/pkgcore.py
cat > $O/run.py <<'PYEOF'
import os, sys, json, collections
sys.path.insert(0, '/opt/z3c/kit/coord')
APPLY = os.environ.get('APPLY') == '1'
os.environ['PKG_ALLOW_WRITE'] = '1' if APPLY else '0'
import pkgcore as pc, pkg
B = pc.BUCKET; ST = pc.PSTATE; BASE = f'{pc.DATASET}/{pc.ROUTE}/'
DAY = '2026-10-03'; LOGK = f'{ST}/removals_done/{DAY}.jsonl'
s3 = pc.s3c()
rep = []; log_rows = []; skip = []
agg = collections.defaultdict(lambda: [0, 0]); samples = collections.defaultdict(list)


def say(*a):
    m = ' '.join(str(x) for x in a); rep.append(m); print(m, flush=True)


def safe(key, pid):
    return key.startswith(f'{BASE}{pid}/') and not any(x in key for x in ('/conversions/', '/extracted/', '/_state/'))


def write_log():
    if APPLY and log_rows:
        prev = pc.get_bytes(B, LOGK) or b''
        s3.put_object(Bucket=B, Key=LOGK, Body=prev + ''.join(json.dumps(r) + '\n' for r in log_rows).encode(), ContentType='application/x-ndjson')
        log_rows.clear()


queue = [json.loads(l) for l in (pc.get_bytes(B, f'{ST}/removals_pending.jsonl') or b'').decode().splitlines() if l.strip()]
done_keys = {json.loads(l)['key'] for l in (pc.get_bytes(B, LOGK) or b'').decode().splitlines() if l.strip()}
pm = (pc.get_json(B, pkg.PRIMARY_KEY) or {}).get('map') or {}
primaries = {e['primary'] for e in pm.values()}
want = [q for q in queue if str(q.get('reason', '')).startswith('dedup_non_primary')]
projects = sorted({q['project_id'] for q in want if q.get('reason') == 'dedup_non_primary_project'})
rows = [q for q in want if q.get('reason', '').startswith('dedup_non_primary (') and q['project_id'] not in projects]
say(f'APPLY={int(APPLY)} queue entries: dedup_non_primary_project {len(projects)}, dedup_non_primary rows outside them {len(rows)}; '
    f'keys already in the done log {len(done_keys)}')


def whole(pid):
    objs = [(k, sz) for k, sz, _ in pc.list_keys(B, f'{BASE}{pid}/') if k not in done_keys]
    bad = [k for k, _ in objs if not safe(k, pid)]
    if bad:
        skip.append((pid, None, f'unsafe keys {bad[:2]}')); return
    agg['dedup_non_primary_project'][0] += len(objs); agg['dedup_non_primary_project'][1] += sum(sz for _, sz in objs)
    if len(samples['dedup_non_primary_project']) < 5 and objs:
        samples['dedup_non_primary_project'].append(objs[0][0])
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
            log_rows.append({'key': k, 'bytes': sz, 'reason': 'dedup_non_primary_project', 'project_id': pid, 'at': pc.now()})
    left = pc.list_keys(B, f'{BASE}{pid}/')
    if left:
        say(f'WARNING {pid}: {len(left)} objects still present after delete (ledger part not changed)')
    else:
        part = pc.get_json(B, f'{ST}/ledger_parts/{pid}.json') or {}
        pc.put_json(B, f'{ST}/ledger_parts/{pid}.json', dict(part, placements={}, removed={'reason': 'dedup_non_primary_project',
                                                                                        'at': pc.now(), 'objects': len(objs)}))
    write_log()


for pid in projects:
    if pid in primaries:
        skip.append((pid, None, 'project is now a primary project')); continue
    # (lead 01:35Z) dedup only: at least one model placed in the project must be shipped with its primary elsewhere; a project whose
    # models only left the shipped set is not covered by the owner's approval (left_shipped_set) and is skipped
    plc = (pc.get_json(B, f'{ST}/ledger_parts/{pid}.json') or {}).get('placements') or {}
    if plc and not any((pm.get(mk) or {}).get('primary') not in (None, pid) for mk in plc):
        skip.append((pid, None, 'models only left the shipped set (not dedup): not deleted')); continue
    if APPLY and not pkg.lock(pid, 'pkg_dedup_delete'):
        skip.append((pid, None, 'project lock held by a package job: next run')); continue
    try:
        whole(pid)
    finally:
        if APPLY: pkg.unlock(pid)

# ---- STEP rows in projects that stay packaged
by_pid = collections.defaultdict(list)
for q in rows:
    if (pm.get(q['model_key']) or {}).get('primary') == q['project_id']:
        skip.append((q['project_id'], q['model_key'], 'model primary is now this project')); continue
    if q['model_key'] not in pm:
        skip.append((q['project_id'], q['model_key'], 'model left the shipped set (not dedup): not deleted')); continue
    by_pid[q['project_id']].append(q)
ad = pkg.load_adapter('zen3')
shipped_keys = {r['id']: r['step_key'] for r in ad.conv_rows() if pc.ship_decision(r)[0]}


def rows_of(pid, qs):
    base = f'{BASE}{pid}'
    man = pc.read_manifest(B, base)
    mids = {q['model_key'].rsplit(':', 1)[-1]: q for q in qs}
    drop = [r for r in man if r.get('modality') == 'step' and r.get('model_id') in mids and r.get('step_source') in ('ifc', 'db1', 'sds2')
            and safe(f"{base}/{r['relpath']}", pid) and f"{base}/{r['relpath']}" not in done_keys]
    for mid, q in mids.items():
        if not any(r.get('model_id') == mid for r in drop):
            skip.append((pid, q['model_key'], 'row not in the manifest (already gone)'))
    for r in drop:
        agg['dedup_non_primary'][0] += 1; agg['dedup_non_primary'][1] += r.get('bytes') or 0
        if len(samples['dedup_non_primary']) < 5:
            samples['dedup_non_primary'].append(f"{base}/{r['relpath']}")
    if not APPLY or not drop:
        return
    new_man = [r for r in man if r not in drop]
    plans = sorted(pc.list_keys(B, f'{ST}/plans/{pid}/'), key=lambda x: x[0])
    plan = None
    for k, _, _ in reversed(plans):
        p_ = pc.get_json(B, k)
        if p_ and p_.get('mode') == 'create':
            plan = p_; break
    if plan is None:
        skip.append((pid, None, 'no create plan found: rows left in place')); return
    body = ('\n'.join(json.dumps(r, ensure_ascii=False) for r in new_man) + '\n').encode('utf-8', 'surrogateescape')
    s3.put_object(Bucket=B, Key=f'{base}/manifest.jsonl', Body=body, ContentType='application/x-ndjson')
    s3.put_object(Bucket=B, Key=f'{base}/project.json', Body=json.dumps(pc.project_json(plan, new_man), indent=1, ensure_ascii=False).encode(),
                  ContentType='application/json')
    for r in drop:
        s3.delete_object(Bucket=B, Key=f"{base}/{r['relpath']}")
        log_rows.append({'key': f"{base}/{r['relpath']}", 'bytes': r.get('bytes'), 'reason': 'dedup_non_primary', 'project_id': pid,
                         'model_id': r.get('model_id'), 'at': pc.now()})
    keys = dict(shipped_keys)
    for r in new_man:                           # rows queued for the owner (e.g. 'left shipped set'): still present, not a failure
        if r.get('modality') == 'step' and r.get('model_id') and r['model_id'] not in keys:
            keys[r['model_id']] = r.get('step_key')
    ver = pc.verify_project(B, pid, keys)
    say(f'verify {pid[:90]}: ok={ver["ok"]} checks={ver["checks"]}')
    if ver['ok']:
        pc.put_json(B, f'{ST}/ledger_parts/{pid}.json', pc.ledger_part(plan, new_man, ver))
    write_log()


for pid, qs in sorted(by_pid.items()):
    if APPLY and not pkg.lock(pid, 'pkg_dedup_delete'):
        skip.append((pid, None, 'project lock held by a package job: next run')); continue
    try:
        rows_of(pid, qs)
    finally:
        if APPLY: pkg.unlock(pid)
for reason, (n, b) in agg.items():
    say(f'{reason}: objects {n}, GB {b / 1e9:.2f}; samples: {samples[reason][:5]}')
say(f'skipped {len(skip)}: {skip[:30]}')
write_log()
open(f"{os.environ.get('PKGDEL_O', '/opt/pkgdel')}/report.{int(APPLY)}.txt", 'w').write('\n'.join(rep) + '\n')
PYEOF
date -u +%FT%TZ > $O/started.$APPLY
systemctl reset-failed z3pkg-dedupdel 2>/dev/null
systemd-run --unit=z3pkg-dedupdel --collect --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=APPLY=$APPLY --setenv=PKGDEL_O=$O /bin/bash -c \
  "$PY $O/run.py > $O/log.$APPLY.txt 2>&1; echo rc=\$? >> $O/log.$APPLY.txt; date -u +%FT%TZ > $O/finished.$APPLY"
sleep 60
if [ -f $O/finished.$APPLY ]; then cat $O/report.$APPLY.txt 2>/dev/null || tail -n 30 $O/log.$APPLY.txt; else echo "running"; tail -n 8 $O/log.$APPLY.txt; fi
