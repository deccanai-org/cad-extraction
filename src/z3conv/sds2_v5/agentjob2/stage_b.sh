#!/bin/bash
# BOX-B: re-stage the SDS2 work (trees, control + evidence jobs), then SOCORRO (v557h, v558b) + Spectrum (v558b)
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f558
for f in getjob.py jobs.json getjob3k.py maxrss.py v557h.tgz v558b.tgz; do aws s3 cp --quiet $C/$f $W/$f; done
for v in v557h v558b; do rm -rf $W/$v; mkdir -p $W/$v && tar xzf $W/$v.tgz -C $W/$v; done
mkdir -p $W/jobs $W/jobs3
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
g3() { k=$(aws s3 ls s3://bim-proprietary-data/$F/$1 | awk '{print $4}' | head -1); [ -d $W/jobs3/$2 ] || $W/env/bin/python $W/getjob3k.py $F/$k $W/jobs3 $2 > /dev/null 2>&1; }
g3 8566eef0 e8_8566eef0 & g3 319570f4 t_319570f4 & g3 ef345b81 e8_ef345b81 & g3 fb1cae54 19002-IMS6_JOB_fb1cae &
g3 0535bdbb j_0535bdbb & g3 4c381a54 j_4c381a54 & wait
cd $W/jobs
if [ ! -d $W/jobs/GMS ]; then
  aws s3 cp --only-show-errors "s3://bim-proprietary-data/Disk-2/Completed_Projects_Data/MT15_061 (The Greenwood Middle School)/18.ABM/01) ABM_122115/GMS ABM  122115_JOB.zip" gms.zip
  $W/env/bin/python -c "import zipfile; zipfile.ZipFile('gms.zip').extractall('gmsx')" && mv "gmsx/GREENWOOD MIDDLE SCHOOL_JOB" GMS && rm -rf gms.zip gmsx
fi
for id in 8164be24 0f97287d a6168a5a baa236aa; do ls -d $W/jobs/*_${id:0:6} > /dev/null 2>&1 || $W/env/bin/python $W/getjob.py $id $W/jobs > /dev/null 2>> $W/fetch.err; done
cd $W; ls $W/jobs $W/jobs3 > $W/stage_b.txt; aws s3 cp --quiet $W/stage_b.txt $R/stage_b.txt
run() {
  V=$1; J=$2; ST=${3:-2}; N=$(basename $J); O=$W/f558/$V/$N; rm -rf $O; mkdir -p $O
  timeout 14400 $W/env/bin/python $W/maxrss.py "$N $V" $W/f558/rss_b.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$V/$N/ --exclude "*.step" --exclude "convert.log"; rm -f $O/*.step
}
export -f run; export W R
mkdir -p $W/f558
{ echo "v558b $W/jobs3/e8_8566eef0 2"; echo "v557h $W/jobs3/e8_8566eef0 2"; echo "v558b $W/jobs3/t_319570f4 2"; } | xargs -P 3 -L 1 bash -c 'run "$0" "$1" "$2"'
date -u +%FT%TZ > $W/STAGEB_DONE; aws s3 cp --quiet $W/STAGEB_DONE $R/STAGEB_DONE
