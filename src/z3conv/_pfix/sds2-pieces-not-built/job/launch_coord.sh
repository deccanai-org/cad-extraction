mkdir -p /work/agentwork/sds2-pieces-not-built/stage /work/agentwork/sds2-pieces-not-built/out && cd /work/agentwork/sds2-pieces-not-built
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/coord_ab.sh stage/coord_ab.sh
setsid nohup bash stage/coord_ab.sh > out/coord_ab.log 2>&1 < /dev/null &
sleep 1; echo launched
