W=/work/agentwork/sds2-approx-pieces-7x
cd $W; aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/p4.py $W/p4.py
export OMP_NUM_THREADS=1
timeout 280 $W/env/bin/python $W/p4.py $W/cand6/sds2-step-pipeline/decode $(cat $W/dirs_d7.txt) 2>&1 | grep -v Warn | head -60
