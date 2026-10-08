#!/bin/bash
W=/work/agentwork/ifc-verification-residue
f=$W/w/bop_dev3/af3c44bd76cfb905/out.step.stats.json
if [ -f $f ]; then python3 -c "
import json; st=json.load(open('$f'))
print('BOPDEV3', {k:st.get(k) for k in ('converter','out_bytes','total_sec','peak_rss_mb','levels','transcode_with_openings_to_kernel')}, 'L0', st.get('verify_L0'), {k:st.get(k) for k in st if k.startswith('kernel_pass')})"; else echo NOTYET; fi
