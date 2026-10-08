#!/bin/bash
# Assemble the z3conv kits from common/ and upload them to the control prefix (operator SSO profile).
#   bash deploy.sh [ifc|db1|sds2|grade|coord|scan ...]   (default: all)
set -e
cd "$(dirname "$0")"
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
export AWS_PROFILE=${AWS_PROFILE:-annotationprod-publish}
PIPES=${@:-ifc db1 sds2 grade final coord scan}
for P in $PIPES; do
  case $P in
    ifc|db1|grade)
      cp common/convfleet.py common/step_check.py common/ifc_census.py common/grade_join.py common/ifc_attrib.py $P/
      cp common/setup_occ.sh $P/setup.sh ;;
    final)
      mkdir -p final; cp common/convfleet.py common/step_check.py common/ifc_census.py common/grade_join.py common/ifc_attrib.py final/
      cp grade/worker.py grade/step_verify_big.py db1/db1dec.py db1/db1step.py db1/db1old.py db1/db1bolts.py db1/db1prof.py db1/convert_one.py db1/layouts.json db1/tekla_profiles.json db1/tekla_profiles_overlay.json db1/bolt_catalog.json db1/db1bolts2.py db1/tekla_bolt_assemblies.json db1/attrlink.py db1/fittings.py final/
      cp common/setup_occ.sh final/setup.sh ;;
    sds2)
      cp common/convfleet.py $P/ ;;
    verify)
      cp common/convfleet.py $P/; cp sds2/fetch.py $P/; cp common/ifc_attrib.py $P/
      cp common/setup_verify.sh $P/setup.sh ;;
    coord)
      cp common/grade_join.py $P/ ;;
  esac
  if [ "$P" = grade ]; then cp db1/db1dec.py db1/db1step.py db1/db1old.py db1/db1bolts.py db1/db1prof.py db1/convert_one.py db1/layouts.json db1/tekla_profiles.json db1/tekla_profiles_overlay.json db1/bolt_catalog.json db1/db1bolts2.py db1/tekla_bolt_assemblies.json db1/attrlink.py db1/fittings.py grade/; fi
  case $P in
    ifc|db1|sds2|grade|final|verify)
      sed "s/__PIPE__/$P/g" common/run.sh > $P/run.sh
      sed "s/__PIPE__/$P/g" common/userdata.sh > $P/userdata.sh ;;
  esac
  for f in $P/*.py; do python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f"; done
  aws s3 sync --only-show-errors $P/ $CTL/$P/ --exclude '*' --include '*.py' --include '*.sh' --include '*.json' --include '*.zip' --include '*.txt' --exclude '*/*'
  echo "deployed $P: $(ls $P | wc -l) files"
done
