set -e
cd /work/agentwork/class1-readiness-audit; PY=/opt/conv/env/bin/python
for f in apply_c1_patch.py apply_c1_stats.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/$f job/; done
rm -rf kit_k5e && mkdir kit_k5e && cp kit_k/*.py kit_k/*.json kit_k5e/ 2>/dev/null || true
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/db1/db1step.py kit_k5e/db1step.py
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/db1/db1bolts.py kit_k5e/db1bolts.py
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/db1/db1bolts2.py kit_k5e/db1bolts2.py
cp job/htr_db1bolts.py kit_k5e/db1bolts.py; cp job/htr_db1step.py kit_k5e/db1step.py
$PY job/apply_c1_patch.py kit_k5e cat_c3env.json; $PY job/apply_c1_stats.py kit_k5e
D=wk/diag2; rm -rf $D; mkdir -p $D; S=src/4671ea5620030089a37717982a0e440baa90e01bb362da2a02e4a68e1e1c4dae.db1
$PY -c "import json;L=json.load(open('kit_k5e/layouts.json'));json.dump(L['6.87'].get('layout'),open('$D/l.json','w'));json.dump([v['layout'] for v in L.values() if v.get('layout')],open('$D/v.json','w'))"
/opt/conv/ifc84/bin/python kit_k5e/convert_one.py $S $D/m.ifc kit_k5e/tekla_profiles.json $D/l.json $D/c.json $D/v.json > $D/log 2>&1
echo IFC approx names: $(grep -c "\[approx:" $D/m.ifc) fasteners: $(grep -c IFCMECHANICALFASTENER $D/m.ifc)
timeout 900 /opt/conv/ifc84/bin/python kit_k5e/ifc2step6.py $D/m.ifc $D/m.stp --mode hybrid --prec 2 --threads 2 > $D/s.log 2>&1
echo STEP approx: $(grep -c "\[approx:" $D/m.stp); grep -m2 "IfcMechanicalFastener" $D/m.stp | cut -c1-220
$PY -c "import json;b=json.load(open('$D/c.json'))['bolt_stats'];print({k:b.get(k) for k in ('bolts','nominal_head_nut_written','holes_nominal_clearance','washers_nominal','slotted_bolts_cut_round','bolts_axial_unknown','bolts_shifted_to_plies','model_catalog_bolts')})"
rm -f $D/m.ifc $D/m.stp
