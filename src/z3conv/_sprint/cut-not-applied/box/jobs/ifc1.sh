#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/ifc_one.py tools/
G=$(/opt/conv/env/bin/python - <<'P' 2>&1
import sys, re
sys.path.insert(0, '/work/agentwork/cut-not-applied/kitp2')
from db1dec import load
data = load('/work/agentwork/cut-not-applied/truth/gsk.db1')
RX = re.compile(rb'ID([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
m = {}
for x in RX.finditer(data):
    v = int.from_bytes(data[x.start() - 8:x.start() - 4], 'little', signed=True); m.setdefault(v, x.group(1).decode().upper().replace('-', ''))
print(' '.join(m.get(p, '') for p in (45670, 47409, 48195, 45934)))
P
)
echo "GUIDS: $G"
/opt/conv/env/bin/python tools/ifc_one.py truth/gsk.ifc $G 2>&1 | cut -c1-300
