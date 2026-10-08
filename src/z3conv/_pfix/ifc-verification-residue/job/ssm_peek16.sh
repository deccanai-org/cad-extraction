#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for d in $W/w/ppv_vr3/1c61df42e5270bac $W/w/ppv_vr4b/2c0f7a89ddf2d595 $W/w/far_vr4/d713eae4bf9dd247; do
python3 - $d/out.step.stats.json <<'PY'
import json,sys
try: st=json.load(open(sys.argv[1]))
except Exception as e: print(sys.argv[1], e); sys.exit()
print(sys.argv[1].split('/')[-2], {k:st.get(k) for k in ('converter','out_bytes','parts','faces','total_sec','peak_rss_mb','levels','instancing','transcode_with_openings_to_kernel','tess_products','exact_parts','approx_parts','readback_parts','far_origin')})
print('  kernel', {k:st.get(k) for k in st if k.startswith('kernel_pass')}, 'verify', {k:(st.get('verify') or {}).get(k) for k in ('sec','final_failed','identical_parts_not_reverified')}, 'L0', st.get('verify_L0'))
PY
done
