W=/work/agentwork/sds2-approx-pieces-7x
cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/p1.py $W/p1.py
if [ ! -d $W/b553 ]; then aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/sds2-step-pipeline-v5.5.3.zip $W/; mkdir -p b553; $W/env/bin/python -c "import zipfile; zipfile.ZipFile('$W/sds2-step-pipeline-v5.5.3.zip').extractall('$W/b553')"; fi
timeout 100 $W/env/bin/python $W/p1.py $W/b553/sds2-step-pipeline/decode $W/jobs/Centene_University_JOB_20c7f1 3 2>&1 | head -150
