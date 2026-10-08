W=/work/agentwork/sds2-pieces-not-built; cd $W
timeout 120 $W/env/bin/python - <<'PY'
import sys; sys.path.insert(0,'/work/agentwork/sds2-pieces-not-built/trees/b/decode')
import to_step2 as T2, inspect
from piece_table import read_pieces, kind
job='/work/agentwork/sds2-pieces-not-built/jobs/21030_S8EP_Phase-III_5eb32c'
P=read_pieces(job); p=P[3147]; print(p, kind(p))
print(T2.source_gap(job,3147,p))
src=inspect.getsource(T2.source_gap); print(src[:1800])
PY
