#!/bin/bash
# BOX-C review of sds2_v5.4_sparse_layout_7243.diff on v5.5.5 (newest) : layout survey on every data-3 7.221/7.233/7.243/7.253 job + stage-2 --verify base vs patch
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue-review/sds2; mkdir -p $W && cd $W
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue-review/sds2
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue-review/sds2
aws s3 cp --quiet --recursive $S/ .
PY=/opt/conv/env/bin/python
SPY=/work/agentwork/sds2v54/env/bin/python
[ -x /opt/conv/sds2env/bin/python ] && SPY=/opt/conv/sds2env/bin/python
echo "SPY=$SPY" > env.txt
if [ ! -d v555 ]; then mkdir -p v555 && (cd v555 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/sds2-step-pipeline-v5.5.5.zip z.zip && $PY -c "import zipfile;zipfile.ZipFile('z.zip').extractall('.')" && rm z.zip); fi
rm -rf v555rv; cp -r v555 v555rv; $PY applydiff.py v555rv/sds2-step-pipeline/decode/sds2job.py $W/sds2_v5.4_sparse_layout_7243.diff > patch_apply.txt 2>&1; echo "apply rc=$?" >> patch_apply.txt
diff v555/sds2-step-pipeline/decode/sds2job.py v555rv/sds2-step-pipeline/decode/sds2job.py >> patch_apply.txt
aws s3 cp --quiet patch_apply.txt $R/patch_apply.txt
# --- survey (lite fetch: no piece files) on all jobs of the 4 versions
$PY - <<'EOP' > survey_ids.txt
import json
for j in json.load(open('jobs2xx.json')):
    if j['ver'] in ('7.221','7.233','7.243','7.253'): print(j['id'], j['fpc'])
EOP
JL=""; mkdir -p jobs
while read id fpc; do
  if [ ! -f jobs/$id.lite.done ]; then
    $PY mkfetch2.py $id $fpc $W/jobs/$id lite > /dev/null && \
    sz=$($PY -c "import json;print(sum(i[2] or 0 for i in json.load(open('fetch_$id.json'))))") && \
    if [ "$sz" -lt 600000000 ]; then $PY fetch.py fetch_$id.json 24 > jobs/$id.fetch.json && touch jobs/$id.lite.done; else echo "$id skip lite $sz" >> survey_skipped.txt; fi
  fi
  [ -f jobs/$id.lite.done ] || continue
  mi=$(find jobs/$id -name mem_idx | head -1); [ -z "$mi" ] && { echo "$id no mem_idx" >> survey_skipped.txt; continue; }
  JL="$JL $(cd $(dirname $mi)/.. && pwd)"
done < survey_ids.txt
$SPY layout_diff.py v555/sds2-step-pipeline/decode v555rv/sds2-step-pipeline/decode $JL > survey.jsonl 2> survey.err
aws s3 cp --quiet survey.jsonl $R/survey.jsonl; aws s3 cp --quiet survey.err $R/survey.err; [ -f survey_skipped.txt ] && aws s3 cp --quiet survey_skipped.txt $R/survey_skipped.txt
echo SURVEY_DONE | aws s3 cp - $R/survey.done
# --- stage 2 --verify, base vs patch (full fetch)
export PYTHONUNBUFFERED=1 MPLBACKEND=Agg
[ -f /work/agentwork/sds2v54/env/lib/libexpat.so.1 ] && [ "$SPY" = /work/agentwork/sds2v54/env/bin/python ] && export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
[ -f /opt/conv/sds2env/lib/libexpat.so.1 ] && [ "$SPY" = /opt/conv/sds2env/bin/python ] && export LD_PRELOAD=/opt/conv/sds2env/lib/libexpat.so.1
one() {
  id=$1; v=$2
  JD=$(cd $(dirname $(find $W/jobsf/$id -name mem_idx | head -1))/.. && pwd)
  o=$W/out/$v/$id; rm -rf $o; mkdir -p $o; cd $o
  /usr/bin/time -v timeout 5400 $SPY -u $W/$v/sds2-step-pipeline/decode/sds2_to_step.py "$JD" -o $o/job_stage2.step --stage 2 --verify > $o/log.txt 2> $o/err.txt
  rc=$?
  echo "$id $v rc=$rc $(grep -m1 'Maximum resident' $o/err.txt)" >> $W/out/summary.txt
  [ -f $o/job_stage2.step ] && { grep -v "^FILE_NAME\|^/\* \|FILE_DESCRIPTION" $o/job_stage2.step | md5sum | cut -c1-32 > $o/step_body.md5; ls -l $o/job_stage2.step | awk '{print $5}' > $o/step_bytes.txt; rm -f $o/job_stage2.step; }
  grep -v "^\*\|Transferr" $o/log.txt | tail -60 > $o/log_tail.txt
  for f in log_tail.txt err.txt job_stage2_manifest.json job_stage2_pieces.csv job_stage2_skipped.csv step_body.md5 step_bytes.txt; do [ -f $o/$f ] && aws s3 cp --quiet $o/$f $R/out/$v/$id/$f; done
}
mkdir -p out
for id in a47a130792964d283c4b9ab9 58c969614e6f06bde4ab3d44 6eeedc274302b8e4032f8736 5eed44fe33ca83c72ae2b048 98adc85b7284f4188ad8ad86 9b72c7bcefc4fe11f5e228fa 40e0ff87a224295965571bd3 cd4a45006669d0f11a756e64 2170ca1e8650c3a67f0e72f8 c84d4cc8b8895572bb32ce69; do
  fpc=$($PY -c "import json;print([x['fpc'] for x in json.load(open('jobs2xx.json')) if x['id']=='$id'][0])")
  if [ ! -f jobsf/$id.done ]; then mkdir -p jobsf; $PY mkfetch2.py $id $fpc $W/jobsf/$id > /dev/null && mv fetch_$id.json fetchf_$id.json && $PY fetch.py fetchf_$id.json 24 > jobsf/$id.fetch.json && touch jobsf/$id.done; fi
done
N=0
for id in a47a130792964d283c4b9ab9 58c969614e6f06bde4ab3d44 6eeedc274302b8e4032f8736 5eed44fe33ca83c72ae2b048 98adc85b7284f4188ad8ad86 9b72c7bcefc4fe11f5e228fa 40e0ff87a224295965571bd3 cd4a45006669d0f11a756e64 2170ca1e8650c3a67f0e72f8 c84d4cc8b8895572bb32ce69; do
  [ -f jobsf/$id.done ] || { echo "$id fetch failed" >> out/summary.txt; continue; }
  for v in v555 v555rv; do one $id $v & N=$((N+1)); if [ $((N % 4)) -eq 0 ]; then wait; fi; done
done
wait
aws s3 cp --quiet out/summary.txt $R/out/summary.txt
echo DONE | aws s3 cp - $R/stage2.done
