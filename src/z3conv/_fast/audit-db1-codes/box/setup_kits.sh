#!/bin/bash
# setup_kits.sh (box): shared single-version kit files + i_audit kit + experiment tools
cd /work/agentwork/audit-db1-codes
mkdir -p kits/common
for f in db1dec.py layouts.json tekla_profiles.json bolt_catalog.json ifc2step5.py ifc2step6.py step_check.py ifc_census.py grade_join.py ifc_crash_bisect.py ifc_exclude.py; do
  [ -s kits/common/$f ] || aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/db1/$f kits/common/$f --only-show-errors
done
for k in kits/*/; do
  k=${k%/}; [ "$k" = kits/common ] && continue
  for f in db1dec.py layouts.json bolt_catalog.json; do ln -sf ../common/$f $k/$f; done
done
/opt/conv/env/bin/python patch_audit.py kits/i kits/i_audit
/opt/conv/env/bin/python patch_audit.py kits/h kits/h_audit
ls -la kits/*/ | head -80
