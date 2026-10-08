W=/work/agentwork/sds2-pieces-not-built
for V in v553 v553q; do /opt/conv/env/bin/python -c "
import json,glob
f=glob.glob('$W/ab553/$V/FGBVF_c2e2f4/*_manifest.json')
if f:
    M=json.load(open(f[0])); c=M['counts']
    print('$V', M['class'], M['corpus'], M['skipped']['by_reason'], {k:c.get(k) for k in ('reference_parts','reference_open_shells','reference_face_sets','reference_skipped','reference_placements')}, M.get('readback',{}).get('invalid'))
"; done
