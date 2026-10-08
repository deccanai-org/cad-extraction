#!/bin/bash
# Place the 54 data-4 package files whose copy failed with NoSuchKey (extraction key missing) now that their bytes are recovered from the
# source archives (/opt/pkgrec5/map_rows.jsonl: bim cad-disk-extract/zentitude-data-4/recovered/<sha256>, S3 SHA-256 = manifest sha).
# Per project, the packager's own path: project lock -> latest plan as the base, items = only those planned files (src_key = recovered
# object) -> pkgcore.apply_plan (copy + S3 SHA-256 check, manifest merge, project.json) -> verify_project -> ledger part when ok.
# Idempotent: a file already in the manifest is skipped. First call starts unit z3placensk; later calls print the report.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgplace; mkdir -p $D
if systemctl is-active -q z3placensk; then echo "running since $(cat $D/started)"; tail -n 3 $D/log.txt; exit 0; fi
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; tail -n 25 $D/log.txt | cut -c1-300; exit 0; fi
cat > $D/run.py <<'PYEOF'
import os, sys, json, gzip, copy, collections
sys.path.insert(0, '/opt/pkgd4r2/kit'); os.environ['PKG_ALLOW_WRITE'] = '1'
import pkg, pkgcore as pc
B = pc.BUCKET
items = json.load(open('/opt/pkgd4r4/nosuchkey_items.json'))
rec = {json.loads(l)['sha256']: json.loads(l) for l in open('/opt/pkgrec5/map_rows.jsonl')}
byp = collections.defaultdict(list)
for x in items: byp[x['project_id']].append(x)
ad = pkg.load_adapter('zen4')
shipped = pkg.shipped_by_project(ad, ad.conv_rows())[0]
keys = {r['id']: r['step_key'] for r in shipped.values()}
tot = collections.Counter()
for pid, xs in sorted(byp.items()):
    base = f'{pc.DATASET}/{pc.ROUTE}/{pid}'
    if not pkg.lock(pid, 'pkg_place_nosuchkey'):
        print('LOCKED (skip, re-run later)', pid, flush=True); tot['locked'] += 1; continue
    try:
        have = {r['relpath'] for r in pc.read_manifest(B, base)}
        todo = [x for x in xs if x['relpath'] not in have]
        if not todo:
            print('already placed', pid, flush=True); tot['already'] += len(xs); continue
        plans = sorted(pc.list_keys(B, f'{pc.PSTATE}/plans/{pid}/'), key=lambda k: k[0])
        docs = []
        for k, _, _ in plans:
            p = pc.get_json(B, k)
            if p: docs.append((k, p))
        latest = max(docs, key=lambda kp: kp[1].get('created') or kp[1].get('at') or kp[0])[1] if docs else None
        # the planned item (relpath, channel, role, source_path ...) from the newest plan that has it
        found = {}
        for k, p in reversed(docs):
            for it in p.get('items') or []:
                if it.get('relpath') in {x['relpath'] for x in todo} and it['relpath'] not in found:
                    found[it['relpath']] = it
        sel = []
        for x in todo:
            it = found.get(x['relpath']); r = rec.get(x['sha256'])
            if not it or not r or int(r['bytes']) != int(it['bytes']) or it.get('sha256') != x['sha256']:
                print('  no plan item / recovered row for', x['relpath'], flush=True); tot['missing_input'] += 1; continue
            it = dict(it, src_bucket=B, src_key=r['key'], src_how='recovered_from_source_archive')
            sel.append(it)
        if not sel: continue
        plan = copy.deepcopy(latest)
        plan.update(mode='update', steps=[], sds2_zips=[], step_attach=[], items=sel)
        r_ = pc.apply_plan(plan, workdir=f'/opt/pkgplace/work/{abs(hash(pid))}')
        man = pc.read_manifest(B, base)
        ver = pc.verify_project(B, pid, dict(keys, **{r['model_id']: r.get('step_key') for r in man
                                                      if r.get('modality') == 'step' and r.get('model_id') and r['model_id'] not in keys}))
        if ver['ok'] and r_.get('status') in ('ok', 'partial'):
            pc.put_json(B, f'{pc.PSTATE}/ledger_parts/{pid}.json', pc.ledger_part(plan, man, ver))
        tot['copied'] += r_.get('copied') or 0; tot['failed'] += len(r_.get('failed') or [])
        tot['verify_ok' if ver['ok'] else 'verify_fail'] += 1
        print(pid[:100], 'copied', r_.get('copied'), 'failed', r_.get('failed'), 'verify', ver['ok'], ver.get('checks'), flush=True)
    finally:
        pkg.unlock(pid)
print('TOTAL', dict(tot), flush=True)
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3placensk 2>/dev/null
systemd-run --unit=z3placensk --collect --working-directory=/opt/pkgd4r2/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_ALLOW_WRITE=1 /bin/bash -c \
  "/opt/conv/env/bin/python $D/run.py > $D/log.txt 2>&1; echo rc=\$? >> $D/log.txt; date -u +%FT%TZ > $D/finished"
sleep 45; echo "started: $(systemctl is-active z3placensk)"; tail -n 5 $D/log.txt | cut -c1-300
