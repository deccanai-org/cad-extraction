#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; cd $J
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/gradecheck2.py $J/
P=$J/w553b/sds2-step-pipeline; B=$J/b553/sds2-step-pipeline
args=""
for t in t2w wrw liftw ssjw bgw s54; do [ -d $J/out/$t ] && args="$args $J/out/$t:$t:$( [ $t = ssjw ] && echo $J/w553t/sds2-step-pipeline || ([ $t = s54 ] && echo $J/w54b/sds2-step-pipeline || echo $P)):new"; done
for t in wrb liftb t553b; do [ -d $J/out/$t ] && args="$args $J/out/$t:$t:$B:cur"; done
timeout 900 /opt/conv/env/bin/python gradecheck2.py gc.json $args 2>&1 | tail -3
aws s3 cp --only-show-errors gc.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures/j2/gc.json && echo up
