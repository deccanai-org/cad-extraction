#!/bin/bash
# mkkits2.sh: j (deployed now) from S3; jfix = j + P1-P3; jfixr = j + P1-P4; *_audit2 = + audit hook v2
cd /work/agentwork/audit-db1-codes
mkdir -p kits/j
for f in db1step.py db1bolts.py db1old.py db1prof.py convert_one.py tekla_profiles_overlay.json layouts.json worker.py; do
  [ -s kits/j/$f ] || aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/db1/$f kits/j/$f --only-show-errors
done
ln -sf ../common/db1dec.py kits/j/db1dec.py; ln -sf ../common/bolt_catalog.json kits/j/bolt_catalog.json
rm -rf kits/jfix kits/jfixr kits/jfix_audit2 kits/jfixr_audit2
cp -a kits/j kits/jfix; /opt/conv/env/bin/python builder_patch.py kits/jfix
cp -a kits/j kits/jfixr; /opt/conv/env/bin/python builder_patch.py kits/jfixr --holes-rel
/opt/conv/env/bin/python patch_audit2.py kits/jfix kits/jfix_audit2; /opt/conv/env/bin/python patch_audit2.py kits/jfixr kits/jfixr_audit2
for k in jfix jfixr; do diff kits/j/db1step.py kits/$k/db1step.py | head -50; done
