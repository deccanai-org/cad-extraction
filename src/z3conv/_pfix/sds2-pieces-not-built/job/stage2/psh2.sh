W=/work/agentwork/sds2-pieces-not-built; cd $W
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
aws s3 cp --quiet $C/probe_sh2.py $W/stage/probe_sh2.py; aws s3 cp --quiet $C/trees553q.tgz $W/stage/trees553q.tgz
rm -rf $W/trees/v553q && tar xzf $W/stage/trees553q.tgz -C $W/trees
for V in v553 v553q; do echo "== $V"; timeout 200 $W/env/bin/python $W/stage/probe_sh2.py $W/trees/$V/decode A-Practice_Job_1cd870:615 2>&1 | tail -3; done
