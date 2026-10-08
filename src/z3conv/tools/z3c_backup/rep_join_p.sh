#!/bin/bash
# READ-ONLY search for the report's "join" and "one job, three ways" examples: piece marks present as a shop-drawing PDF, a DXF outline
# and an NC1 program in the same package; NC1 header vs DXF extents vs PDF text; whether the package's IFC carries the mark.
# Output /opt/report/assets/join/candidates.json. Idempotent: first call starts unit z3repjoinp.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/report; O=$D/assets/pjoin; mkdir -p $O $D/work/pjoin
if systemctl is-active -q z3repjoinp; then echo running; tail -n 3 $O/log.txt; exit 0; fi
if [ -f $O/finished ]; then echo "finished $(cat $O/finished)"; tail -n 4 $O/log.txt; exit 0; fi
cat > $D/rep_join_p.py <<'PYEOF'
import os, json, re, random, collections, io
import boto3, fitz, ezdxf
from ezdxf import bbox as ebbox
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
O = '/opt/report/assets/pjoin'; W = '/opt/report/work/pjoin'
P = [p for p in json.load(open('/opt/report/out/projects_p1.json')) if not p.get('addon_of')]
rnd = random.Random(77)
def stem(rp):
    b = rp.rsplit('/', 1)[-1]; b = b.rsplit('.', 1)[0]
    return re.sub(r'-[0-9a-f]{6}$', '', b).lower()
def nc1_header(txt):
    L = [l.rstrip('\r') for l in txt.split('\n')]
    try: i = next(k for k, l in enumerate(L) if l.strip() == 'ST')
    except StopIteration: return None
    f = [l.strip() for l in L[i + 1:i + 20]]
    keys = ['order', 'drawing', 'phase', 'mark', 'grade', 'qty', 'profile', 'code', 'length', 'height', 'width', 'flange_t', 'web_t', 'radius', 'kg_m', 'paint_m2']
    return dict(zip(keys, f)), L[i:i + 18]
cands = [p for p in P if all((p['per_channel'].get(c) or 0) > 0 for c in ('drawings/pdf', 'drawings/dxf', 'fab/nc1'))]
rnd.shuffle(cands)
out = []; scanned = 0
for p in cands[:240]:
    pid = p['id']
    man = s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
    pdf, dxf, nc1, ifc, stp = {}, {}, {}, [], []
    for l in man.split('\n'):
        if not l.strip(): continue
        r = json.loads(l); rp = r['relpath']
        if rp.startswith('drawings/pdf/'): pdf.setdefault(stem(rp), (rp, r['bytes']))
        elif rp.startswith('drawings/dxf/'): dxf.setdefault(stem(rp), (rp, r['bytes']))
        elif rp.startswith('fab/nc1/'): nc1.setdefault(stem(rp), (rp, r['bytes']))
        elif rp.startswith('model/ifc/') and rp.lower().endswith('.ifc'): ifc.append((rp, r['bytes']))
        elif rp.startswith('model/step/'): stp.append((rp, r['bytes']))
    trip = sorted(set(pdf) & set(dxf) & set(nc1)); scanned += 1
    if not trip: continue
    for st in rnd.sample(trip, min(6, len(trip))):
        rec = {'project_id': pid, 'disk': p['disk'], 'mark_stem': st, 'pdf': pdf[st][0], 'dxf': dxf[st][0], 'nc1': nc1[st][0],
               'n_ifc': len(ifc), 'n_step': len(stp), 'n_triples': len(trip)}
        try:
            nt = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{nc1[st][0]}')['Body'].read().decode('latin1')
            h = nc1_header(nt)
            if not h: continue
            rec['nc1_header'], rec['nc1_lines'] = h
            db = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{dxf[st][0]}')['Body'].read()
            open(f'{W}/x.dxf', 'wb').write(db); doc = ezdxf.readfile(f'{W}/x.dxf')
            ext = ebbox.extents(doc.modelspace()); rec['dxf_ext'] = [round(ext.size.x, 3), round(ext.size.y, 3)] if ext.has_data else None
            rec['dxf_units'] = doc.header.get('$INSUNITS')
            pb = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{pdf[st][0]}')['Body'].read()
            pd = fitz.open(stream=pb, filetype='pdf'); tx = pd[0].get_text(); rec['pdf_pages'] = pd.page_count
            mk = rec['nc1_header'].get('mark', ''); rec['pdf_has_mark'] = bool(mk) and mk.lower() in tx.lower()
            rec['pdf_has_profile'] = bool(rec['nc1_header'].get('profile')) and rec['nc1_header']['profile'].replace(' ', '').lower() in tx.replace(' ', '').lower()
            rec['pdf_page_in'] = [round(pd[0].rect.width / 72, 2), round(pd[0].rect.height / 72, 2)]
            try:
                Lm, Wm = float(rec['nc1_header']['length']), float(rec['nc1_header']['width'] if rec['nc1_header'].get('code') == 'B' else rec['nc1_header']['height'])
                if rec['dxf_ext']:
                    a, b = sorted(rec['dxf_ext'], reverse=True)
                    for f_, u in ((25.4, 'in'), (1.0, 'mm')):
                        if abs(a * f_ - Lm) < 0.6 and abs(b * f_ - Wm) < 0.6: rec['dxf_matches_nc1'] = u
            except Exception: pass
        except Exception as e:
            rec['error'] = f'{type(e).__name__}: {str(e)[:120]}'
        out.append(rec)
    if len([r for r in out if r.get('dxf_matches_nc1') and r.get('pdf_has_mark')]) >= 40: break
json.dump(out, open(f'{O}/candidates.json', 'w'), indent=1)
good = [r for r in out if r.get('dxf_matches_nc1') and r.get('pdf_has_mark')]
print('DONE scanned', scanned, 'triples tested', len(out), 'consistent', len(good), flush=True)
PYEOF
date -u +%FT%TZ > $O/started
systemctl reset-failed z3repjoinp 2>/dev/null
systemd-run --unit=z3repjoinp --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_join_p.py > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 30; echo "started: $(systemctl is-active z3repjoinp)"; tail -n 3 $O/log.txt
