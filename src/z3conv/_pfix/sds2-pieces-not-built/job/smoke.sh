W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/trees.tgz stage/trees.tgz
rm -rf $W/trees && mkdir -p $W/trees && tar xzf $W/stage/trees.tgz -C $W/trees && ln -sfn $W/base54/sds2-step-pipeline $W/trees/a
mkdir -p $W/smoke
for n in 888_Boylston_Embeds_Only_b9c720 BG_Residental_tower_Job_0bda20 hk_86b590 THERMOFISHER_JOB_bff8f8; do
  ( mkdir -p $W/smoke/$n && cd $W/smoke/$n && OMP_NUM_THREADS=1 MPLBACKEND=Agg timeout 900 $W/env/bin/python -u $W/trees/b/decode/sds2_to_step.py $W/jobs/$n -o $W/smoke/$n/${n}_stage2.step --stage 2 > convert.log 2>&1; echo "rc=$?" >> convert.log ) &
done; wait
for n in 888_Boylston_Embeds_Only_b9c720 BG_Residental_tower_Job_0bda20 hk_86b590 THERMOFISHER_JOB_bff8f8; do
  echo "=== $n"; grep -a "rc=\|not built\|manifest:\|Traceback\|Error" $W/smoke/$n/convert.log | cut -c1-400 | tail -6
  python3 -c "
import json; m=json.load(open('$W/smoke/$n/${n}_stage2_manifest.json')); s=m['skipped']; print(' skipped', s['total'], s['by_reason'], s.get('needed'), 'src_absent', s.get('source_absent'), 'table_empty', m['counts'].get('pieces_exact_without_table_data'))" 2>&1 | cut -c1-700
done
