#!/bin/bash
# v5.5.4 regression: control (v554g vs f553 v553b), 7.3xx fallback jobs (v553b vs v554g), CSU, prior evidence, NC1 opt-in
W=/work/agentwork/sds2v54; cd $W
export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg OMP_NUM_THREADS=1
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/f554
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
aws s3 cp --quiet $C/v554g.tgz $W/v554g.tgz; rm -rf $W/v554g; mkdir -p $W/v554g && tar xzf $W/v554g.tgz -C $W/v554g
F=cad-disk-extract/zenitude-data-3/_state/conv/sds2/files
NC1C=/work/agentwork/sds2-recall-nc1/nc1cache
# NC1 jobs: job folder + pcm_list + NC1 files + job name
$W/env/bin/python - <<'P'
import json, os, gzip, shutil, boto3, subprocess
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'; F = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/'
W = '/work/agentwork/sds2v54'; pairs = json.load(open(f'{W}/nc1/eval_pairs.json'))
for jid in ('7b40c0c5683f62cc2f382c90', '425c2f6c4282287cc9ffdc30', '6e9e3214c04ce23fdda24038'):
    key = s3.list_objects_v2(Bucket=B, Prefix=F + jid[:8])['Contents'][0]['Key']
    mf = json.loads(gzip.decompress(s3.get_object(Bucket=B, Key=key)['Body'].read()))
    k = next(f['key'] for f in mf if f['p'].replace('\\', '/').lower().endswith('main/jsetup') and f.get('key'))
    root = k[:-len('main/jsetup')]; name = root.rstrip('/').split('/')[-1]
    jd = f'{W}/jobs3/nc_{jid[:8]}'
    if not os.path.isdir(jd + '/mem'):
        subprocess.run([f'{W}/env/bin/python', f'{W}/getjob3k.py', key, f'{W}/jobs3', f'nc_{jid[:8]}'], capture_output=True)
    os.makedirs(jd + '/pcm', exist_ok=True)
    open(jd + '/pcm/pcm_list', 'wb').write(s3.get_object(Bucket=B, Key=root + 'pcm/pcm_list')['Body'].read())
    nd = f'{W}/nc1/src_{jid[:8]}'; os.makedirs(nd, exist_ok=True)
    for i, e in enumerate(pairs.get(jid, [])):
        p = os.path.join('/work/agentwork/sds2-recall-nc1/nc1cache', e['sha256'][:2], e['sha256'])
        if os.path.exists(p): shutil.copy(p, os.path.join(nd, f'{i}_{os.path.basename(e["path"])}'))
    open(f'{W}/nc1/name_{jid[:8]}', 'w').write(name)
P
run() {
  V=$1; J=$2; ST=${3:-2}; X=$4; N=$(basename $J); TAG=$V${X:+_nc1}; O=$W/f554/$TAG/$N; rm -rf $O; mkdir -p $O
  EXTRA=""; if [ -n "$X" ]; then EXTRA="--nc1 $W/nc1/src_${N#nc_}"; export SDS2_JOB_NAME="$(cat $W/nc1/name_${N#nc_})"; fi
  timeout 10800 $W/env/bin/python $W/maxrss.py "$N $TAG" $W/f554/rss.jsonl $W/env/bin/python -u $W/$V/sds2-step-pipeline/decode/sds2_to_step.py $J -o $O/${N}_stage$ST.step --stage $ST --verify $EXTRA > $O/convert.log 2>&1
  grep -av '^\*\|Transferr\|^\s*$\|\[0m\|\[32;1m' $O/convert.log > $O/${N}_stage$ST.log
  aws s3 cp --quiet --recursive $O $R/$TAG/$N/ --exclude "*.step" --exclude "convert.log"
  rm -f $O/*.step
}
export -f run
export W R
mkdir -p $W/f554
{
for J in $W/jobs/METHODIST* $W/jobs/GMS $W/jobs/AGNEWS_HS_Bldg-T* $W/jobs/TYSONS* $W/jobs/160920_AGNEWS*; do echo "v554g $J 2"; done
echo "v554g $W/jobs3/19002-IMS6_JOB_fb1cae 1"
for id in 5ce1bf4b f16781fc d1bf0fc7 9ab5fb14 319570f4 859650c1 00b3fcb9; do echo "v553b $W/jobs3/t_$id 2"; echo "v554g $W/jobs3/t_$id 2"; done
echo "v554g $W/jobs3/csu 2"; echo "v554g $W/jobs3/ev_7699a4a7 2"; echo "v554g $W/jobs3/ev_23c10723 2"
for id in 7b40c0c5 425c2f6c 6e9e3214; do echo "v554g $W/jobs3/nc_$id 2"; echo "v554g $W/jobs3/nc_$id 2 nc1"; done
} | xargs -P 7 -L 1 bash -c 'run "$0" "$1" "$2" "$3"'
aws s3 cp --quiet $W/f554/rss.jsonl $R/rss.jsonl
date -u +%FT%TZ > $W/F554_DONE; aws s3 cp --quiet $W/F554_DONE $R/F554_DONE
