#!/bin/bash
# READ-ONLY: "one job, three ways" for the PARTIAL tier: in partial-only packages whose partial STEP comes from IFC and which carry drawings
# and NC1, find IfcElementAssembly marks that also name a shop-drawing PDF and an NC1 program; record the assembly's parts.
# Output /opt/report/assets/pthree/candidates.json. Idempotent unit z3rep3wp.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/report; O=$D/assets/pthree; mkdir -p $O
if systemctl is-active -q z3rep3wp; then echo running; tail -n 3 $O/log.txt; exit 0; fi
if [ -f $O/finished ]; then echo "finished $(cat $O/finished)"; tail -n 6 $O/log.txt; exit 0; fi
cat > $D/rep_3ways_p.py <<'PYEOF'
import json, re, collections, random, boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
P = [p for p in json.load(open('/opt/report/out/projects_p1.json')) if not p.get('addon_of')
     and (p['per_channel'].get('drawings/pdf') or 0) >= 20 and (p['per_channel'].get('fab/nc1') or 0) >= 20 and any(s['step_source'] == 'ifc' for s in p['steps'])]
random.Random(3).shuffle(P); print('candidate projects', len(P), flush=True)
def stem(rp):
    b = rp.rsplit('/', 1)[-1].rsplit('.', 1)[0]; return re.sub(r'-[0-9a-f]{6}$', '', b)
rx = re.compile(r"#(\d+)\s*=\s*(IFC[A-Z]+)\((.*?)\);", re.S)
out = []
for p in P[:60]:
    pid = p['id']
    man = [json.loads(l) for l in s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape').split('\n') if l.strip()]
    pdf = collections.defaultdict(list); nc1 = collections.defaultdict(list)
    for r in man:
        rp = r['relpath']
        if rp.startswith('drawings/pdf/'): pdf[stem(rp).lower()].append(rp)
        elif rp.startswith('fab/nc1/'): nc1[stem(rp).lower()].append(rp)
    steps = [r for r in man if r.get('modality') == 'step' and r.get('step_source') == 'ifc']
    for st in steps:
        src = st.get('converted_from'); srow = next((r for r in man if r['relpath'] == src), None)
        if not srow or not src.lower().endswith('.ifc') or srow['bytes'] > 40e6: continue
        txt = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{src}')['Body'].read().decode('latin1')
        ents = {int(m.group(1)): (m.group(2), m.group(3)) for m in rx.finditer(txt)}
        name = {}
        for k, (t, a) in ents.items():
            q = re.findall(r"'((?:[^']|'')*)'", a)
            if t in ('IFCELEMENTASSEMBLY', 'IFCBEAM', 'IFCCOLUMN', 'IFCMEMBER', 'IFCPLATE') and len(q) >= 2: name[k] = (t, q[1], q[2] if len(q) > 2 else None)
        parts = collections.defaultdict(list)
        for k, (t, a) in ents.items():
            if t == 'IFCRELAGGREGATES':
                refs = [int(x) for x in re.findall(r'#(\d+)', a)]
                if len(refs) >= 3: parts[refs[1]] += refs[2:]
        cnt = collections.Counter(t for t, _ in ents.values())
        hits = 0
        for k, (t, nm, desc) in name.items():
            if t != 'IFCELEMENTASSEMBLY': continue
            mk = nm.lower()
            if mk not in pdf or mk not in nc1: continue
            kids = [name[c] for c in parts.get(k, []) if c in name]
            if len(kids) < 3: continue
            km = collections.Counter(c[1].lower() for c in kids)
            out.append({'project_id': pid, 'disk': p['disk'], 'ifc': src, 'step': st['relpath'], 'kind': (st.get('partial') or {}).get('kind'),
                        'issues': (st.get('partial') or {}).get('issues'), 'assembly': nm, 'desc': desc, 'n_parts': len(kids),
                        'part_types': collections.Counter(c[0] for c in kids).most_common(), 'part_marks': km.most_common(10),
                        'parts_with_nc1': [m for m, _ in km.most_common(10) if m in nc1], 'pdf': pdf[mk], 'nc1': nc1[mk],
                        'ifc_counts': {k2: cnt[k2] for k2 in ('IFCELEMENTASSEMBLY', 'IFCBEAM', 'IFCCOLUMN', 'IFCMEMBER', 'IFCPLATE', 'IFCMECHANICALFASTENER') if cnt.get(k2)}})
            hits += 1
            if hits >= 8: break
        print('scanned', pid[:70], src[-40:], 'assemblies matched', hits, flush=True)
    if len(out) >= 60: break
json.dump(out, open('/opt/report/assets/pthree/candidates.json', 'w'), indent=1)
print('DONE candidates', len(out), 'projects', len({o['project_id'] for o in out}), flush=True)
PYEOF
date -u +%FT%TZ > $O/started
systemctl reset-failed z3rep3wp 2>/dev/null
systemd-run --unit=z3rep3wp --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_3ways_p.py > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 20; echo "started: $(systemctl is-active z3rep3wp)"; tail -n 2 $O/log.txt
