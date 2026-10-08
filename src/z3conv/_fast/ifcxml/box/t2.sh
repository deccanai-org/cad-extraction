#!/bin/bash
# regression suite with the current converter / validator in a separate dir (does not touch the running batch)
mkdir -p /work/agentwork/ifcxml/t2 && cd /work/agentwork/ifcxml/t2
rm -rf work
aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/ . --exclude "*" --include "ifcxml2spf.py" --include "validate_spf.py" --include "compare_sibling.py" --include "run_tests.sh" --include "tests/*" --only-show-errors
bash run_tests.sh > tests.log 2>&1
aws s3 cp work/tests/summary.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/tests_summary_v2.json --only-show-errors
aws s3 cp tests.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/logs/tests_v2.log --only-show-errors
grep -c '"verdict": "pass"' tests.log; tail -c 400 tests.log
