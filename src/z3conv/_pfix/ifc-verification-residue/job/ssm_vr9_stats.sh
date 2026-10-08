#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for f in $W/w/bop_vr9/af3c44bd76cfb905/out.step.stats.json $W/w/seaport_vr9/out.step.stats.json; do
if [ -f $f ]; then python3 -c "
import json; st=json.load(open('$f'))
print('STATS', '$f'.split('/')[-3:-1], {k:st.get(k) for k in ('converter','out_bytes','total_sec','peak_rss_mb','levels')}, 'L0', st.get('verify_L0'), {k:st.get(k) for k in st if k.startswith('kernel_')})"; else echo "NOTYET $f"; fi
done
