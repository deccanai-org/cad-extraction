#!/bin/bash
# z3conv end game (operator, annotationprod-publish). Steps are idempotent; run in order:
#   bash endgame.sh final-prep   -> coordinator writes _state/conv/final/jobs.json (final pass jobs; boxes assist 'final' when idle)
#   bash endgame.sh final        -> coordinator builds the FINAL index / class lists / conv_status (final=true) and leaves FINAL_OK
#   bash endgame.sh release      -> remove every hold flag: workers write DONE when their queues are empty -> boxes power off
#   bash endgame.sh finish       -> coordinator powers off after its next round (needs FINAL_OK)
set -e
export AWS_PROFILE=${AWS_PROFILE:-annotationprod-publish}
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
case $1 in
  final-prep) echo '{}' | aws s3 cp --quiet - $CTL/coord/final_prep; echo "final_prep set";;
  final)      echo '{}' | aws s3 cp --quiet - $CTL/coord/final; echo "final set";;
  release)    for p in ifc db1 sds2 grade final; do aws s3 rm --quiet $CTL/$p/hold || true; done; echo "holds removed";;
  finish)     echo '{}' | aws s3 cp --quiet - $CTL/coord/finish; echo "finish set";;
  *) echo "usage: endgame.sh final-prep|final|release|finish"; exit 1;;
esac
