#!/bin/bash
W=/work/agentwork/sds2-approx-pieces-7x-review
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x-review
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x-review
B=s3://annotationprod/cad-disk-extract/_control/z3conv/sds2
export AWS_DEFAULT_REGION=ap-south-1
cd $W
exec > $W/setup.log 2>&1
for v in 5.5.3 5.5.6; do aws s3 cp --quiet $B/sds2-step-pipeline-v$v.zip $W/; rm -rf $W/v$v; mkdir -p $W/v$v; (cd $W/v$v && unzip -q ../sds2-step-pipeline-v$v.zip); done
sha256sum $W/sds2-step-pipeline-v5.5.3.zip
U=$B/pfix/sds2-approx-pieces-7x/patch
aws s3 cp --quiet $U/sds2-approx-pieces-7x.diff $W/the.diff; aws s3 cp --quiet $U/brep.py $W/up_brep.py; aws s3 cp --quiet $U/to_step2.py $W/up_to_step2.py
sha256sum the.diff up_brep.py up_to_step2.py
rm -rf base553 cand v556; mkdir base553 cand v556
cp -r v5.5.3/sds2-step-pipeline base553/; cp -r v5.5.3/sds2-step-pipeline cand/; cp -r v5.5.6/sds2-step-pipeline v556/
(cd cand && patch -p1 < ../the.diff) && echo PATCH_OK
cmp cand/sds2-step-pipeline/decode/brep.py up_brep.py && cmp cand/sds2-step-pipeline/decode/to_step2.py up_to_step2.py && echo UPLOADED_FILES_MATCH
PY=/work/agentwork/sds2v54/env/bin/python
$PY -c "import OCP, scipy, shapely, numpy; print('env ok', scipy.__version__, shapely.__version__, numpy.__version__)"
mkdir -p jobs; : > dirs_all.txt
while read g id; do
  d=$(timeout 1800 $PY getjob.py $id $W/jobs 2>>fetch.err | tail -1); echo "$g $id $d" >> dirs_all.txt
done < models.txt
cat dirs_all.txt; du -sh jobs
date -u +%FT%TZ > SETUP_DONE
aws s3 cp --quiet setup.log $R/setup.log; aws s3 cp --quiet dirs_all.txt $R/dirs_all.txt; aws s3 cp --quiet SETUP_DONE $R/SETUP_DONE
