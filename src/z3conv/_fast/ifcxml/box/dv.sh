#!/bin/bash
cd /work/agentwork/ifcxml
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/validate_spf.py validate_spf.py.new --only-show-errors
cp validate_spf.py.new validate_spf.py && cp validate_spf.py.new t2/validate_spf.py && rm validate_spf.py.new
grep -c wrapped_single_refs_compared validate_spf.py t2/validate_spf.py
cat job4.log; tail -3 harness.log
