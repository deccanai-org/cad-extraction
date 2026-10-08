#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for d in ppv_vr3/beeeacea7d2d7546 ppv_vr4b/af3c44bd76cfb905 stockton_vr7/2c0f7a89ddf2d595 ppv_vr3/2bcaa3013d9250c2; do
python3 - $W/w/$d/out.step.stats.json <<'PY'
import json,sys
try: st=json.load(open(sys.argv[1]))
except Exception as e: print(sys.argv[1], e); sys.exit()
print(sys.argv[1].split('/')[-3:-1], {k:st.get(k) for k in ('converter','out_bytes','parts','total_sec','peak_rss_mb','levels','transcode_with_openings_to_kernel','readback_parts')})
print('   ', {k:st.get(k) for k in st if k.startswith('kernel_pass')}, 'verify', {k:(st.get('verify') or {}).get(k) for k in ('sec','identical_parts_not_reverified','final_failed')}, 'L0', st.get('verify_L0'), 'inst', st.get('instancing'), 'copies', st.get('instances_written_as_copies'))
PY
done
