W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/classify_ref.py stage/classify_ref.py
mkdir -p out/cls
for j in DFGH_010ffa P-02_036a18 jklu_573093 bbbn_f9466d jfkf_23c107; do
  timeout 250 $W/env/bin/python stage/classify_ref.py $W/base54/sds2-step-pipeline/decode $W/jobs/$j out/cls/$j.json 25 > out/cls/$j.log 2>&1 &
done; wait
for j in DFGH_010ffa P-02_036a18 jklu_573093 bbbn_f9466d jfkf_23c107; do python3 -c "
import json,sys; d=json.load(open('out/cls/$j.json')); print(d['job'], d['placed_sids'], d['placed_inst'], 'named_dropped', d['named_dropped_inst'], d['sec']); print('  sids', d['sids_by_class']); print('  inst', d['inst_by_class']); print('  occ', d['occ_sample'])" 2>&1 | head -8; done
