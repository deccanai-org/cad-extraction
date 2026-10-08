#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && for f in sds2_ifc_recall.py nc1_holes_check.py aggregate.py run_jobs.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/$f $f.new && mv $f.new $f; done
ls -la out/ifc | head; ls cache/ifc_*.npz | wc -l; tail -3 logs/pipe.log; uptime
