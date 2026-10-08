#!/bin/bash
cd /work/agentwork/ifcxml/t2/work/tests
for f in *.validate.json; do /opt/conv/env/bin/python -c "
import json,sys
d=json.load(open('$f'))
if d.get('verdict')!='pass': print('$f', json.dumps((d.get('roundtrip') or {}).get('samples'))[:1500])
"; done
