#!/bin/bash
# READ-ONLY: assembly-level "three ways" in the Issaquah package: IFC assemblies / beams / columns of the sequence models whose mark has
# an assembly drawing PDF and an NC1 program of the SAME job (NC1 order line contains IMS / drawing job number 19002), with the parts of
# that assembly (IfcRelAggregates) and their marks. Output /opt/report/assets/join/three_ways3.json
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import json, re, collections, boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
pid = 'Zenitude-data-3__Completed_Projects_Data_0102_Lundahl LIC_MT20_023 (Issaquah Middle School).7z'
def stem(rp):
    b = rp.rsplit('/', 1)[-1].rsplit('.', 1)[0]; return re.sub(r'-[0-9a-f]{6}$', '', b)
man = s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
pdf, nc1, stp = collections.defaultdict(list), collections.defaultdict(list), {}
for l in man.split('\n'):
    if not l.strip(): continue
    r = json.loads(l); rp = r['relpath']
    if rp.startswith('drawings/pdf/'): pdf[stem(rp).lower()].append(rp)
    elif rp.startswith('fab/nc1/'): nc1[stem(rp).lower()].append(rp)
    elif rp.startswith('model/step/'): stp[r.get('converted_from')] = (rp, r['bytes'], r.get('model_id'), r.get('converter'))
rx = re.compile(r"#(\d+)\s*=\s*(IFC[A-Z]+)\((.*?)\);", re.S)
res = []
for seq in ('52', '69', '25', '19', '15'):
    rp = f'model/ifc/IMS_Job_102120_Seq#{seq}.ifc'
    txt = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}')['Body'].read().decode('latin1')
    ents = {}
    for m in rx.finditer(txt): ents[int(m.group(1))] = (m.group(2), m.group(3))
    def args(s): return re.findall(r"'((?:[^']|'')*)'|(#\d+)|(\$|\.[A-Z_]+\.)", s)
    name = {}
    for k, (t, a) in ents.items():
        q = re.findall(r"'((?:[^']|'')*)'", a)
        if t in ('IFCELEMENTASSEMBLY', 'IFCBEAM', 'IFCCOLUMN', 'IFCMEMBER', 'IFCPLATE', 'IFCBUILDINGELEMENTPROXY') and len(q) >= 2: name[k] = (t, q[1], q[2] if len(q) > 2 else None, q[-1])
    parts = collections.defaultdict(list)
    for k, (t, a) in ents.items():
        if t == 'IFCRELAGGREGATES':
            refs = [int(x) for x in re.findall(r'#(\d+)', a)]
            # (GlobalId, OwnerHistory, Name, Description, RelatingObject, (RelatedObjects))
            if len(refs) >= 3: parts[refs[1]] += refs[2:]
    for k, (t, nm, desc, tag) in name.items():
        if t != 'IFCELEMENTASSEMBLY': continue
        mk = nm.lower()
        if mk not in pdf or mk not in nc1: continue
        kids = [name[c] for c in parts.get(k, []) if c in name]
        nh = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{nc1[mk][0]}')['Body'].read().decode('latin1').replace('\r', '').split('\n')
        if not any('IMS' in x for x in nh[1:3]): continue
        pb = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{pdf[mk][0]}')['Body'].read(); d = fitz.open(stream=pb, filetype='pdf'); tx = d[0].get_text()
        if '19002' not in tx: continue
        km = collections.Counter(c[1].lower() for c in kids)
        res.append({'seq': seq, 'ifc': rp, 'step': stp.get(rp), 'assembly': nm, 'assembly_desc': desc, 'n_parts': len(kids), 'part_marks': km.most_common(12),
                    'part_types': collections.Counter(c[0] for c in kids).most_common(), 'pdf': pdf[mk], 'nc1': nc1[mk], 'nc1_head': nh[:16],
                    'pdf_size_in': [round(d[0].rect.width / 72, 1), round(d[0].rect.height / 72, 1)], 'pdf_text': tx[:1200],
                    'same_mark_entities': sum(1 for v in name.values() if v[1].lower() == mk),
                    'parts_with_nc1': [m for m, _ in km.most_common(12) if m in nc1], 'parts_with_pdf': [m for m, _ in km.most_common(12) if m in pdf]})
    print('RESULT seq', seq, 'assemblies with pdf+nc1 (same job):', sum(1 for r in res if r['seq'] == seq), flush=True)
json.dump(res, open('/opt/report/assets/join/three_ways3.json', 'w'), indent=1)
for r in sorted(res, key=lambda r: -r['n_parts'])[:12]:
    print('RESULT', r['seq'], r['assembly'], r['assembly_desc'], 'parts', r['n_parts'], r['part_types'], 'nc1', r['nc1_head'][7:9], 'kids', r['part_marks'][:5], 'kids_nc1', r['parts_with_nc1'][:4], flush=True)
PY
