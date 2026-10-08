#!/bin/bash
# READ-ONLY: score Disk-1-origin perfect packages by workflow folders (INPUTS/UPLOADS/COMMENTS/EMAILS/RFI/...) in manifest source paths
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/coord_tmp/disk1_perfect_ids.json /opt/report/work/disk1_perfect_ids.json
cat > /opt/report/work/pick_workflow.py <<'PY'
import json, re, collections, boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'; R = 'cad-disk-extract/dataset/packages/3d/'
ids = json.load(open('/opt/report/work/disk1_perfect_ids.json'))
KW = {'input': r'\binputs?\b', 'upload': r'\buploads?\b', 'comment': r'\bcomments?\b|\bmarkups?\b|\bredlines?\b', 'email': r'\be-?mails?\b|\bcorrespondence\b',
      'rfi': r'\brfis?\b', 'approval': r'\bapprov', 'submittal': r'\bsubmittals?\b', 'revision': r'\brevisions?\b|\brev\b', 'transmittal': r'\btransmittals?\b'}
def one(pid):
    p = R + pid + '/'
    pj = json.loads(s3.get_object(Bucket=B, Key=p + 'project.json')['Body'].read())
    m = s3.get_object(Bucket=B, Key=p + 'manifest.jsonl')['Body'].read().decode()
    hit = collections.Counter(); folders = collections.defaultdict(set); n = 0; ch = collections.Counter()
    for l in m.split('\n'):
        if not l.strip(): continue
        r = json.loads(l); n += 1; ch[r['relpath'].split('/')[0]] += 1
        sp = r.get('source_path') or r.get('source_key') or ''
        segs = re.split(r'[/\\]', sp)[:-1]
        for s in segs:
            sl = re.sub(r'[_\-.]', ' ', s.lower())
            for k, rx in KW.items():
                if re.search(rx, sl): hit[k] += 1; folders[k].add(s[:60])
    return {'pid': pid, 'files': n, 'chan': dict(ch), 'hit': dict(hit), 'folders': {k: sorted(v)[:6] for k, v in folders.items()},
            'excluded_non_asset': pj.get('excluded_non_asset_files'), 'steps': ch.get('model', 0), 'src': pj.get('source_archive')}
with ThreadPoolExecutor(48) as ex: res = list(ex.map(one, ids))
json.dump(res, open('/opt/report/out/pick_workflow.json', 'w'))
for r in sorted(res, key=lambda r: -len(r['hit']))[:25]: print('RESULT', len(r['hit']), r['hit'], r['files'], r['excluded_non_asset'], r['pid'][:110])
PY
cd /opt/report/work && /opt/report/venv/bin/python pick_workflow.py
