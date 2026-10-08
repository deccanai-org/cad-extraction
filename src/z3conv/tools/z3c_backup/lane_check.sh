#!/bin/bash
# READ-ONLY attended check of the data-4 disk lanes (lead: DB1 lane check). Only S3 GET / LIST; writes nothing (stdout only).
# Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/lane_check.sh 300
#  - lane workers: fresh heartbeats under zentitude-data-4/_state/conv2/<pipe>/hosts/ (count, running, gate incl. yield_data3)
#  - results: count by status/reason, newest 20 (output key, suffix, key prefix check), claims in flight
#  - output objects: newest objects under zentitude-data-4/conversions/<pipe>-step/ written after 2026-10-03T05:00Z, and a check that
#    no object older than that was rewritten (LastModified of the old files unchanged = none after the epoch among pre-lane names)
#  - index: zentitude-data-4/_state/conv2/status_block.json + conv_status.disks
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - "${1:-db1,ifc,sds2}" <<'PYEOF'
import sys, json, time, collections, datetime
import boto3
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'; R = 'cad-disk-extract/zentitude-data-4'; ST = f'{R}/_state/conv2'
pipes = sys.argv[1].split(',')
now = time.time(); EPOCH = datetime.datetime(2026, 10, 3, 5, 0, tzinfo=datetime.timezone.utc)
def lst(p):
    out = []
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=p):
        out += pg.get('Contents', [])
    return out
def gj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception: return None
for pipe in pipes:
    hb = [o for o in lst(f'{ST}/{pipe}/hosts/') if now - o['LastModified'].timestamp() < 300]
    docs = [gj(o['Key']) or {} for o in hb]
    run = sum(len(d.get('running') or []) for d in docs)
    yld = sum(1 for d in docs if (d.get('gate') or {}).get('yield_data3'))
    print(f'== {pipe}: lane workers {len(docs)} on {len({d.get("host") for d in docs})} hosts; running {run}; gates yielding to data-3 {yld}')
    for d in sorted(docs, key=lambda d: -len(d.get('running') or []))[:6]:
        g = d.get('gate') or {}
        print(f"   {str(d.get('host'))[:30]} pid {d.get('pid')} slots {d.get('slots')} running {len(d.get('running') or [])} gate mem/cpu/disk "
              f"{g.get('ok_mem')}/{g.get('ok_cpu')}/{g.get('ok_disk')} yield_data3={g.get('yield_data3')} code {d.get('code')}")
    rj = [(d.get('host'), r) for d in docs for r in d.get('running') or []]
    for h, r in sorted(rj, key=lambda x: x[1].get('since') or '')[:12]:
        print(f"   RUN {str(h)[:22]} {str(r.get('id'))[:16]} since {r.get('since')} size {round((r.get('size') or 0) / 2**20)} MB rss {round((r.get('rss') or 0) / 2**30, 1)} GB peak {round((r.get('peak_rss') or 0) / 2**30, 1)} GB")
    res = lst(f'{ST}/{pipe}/results/')
    rt = lst(f'{ST}/{pipe}/retry/') + lst(f'{ST}/{pipe}/deferred/')
    for o in rt[:5]:
        print('   RETRY/DEFERRED', o['Key'].rsplit('/', 2)[-2:], json.dumps(gj(o['Key']) or {})[:300])
    cl = [o for o in lst(f'{ST}/{pipe}/claims/') if now - o['LastModified'].timestamp() < 1500]
    print(f'   results {len(res)}; claims in flight {len(cl)}')
    newest = sorted(res, key=lambda o: o['LastModified'])[-20:]
    st = collections.Counter(); bad = []
    for o in newest:
        r = gj(o['Key']) or {}
        st[f"{r.get('status')}:{r.get('reason') or ''}"] += 1
        k = r.get('out_key') or (r.get('step') or {}).get('key') or (r.get('outputs') or {}).get('prefix') or ''
        if k and not k.startswith(f'{R}/conversions/'):
            bad.append(k)
        print(f"   {o['LastModified']:%H:%M:%S} {o['Key'].rsplit('/',1)[-1][:20]} {r.get('status')} {r.get('reason') or ''} code={r.get('code')} out={k[len(R)+1:][:90]}")
    print(f'   newest-20 status: {dict(st)}; outputs outside {R}/conversions/: {bad[:3]}')
    outs = lst(f'{R}/conversions/{pipe}-step/')
    new = [o for o in outs if o['LastModified'] >= EPOCH]
    print(f'   conversions/{pipe}-step: {len(outs)} objects, {len(new)} written since 05:00Z; suffixes of new: '
          f"{dict(collections.Counter('.'.join(o['Key'].rsplit('/',1)[-1].split('.')[1:])[:20] for o in new).most_common(6))}")
blk = gj(f'{ST}/status_block.json')
print('== status_block', json.dumps({k: v for k, v in (blk or {}).items() if k != 'eta'})[:2500] if blk else 'none yet')
cs = gj('cad-disk-extract/zenitude-data-3/_state/conv_status.json') or {}
print('== conv_status', cs.get('updated'), 'disks:', list((cs.get('disks') or {}).keys()))
PYEOF
