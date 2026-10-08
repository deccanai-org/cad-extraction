#!/bin/bash
W=/work/agentwork/sds2-weights-failures; J=$W/j2; mkdir -p $J && cd $J
for f in runana2.py w553a.tgz sds2-step-pipeline-v5.5.3.zip ids_t.txt ids_tb.txt; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/j2/$f $J/$f; done
cp $J/runana2.py $W/runana2.py
rm -rf $J/b553 $J/w553a && mkdir -p $J/b553 $J/w553a
(cd $J/b553 && $W/env/bin/python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall('.')" $J/sds2-step-pipeline-v5.5.3.zip)
tar xzf $J/w553a.tgz -C $J/w553a
sha256sum $J/sds2-step-pipeline-v5.5.3.zip
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py t553w $J/ids_t.txt conv:$J/w553a/sds2-step-pipeline 5 110 > $J/t553w.out 2>&1" > /dev/null 2>&1 < /dev/null &
setsid nohup bash -c "/opt/conv/env/bin/python $W/runana2.py t553b $J/ids_tb.txt conv:$J/b553/sds2-step-pipeline 3 60 > $J/t553b.out 2>&1" > /dev/null 2>&1 < /dev/null &
sleep 20; cat $J/t553w.out $J/t553b.out; tail -3 $J/t553w.runlog $J/t553b.runlog 2>/dev/null; ls $J
