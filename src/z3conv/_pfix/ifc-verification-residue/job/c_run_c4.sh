#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue/sds2; cd $W
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/sds2
aws s3 cp --quiet $S/apply7243.py . ; aws s3 cp --quiet $S/sds2job_v54ivr.py .
PY=/opt/conv/env/bin/python; SPY=/work/agentwork/sds2v54/env/bin/python
for v in v5.4 v5.5.3; do rm -rf ${v}ivr; cp -r $v ${v}ivr; $PY apply7243.py ${v}ivr/sds2-step-pipeline/decode/sds2job.py $W/sds2job_v54ivr.py; done
cmp v5.4ivr/sds2-step-pipeline/decode/sds2job.py sds2job_v54ivr.py && echo "v5.4ivr identical to the local patched file"
# diag of the 3rd job
JD=$(dirname $(find jobs/6eeedc274302b8e4032f8736 -name mem_idx | head -1))/..
$SPY diag_mem.py $W/v5.4/sds2-step-pipeline/decode $JD 2>&1 | head -12
cat > runall.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/ifc-verification-residue/sds2; cd $W; SPY=/work/agentwork/sds2v54/env/bin/python
export PYTHONUNBUFFERED=1 MPLBACKEND=Agg
[ -f /work/agentwork/sds2v54/env/lib/libexpat.so.1 ] && export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
for id in a47a130792964d28 58c969614e6f06bd 6eeedc274302b8e4032f8736; do
  JD=$(cd $(dirname $(find jobs/$id -name mem_idx | head -1))/.. && pwd)
  for v in v5.4 v5.4ivr v5.5.3ivr; do
    o=$W/out/$v/$id; mkdir -p $o; cd $o
    /usr/bin/time -v timeout 3600 $SPY -u $W/$v/sds2-step-pipeline/decode/sds2_to_step.py "$JD" -o $o/job_stage2.step --stage 2 --verify > $o/log.txt 2> $o/err.txt
    echo "$id $v rc=$? $(grep -m1 'Maximum resident' $o/err.txt)" >> $W/out/summary.txt
    cd $W
  done
done
echo DONE >> $W/out/summary.txt
for f in $(find out -name '*manifest.json' -o -name summary.txt -o -name log.txt -o -name err.txt -o -name '*_pieces.csv' -o -name '*_skipped.csv'); do aws s3 cp --quiet $f s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/sds2_7243/$f; done
EOS
rm -rf out; mkdir -p out; setsid nohup bash runall.sh > runall.log 2>&1 < /dev/null &
echo launched $!
