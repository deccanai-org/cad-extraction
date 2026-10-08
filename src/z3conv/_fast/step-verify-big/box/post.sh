#!/bin/bash
# BOX-A: collect final-pass readback records + class prediction (coordinator code, read-only) -> s3 agentwork/step-verify-big/final/
cd /work/agentwork/step-verify-big
for f in post.py predict_class.py spec_p3.py equiv_summary.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big/$f pkg/$f; done
aws s3 cp --only-show-errors --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big/coord_copy/ pkg/coord_copy/
rm -rf final final_stale && mkdir -p final
# B1 / B2 (> 1 GB, reused): final-pass records with the join against the grade census (src_parts)
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv
for spec in "B1 g24 6c34303149ba9806c3285cf9e1d9a6e62ed0e708da8c26af00bc6968a88a22d5 cad-disk-extract/conversions/ifc-step/ad0de6fbb5c943534f74af1d3aa0195e_124979893.stp" \
            "B2 x24 a358f0c34f66fb99d548baf24d83f238ab9a6a2c95129a49883e0c2ce0e913bd cad-disk-extract/conversions/ifc-step/2e0d8fce2af83890da944354f4c8ca70_707157025.stp"; do
  set -- $spec
  aws s3 cp --only-show-errors $ST/grade/detail/ifc-$3.src_parts.jsonl.gz ref/$1.src_parts.jsonl.gz
  [ "$2" != x24 ] && cp out/$1/s_$2.json out/$1/s_x24.json && cp out/$1/s_$2.parts.jsonl.gz out/$1/s_x24.parts.jsonl.gz && cp logs/s_$1_$2.rusage.json logs/s_$1_x24.rusage.json
  /opt/conv/env/bin/python pkg/to_final_result.py out/$1/s_x24.json out/$1/s_x24.parts.jsonl.gz --pipeline ifc --model-id $3 --step-key $4 \
      --src-parts ref/$1.src_parts.jsonl.gz --grade-join pkg/grade_join.py -o out/$1/final_readback_x24.json > out/$1/final_readback_x24.json.log 2>&1
  cat out/$1/final_readback_x24.json.log
done
/opt/conv/env/bin/python pkg/post.py > final/post.txt 2>&1
INDEX_WORK=/work/agentwork/step-verify-big/index_work timeout 600 /opt/conv/env/bin/python pkg/predict_class.py final/results final/predict.json > final/predict.txt 2>&1
/opt/conv/env/bin/python pkg/spec_p3.py pkg/spec_p3.json > final/spec_p3.txt 2>&1
/opt/conv/env/bin/python pkg/equiv_summary.py pkg/spec_p3.json out/equiv_p3.json > out/equiv_p3.txt 2>&1
aws s3 cp --only-show-errors out/equiv_p3.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/out/equiv_p3.json
aws s3 cp --only-show-errors out/equiv_p3.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/out/equiv_p3.txt
for f in final_stale/results/*.json; do aws s3 rm --only-show-errors s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final/results/$(basename $f); done
for f in final_stale/detail/*.gz; do aws s3 rm --only-show-errors s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final/detail/$(basename $f); done
aws s3 cp --only-show-errors --recursive final s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final/
aws s3 cp --only-show-errors --recursive final_stale s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final_stale/
cat final/post.txt final/spec_p3.txt
/opt/conv/env/bin/python -c "
import json, collections
d = json.load(open('out/equiv_p3.json'))
v = collections.Counter(s['verdict'] for r in d.values() for s in r.get('stream_vs_full', []))
n = sum(r['roots'] for r in d.values()); ident = sum(s['parts_identical'] for r in d.values() for s in r.get('stream_vs_full', []))
print('phase-3 vs grader stored read-back:', dict(v), 'roots', n, 'identical', ident)
for m, r in d.items():
    for s in r.get('stream_vs_full', []):
        if s['verdict'] != 'identical': print('  ', m, s['verdict'], s['parts_differing'], s['unexplained_examples'][:2])
"
tail -40 final/predict.txt
