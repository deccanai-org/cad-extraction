#!/bin/bash
W=/work/agentwork/ifc-verification-residue
S=$W/w/mnc_dev3/4f6b8e2e96937507/out.step
grep -c "MAPPED_ITEM" $S; grep -c "REPRESENTATION_MAP" $S; grep -m3 "MAPPED_ITEM" $S
python3 - <<'PY'
import json
st=json.load(open('/work/agentwork/ifc-verification-residue/w/mnc_dev3/4f6b8e2e96937507/out.step.stats.json'))
for k in ('instancing','instances_written_as_copies','verify_L0','levels','parts','bbox','verify'):
    print(k, json.dumps(st.get(k))[:400])
PY
grep -m5 "CARTESIAN_POINT" $S
