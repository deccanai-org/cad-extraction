#!/bin/bash
# READ-ONLY: the giant jobs (expected memory >= 150 GB) of data-3 and data-4 - why their expectation is that high (own measured peak,
# memory-kill deferral, bucket estimate, control override) and their measured peaks. Only S3 GET / LIST; writes nothing.
# Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/giants.sh 200
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, collections
import boto3
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; CB = 'annotationprod'
def gj(k, b=B):
    try: return json.loads(s3.get_object(Bucket=b, Key=k)['Body'].read())
    except Exception: return None
def lst(p):
    out = []
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=p):
        out += pg.get('Contents', [])
    return out
mo = gj('cad-disk-extract/_control/z3conv/coord/mem_overrides.json', CB) or {}
print('control mem_overrides:', mo)
for tag, st in (('data-3', 'cad-disk-extract/zenitude-data-3/_state/conv'),):
    for p in ('sds2',):
        tb = gj(f'cad-disk-extract/zenitude-data-3/_state/conv/{p}/mem_buckets.json') or {}
        pk = tb.get('peak_by_id') or {}
        jobs = {j['id']: j for j in (gj(f'{st}/{p}/jobs.json') or []) + (gj(f'{st}/{p}/jobs_reconvert.json') or []) if isinstance(j, dict)}
        res = {o['Key'].rsplit('/', 1)[-1][:-5] for o in lst(f'{st}/{p}/results/')}
        dfr = {o['Key'].rsplit('/', 1)[-1][:-5]: o for o in lst(f'{st}/{p}/deferred/')}
        big = []
        for jid, j in jobs.items():
            d = gj(dfr[jid]['Key']) if jid in dfr else None
            mm = (d or {}).get('min_mem_bytes') or 0
            own = pk.get(jid)
            if mm >= 150 << 30 or (own and float(own) >= 150):
                big.append((jid, j.get('size') or j.get('model_bytes'), own, mm, (d or {}).get('kills_by_code'), (d or {}).get('runtime'),
                            (d or {}).get('hold_code'), jid in res))
        print(f'== {tag} {p}: jobs {len(jobs)}, giant (deferral min_mem >= 150 GB or own measured peak >= 150 GB): {len(big)}')
        wo = [x for x in big if not x[2]]
        print(f'   with own measured peak: {len(big) - len(wo)} (max {max([float(x[2]) for x in big if x[2]] or [0])} GB); without: {len(wo)}; '
              f'legacy deferral (runtime != v2): {sum(1 for x in big if x[5] != "z3-convfleet-v2")}')
        for jid, sz, own, mm, kb, rt, hc, has_res in wo[:12]:
            r = gj(f'{st}/{p}/results/{jid}.json') or {}
            print(f'   NO-PEAK {jid[:16]} size {round((sz or 0) / 2**20)} MB deferral {round(mm / 2**30)} GB result {r.get("status")}/{r.get("reason")} code {r.get("code")} '
                  f'peak_rss_in_result {r.get("peak_rss_gb") or r.get("peak_rss") or (r.get("stats") or {}).get("peak_rss_gb")}')
        opn = set(gj(f'{st}/{p}/redo.json') or []) | {j['id'] for j in (gj(f'{st}/{p}/jobs_reconvert.json') or []) if isinstance(j, dict)}
        opn -= set()
        hist = collections.Counter()
        for jid in opn:
            v = float(pk.get(jid) or 0)
            hist['>=250' if v >= 250 else '200-250' if v >= 200 else '150-200' if v >= 150 else '100-150' if v >= 100 else '50-100' if v >= 50 else '<50' if v else 'no_peak'] += 1
        print(f'   OPEN re-run targets {len(opn)} by own measured peak GB: {dict(hist)}')
        gi = sorted([(float(pk.get(j) or 0), j) for j in opn if float(pk.get(j) or 0) >= 150], reverse=True)
        for v, jid in gi[:20]:
            d = gj(dfr[jid]['Key']) if jid in dfr else {}
            print(f'   OPEN-GIANT {jid[:16]} own_peak {v} GB size {round(((jobs.get(jid) or {}).get("size") or 0) / 2**20)} MB deferral {round(((d or {}).get("min_mem_bytes") or 0) / 2**30)} GB runtime {(d or {}).get("runtime")} kills {(d or {}).get("kills_by_code")}')
        for jid, sz, own, mm, kb, rt, hc, has_res in sorted(big, key=lambda x: -(x[3] or 0))[:0]:
            print(f'   {jid[:16]} size {round((sz or 0) / 2**20)} MB own_peak {own} GB deferral_min_mem {round(mm / 2**30, 1)} GB kills {kb} runtime {rt} hold {hc} has_result {has_res}')
        bk = [(b.get('lo'), b.get('hi'), b.get('expected_bytes'), b.get('reserve_bytes')) for b in tb.get('buckets') or []]
        print(f'   bucket table ({p}): ' + ', '.join(f"{round((lo or 0) / 2**20)}-{round((hi or 0) / 2**20) if hi and hi < 1 << 60 else 'inf'}MB exp {round((e or 0) / 2**30, 1)}GB" for lo, hi, e, r in bk))
PYEOF
