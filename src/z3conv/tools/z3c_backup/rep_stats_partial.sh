#!/bin/bash
# READ-ONLY report statistics over every delivered package (bim cad-disk-extract/dataset/packages/3d/<project>/{project.json,manifest.jsonl}).
# Distinct files = distinct sha256 across the whole pack (two copies of the same bytes count once), per channel and per disk.
# Output on the box: /opt/report/out/stats_<RUN>.json (+ per-project table, samples). Idempotent: first call starts unit z3repstats-<RUN>.
export AWS_DEFAULT_REGION=ap-south-1
RUN=${RUN:-p1}; D=/opt/report; O=$D/out
if systemctl is-active -q z3repstats-$RUN; then echo "running since $(cat $O/stats_$RUN.started)"; tail -n 3 $O/stats_$RUN.log; exit 0; fi
if [ -f $O/stats_$RUN.json ]; then echo "finished"; tail -n 4 $O/stats_$RUN.log; exit 0; fi
cat > $D/rep_stats.py <<'PYEOF'
import os, sys, json, collections, random, time
from multiprocessing import Pool
import boto3
from botocore.config import Config
B = 'bim-proprietary-data'; P = 'cad-disk-extract/dataset/packages/3d_partial/'
RUN = sys.argv[1]; O = '/opt/report/out'
D1 = set(json.load(open('/opt/report/z4_disk12_duplicates.json'))); D2 = set(json.load(open('/opt/report/disk2_in_z3.json'))['z3_in_d2'])
s3 = None
def init():
    global s3
    s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=8, retries={'max_attempts': 10, 'mode': 'standard'}))
def chan(rel):
    p = rel.split('/')
    return '/'.join(p[:2]) if len(p) > 2 else p[0]
def one(pid):
    for a in range(5):
        try:
            pj = json.loads(s3.get_object(Bucket=B, Key=f'{P}{pid}/project.json')['Body'].read())
            man = s3.get_object(Bucket=B, Key=f'{P}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
            break
        except Exception as e:
            err = e; time.sleep(3 * (a + 1))
    else:
        return pid, None, None
    rows = []; steps = []
    for l in man.split('\n'):
        if not l.strip(): continue
        r = json.loads(l)
        ch = chan(r['relpath'])
        rows.append((ch, r.get('modality'), r.get('role'), r.get('sha256'), int(r.get('bytes') or 0), r['relpath']))
        if ch == 'model/step':
            steps.append({'relpath': r['relpath'], 'step_source': r.get('step_source'), 'model_id': r.get('model_id'), 'class': r.get('class'),
                          'converter': r.get('converter'), 'bytes': r.get('bytes'), 'also': len(r.get('also_models') or []), 'converted_from': r.get('converted_from'),
                          'partial_kind': (r.get('partial') or {}).get('kind'), 'converted_from_package': r.get('converted_from_package')})
    src = (pj.get('source_archive') or pj.get('source') or '')
    summ = {k: pj.get(k) for k in ('id', 'disk', 'year', 'files', 'bytes', 'status', 'source_archive', 'source_kind', 'model_formats', 'drawing_formats',
                                   'model_step_by_source', 'missing', 'excluded_non_asset_files', 'duplicates_collapsed', 'unresolved_files_count', 'steps_not_shipped_count')}
    rel = src.split('/', 1)[1] if '/' in src else src
    summ['disk1_archive'] = rel in D1; summ['disk2_archive'] = rel in D2
    summ['steps'] = steps
    summ.update(addon_of=pj.get('addon_of'), tier=pj.get('tier'), partial_steps=pj.get('partial_steps'), warnings=[w for w in (pj.get('warnings') or []) if 'SDS2 job zip' in w])
    return pid, summ, rows
if __name__ == '__main__':
    init(); pids = []
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P, Delimiter='/'):
        pids += [c['Prefix'][len(P):-1] for c in pg.get('CommonPrefixes') or []]
    print('projects', len(pids), flush=True)
    raw = collections.Counter(); rawb = collections.Counter()                       # (disk, channel) raw rows / bytes
    seen = {}                                                                      # sha -> (channel, bytes) first seen
    seen_disk = collections.defaultdict(dict)                                     # disk -> sha -> (channel, bytes)
    mod = collections.Counter(); role = collections.Counter()
    projects = []; cov = collections.Counter(); covd = collections.Counter(); combos = collections.Counter()
    samples = collections.defaultdict(list); nseen = collections.Counter()
    rnd = random.Random(20261005)
    t0 = time.time()
    with Pool(32, initializer=init) as pool:
        for i, (pid, summ, rows) in enumerate(pool.imap_unordered(one, pids, chunksize=1), 1):
            if summ is None: print('UNREADABLE', pid, flush=True); continue
            disk = 'data-3' if pid.startswith('Zenitude-data-3') else ('data-4' if pid.startswith('Zentitude-data-4') else 'other')
            per = collections.Counter(); perb = collections.Counter()
            sa = (summ.get('source_archive') or '').split('/')
            fold = '/'.join(sa[1:2]) if disk == 'data-3' else '/'.join(sa[1:3])
            pseudo = ([('disk-1' if summ['disk1_archive'] else 'data-4-only')] if disk == 'data-4' else [('disk-2' if summ['disk2_archive'] else 'data-3-only')] if disk == 'data-3' else []) + [f'src|{disk}|{fold}']
            summ['origin'] = pseudo[0] if pseudo else None; summ['src_folder'] = fold
            for ch, m, ro, sha, b, rp in rows:
                raw[(disk, ch)] += 1; rawb[(disk, ch)] += b; per[ch] += 1; perb[ch] += b
                mod[(ch, m)] += 1; role[(ch, ro)] += 1
                if sha:
                    seen.setdefault(sha, (ch, b)); seen_disk[disk].setdefault(sha, (ch, b))
                    for pd in pseudo: seen_disk[pd].setdefault(sha, (ch, b))
                    if ch in ('drawings/pdf', 'drawings/dxf', 'fab/nc1', 'drawings/dwg', 'model/ifc', 'model/step', 'drawings/dg', 'drawings/dpm'):
                        # reservoir sample (uniform over every row of the channel on that disk), k = 3000
                        key = (disk, ch); nseen[key] += 1; res_ = samples[f'{disk}|{ch}']
                        if len(res_) < 3000: res_.append((pid, sha, b, rp))
                        else:
                            j = rnd.randrange(nseen[key])
                            if j < 3000: res_[j] = (pid, sha, b, rp)
            chs = set(per)
            for ch in chs:
                cov[ch] += 1; covd[(disk, ch)] += 1
                for pd in pseudo: covd[(pd, ch)] += 1
            has = lambda pre: any(c.startswith(pre) for c in chs)
            combos[('drawings', has('drawings/'))] += 1
            combos[('pdf+nc1+tables', 'drawings/pdf' in chs and 'fab/nc1' in chs and has('tables/'))] += 1
            combos[('any_drawing+nc1+join_table', has('drawings/') and 'fab/nc1' in chs and ('tables/bom' in chs or 'tables/kiss' in chs))] += 1
            summ.update(disk=disk, per_channel=dict(per), per_channel_bytes=dict(perb), n_rows=len(rows))
            projects.append(summ)
            if i % 50 == 0: print(i, 'projects', len(seen), 'distinct files', round(time.time() - t0), 's', flush=True)
    dist = collections.Counter(); distb = collections.Counter()
    for sha, (ch, b) in seen.items(): dist[ch] += 1; distb[ch] += b
    distd = {}
    for disk, m in seen_disk.items():
        c = collections.Counter(); cb = collections.Counter()
        for sha, (ch, b) in m.items(): c[ch] += 1; cb[ch] += b
        distd[disk] = {'files': dict(c), 'bytes': dict(cb)}
    out = {'run': RUN, 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'projects': len(projects),
           'distinct': {'files': dict(dist), 'bytes': dict(distb), 'total_files': sum(dist.values()), 'total_bytes': sum(distb.values())},
           'distinct_by_disk': distd,
           'raw_by_disk_channel': {f'{d}|{c}': [raw[(d, c)], rawb[(d, c)]] for (d, c) in raw},
           'modality': {f'{c}|{m}': n for (c, m), n in mod.items()}, 'role': {f'{c}|{r}': n for (c, r), n in role.items()},
           'coverage': dict(cov), 'coverage_by_disk': {f'{d}|{c}': n for (d, c), n in covd.items()},
           'combos': {f'{k}|{v}': n for (k, v), n in combos.items()},
           'tier': 'partial',
           'partial_kinds': dict(collections.Counter((p['disk'], s_.get('partial_kind')) for p in projects for s_ in p['steps']).most_common()) and
               {f'{d}|{k}': n for (d, k), n in collections.Counter((p['disk'], s_.get('partial_kind')) for p in projects for s_ in p['steps']).items()},
           'models_represented': {d: sum(1 + (s_.get('also') or 0) for p in projects if p['disk'] == d for s_ in p['steps']) for d in ('data-3', 'data-4')},
           'step_rows': {d: sum(len(p['steps']) for p in projects if p['disk'] == d) for d in ('data-3', 'data-4')},
           'addon_projects': {d: sum(1 for p in projects if p['disk'] == d and p.get('addon_of')) for d in ('data-3', 'data-4')},
           'standalone_projects': {d: sum(1 for p in projects if p['disk'] == d and not p.get('addon_of')) for d in ('data-3', 'data-4')},
           'projects_with_incomplete_sds2_zip': sum(1 for p in projects if p.get('warnings'))}
    json.dump(out, open(f'{O}/stats_{RUN}.json', 'w'), indent=1)
    json.dump(projects, open(f'{O}/projects_{RUN}.json', 'w'))
    json.dump(dict(samples), open(f'{O}/samples_{RUN}.json', 'w'))
    print('DONE projects', len(projects), 'distinct files', out['distinct']['total_files'], 'GB', round(out['distinct']['total_bytes'] / 1e9, 1), flush=True)
PYEOF
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/coord_tmp/z4_disk12_duplicates.json $D/z4_disk12_duplicates.json 2>/dev/null
test -s /opt/report/disk2_in_z3.json || { echo 'missing disk2_in_z3.json'; exit 1; }
test -s $D/z4_disk12_duplicates.json || { echo "missing z4_disk12_duplicates.json"; exit 1; }
date -u +%FT%TZ > $O/stats_$RUN.started
systemctl reset-failed z3repstats-$RUN 2>/dev/null
systemd-run --unit=z3repstats-$RUN --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_stats.py $RUN > $O/stats_$RUN.log 2>&1; echo rc=\$? >> $O/stats_$RUN.log"
sleep 45; echo "started: $(systemctl is-active z3repstats-$RUN)"; tail -n 3 $O/stats_$RUN.log
