cd /work/agentwork/class1-readiness-audit
D=wk/diag; mkdir -p $D; S=src/4671ea5620030089a37717982a0e440baa90e01bb362da2a02e4a68e1e1c4dae.db1
/opt/conv/env/bin/python -c "import json;L=json.load(open('kit_k4e/layouts.json'));json.dump(L['6.87'].get('layout'),open('$D/l.json','w'));json.dump([v['layout'] for v in L.values() if v.get('layout')],open('$D/v.json','w'))"
/opt/conv/ifc84/bin/python kit_k4e/convert_one.py $S $D/m.ifc kit_k4e/tekla_profiles.json $D/l.json $D/c.json $D/v.json > $D/log 2>&1
echo IFC approx names: $(grep -c "\[approx:" $D/m.ifc); grep -m2 "IFCMECHANICALFASTENER" $D/m.ifc | cut -c1-250
timeout 600 /opt/conv/ifc84/bin/python kit_k4e/ifc2step6.py $D/m.ifc $D/m.stp --mode hybrid --prec 2 --threads 2 > $D/s.log 2>&1
echo STEP approx: $(grep -c "\[approx:" $D/m.stp); grep -m3 "PRODUCT(" $D/m.stp | cut -c1-250; grep -m3 -i "mechanical\|MM16\|A307" $D/m.stp | cut -c1-200
