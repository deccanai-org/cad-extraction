#!/bin/bash
# Mac: upload the deliverable files (tool, docs, patches, test, box scripts, evidence JSON) to the fixes dirs (small files only)
D=/Users/dhiren/Downloads/Deccan/z3conv/_fast/step-verify-big
for PIPE in grade ifc; do
  T=s3://annotationprod/cad-disk-extract/_control/z3conv/$PIPE/fixes/step-verify-big
  for f in step_verify_big.py to_final_result.py equiv_compare.py README.md; do AWS_PROFILE=annotationprod-publish aws s3 cp --only-show-errors $D/$f $T/$f; done
  for f in integration/grade_worker.patch integration/ifc_worker.patch integration/build_index_apply_final.patch integration/grade/worker.py integration/ifc/worker.py \
           integration/test/test_check_step.py integration/test/stub_convfleet.py integration/test/itest_box.log; do AWS_PROFILE=annotationprod-publish aws s3 cp --only-show-errors $D/$f $T/$f; done
  for f in jobq.py make_tasks.py make_tasks_p4.py equiv_summary.py post.py predict_class.py spec_p3.py run_main.sh post.sh run_p4.sh run_sampling.sh \
           tasks_sampling.json spec_sampling.json p4_targets.json covered.json; do AWS_PROFILE=annotationprod-publish aws s3 cp --only-show-errors $D/box/$f $T/box/$f; done
  AWS_PROFILE=annotationprod-publish aws s3 cp --only-show-errors --recursive $D/equiv/box $T/evidence/equiv/
  for f in models.json runs.json predict.json predict.txt post.txt nonpos_where.json; do [ -f $D/final/$f ] && AWS_PROFILE=annotationprod-publish aws s3 cp --only-show-errors $D/final/$f $T/evidence/final/$f; done
  AWS_PROFILE=annotationprod-publish aws s3 cp --only-show-errors --recursive $D/final/results $T/evidence/final/results/
  AWS_PROFILE=annotationprod-publish aws s3 cp --only-show-errors --recursive $D/final_stale/results $T/evidence/final_stale/results/
done
AWS_PROFILE=annotationprod-publish aws s3 ls --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/grade/fixes/step-verify-big/ | wc -l
AWS_PROFILE=annotationprod-publish aws s3 ls --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/fixes/step-verify-big/ | wc -l
