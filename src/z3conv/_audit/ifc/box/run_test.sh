#!/bin/bash
mkdir -p /work/agentwork/audit-ifc && cd /work/agentwork/audit-ifc
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/ .
rm -rf out; mkdir -p out
timeout 1500 /opt/conv/env/bin/python scan.py --ids 6250be71ec4ff77b,3cbf9c1f5b0b2337,0c5f518af190b90b,83134afa6b20900b,cdb0c35e2c6b0434,000eaae86a8acd03,0092a0c5caabe72d --small-procs 7 --big-procs 1 2>&1 | tail -15
for f in out/*.json; do /opt/conv/env/bin/python - "$f" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
g=d.get('graph') or {}
print(d['id'][:16], d.get('sec'), 'hdr', (d.get('hdr') or {}).get('schema'), (d.get('hdr') or {}).get('fn_originating'), '|', (d.get('hdr') or {}).get('fn_preprocessor'), 'nul', d.get('nul_bytes'), d.get('first_non_nul'), 'ents', d.get('entities'), 'blocks', d.get('spf_blocks'), 'zip', (d.get('zip') or {}).get('ifc_members'), 'err', d.get('error'), d.get('graph_errors'))
print('   graph', {k: g.get(k) for k in ('schema','with_body','transcodable','kernel','with_openings','transcodable_with_openings','n_IfcOpeningElement','applications','graph_sec')})
print('   kinds', g.get('kind_signatures'))
for s in (g.get('vol_samples') or [])[:8]: print('   vol', {k: s.get(k) for k in ('cls','name','openings','cut_vol','uncut_vol','cut_closed','uncut_closed','opening_effect','verdict','step_vol','step_over_cut','step_over_uncut','match','error')})
print('   step_parts', d.get('step_parts_key'), d.get('step_parts_n'), d.get('step_parts_error'))
PY
done
