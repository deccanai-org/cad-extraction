#!/bin/bash
# mkkits.sh: kit j (= deployed now) from S3, jfix = j + builder patches, jfix_audit = jfix + audit hook
cd /work/agentwork/audit-db1-codes
mkdir -p kits/j
for f in db1step.py db1bolts.py db1old.py db1prof.py convert_one.py tekla_profiles_overlay.json layouts.json worker.py; do
  aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/db1/$f kits/j/$f --only-show-errors
done
ln -sf ../common/db1dec.py kits/j/db1dec.py; ln -sf ../common/bolt_catalog.json kits/j/bolt_catalog.json
grep -m1 '^CODE' kits/j/worker.py
rm -rf kits/jfix; cp -a kits/j kits/jfix; /opt/conv/env/bin/python builder_patch.py kits/jfix
rm -rf kits/jfix_audit kits/j_audit; /opt/conv/env/bin/python patch_audit.py kits/jfix kits/jfix_audit; /opt/conv/env/bin/python patch_audit.py kits/j kits/j_audit
diff kits/j/db1old.py kits/jfix/db1old.py; diff kits/j/db1bolts.py kits/jfix/db1bolts.py
