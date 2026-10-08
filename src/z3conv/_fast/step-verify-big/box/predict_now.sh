#!/bin/bash
# BOX-A: class prediction over every applicable record in s3 final/results (phases 2-4 so far), coordinator code (patched copy)
cd /work/agentwork/step-verify-big && rm -rf pred_now && mkdir -p pred_now/results
aws s3 cp --only-show-errors --recursive s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final/results/ pred_now/results/
INDEX_WORK=/work/agentwork/step-verify-big/index_work timeout 600 /opt/conv/env/bin/python pkg/predict_class.py pred_now/results pred_now/predict.json > pred_now/predict.txt 2>&1
aws s3 cp --only-show-errors pred_now/predict.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final/predict_now.json
tail -30 pred_now/predict.txt
/opt/conv/env/bin/python -c "
import json
d = json.load(open('pred_now/predict.json'))
for m in d['models']:
    if m.get('class_after') == 1 or m['id'] in d['summary']['lifted_to_class1']:
        print('CLASS1', m['id'], m.get('class_before'), '->', m.get('class_after'), m.get('graded_by_after'), m.get('solids_after'), m.get('coverage_all_after'), m.get('corpus_after'))
"
