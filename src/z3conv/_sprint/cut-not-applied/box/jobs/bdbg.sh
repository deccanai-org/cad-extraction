#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/bool_dbg.py tools/
timeout 300 /opt/conv/env/bin/python tools/bool_dbg.py pipes2/kitp2/6eabb07e71459be6/model.ifc '0tlg$4Lxf3yhKx$UU2CNuB' 2>&1 | cut -c1-300
grep -h "0tlg" pipes2/kitp2/6eabb07e71459be6/model.stp.parts.json | head -3 | cut -c1-400
python3 -c "
import json; d=json.load(open('pipes2/kitp2/6eabb07e71459be6/model.stp.parts.json'))
p = d.get('parts', d) if isinstance(d, dict) else d
x = [v for v in (p.items() if isinstance(p, dict) else enumerate(p)) if '0tlg' in json.dumps(v)]
print(json.dumps(x)[:800])
"
