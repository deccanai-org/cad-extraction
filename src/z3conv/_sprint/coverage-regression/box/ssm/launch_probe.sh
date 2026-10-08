#!/bin/bash
W=/work/agentwork/coverage-regression/ab
OUTS=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/coverage-regression
cd $W && for f in probe_profdb.py probe_zips.json want_names.json; do aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/coverage-regression/ab/$f . --only-show-errors; done
timeout 900 /opt/conv/env/bin/python probe_profdb.py probe_zips.json want_names.json probe_out.json > probe.log 2>&1
aws s3 cp --only-show-errors probe_out.json $OUTS/ab/probe_out.json; aws s3 cp --only-show-errors probe.log $OUTS/ab/probe.log
tail -c 6000 probe.log
