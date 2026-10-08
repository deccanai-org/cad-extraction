#!/bin/bash
set -e
W=/work/agentwork/sds2-weights-failures-review; mkdir -p $W/trees $W/jobs $W/out $W/logs; cd $W
aws s3 cp --only-show-errors --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures-review/ $W/stage/
cp $W/stage/rrun.py $W/stage/ids_*.txt $W/
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/fetch.py $W/fetch.py
if [ ! -x $W/env/bin/python ]; then cp -a /work/agentwork/sds2-weights-failures/env $W/env; fi
$W/env/bin/python -c "import OCP, numpy; print('env ok', numpy.__version__)"
mk() { d=$W/trees/$1; rm -rf $d; mkdir -p $d; (cd $d && unzip -q $W/stage/$2); }
mk b553 sds2-step-pipeline-v5.5.3.zip; mk w553 sds2-step-pipeline-v5.5.3.zip; mk b555 sds2-step-pipeline-v5.5.5.zip; mk b54 sds2-step-pipeline-v5.4.zip; mk w54 sds2-step-pipeline-v5.4.zip
(cd $W/trees/w553 && patch -p1 < $W/stage/sds2-weights-failures-v5.5.3.patch | tail -3)
(cd $W/trees/w54 && patch -p1 < $W/stage/sds2-weights-failures-v5.4.patch | tail -3)
for t in b553 w553 b555 b54 w54; do $W/env/bin/python -m py_compile $W/trees/$t/sds2-step-pipeline/decode/to_step2.py && echo "$t compiles"; done
sha256sum $W/stage/*.zip $W/stage/*.patch
du -sh $W/env
