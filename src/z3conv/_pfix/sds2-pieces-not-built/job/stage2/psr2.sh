W=/work/agentwork/sds2-pieces-not-built
for V in v553 v553r; do /opt/conv/env/bin/python -c "
import json,sys
M=json.load(open('$W/ab553/$V/State_Reno_df6dfb/State_Reno_df6dfb_stage2_manifest.json'))
print('$V', M['skipped']['by_reason'], {k:M['counts'].get(k) for k in ('reference_parts','reference_open_shells','reference_face_sets','reference_skipped')})
"; grep -a "reference\|budget\|s)" $W/ab553/$V/State_Reno_df6dfb/convert.log | head -5 | cut -c1-200; done
