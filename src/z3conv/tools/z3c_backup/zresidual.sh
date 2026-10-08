#!/bin/bash
# Phase-2 residual census (lead: Disk-1/2 residual check + data-2 census only). READ-ONLY on everything; writes ONLY
# bim cad-disk-extract/_state/phase2/residual.json. No deletes.
#  - Disk-1/2: IFC / DB1 contents (sha256) of the 2,476 dataset/main packages vs the data-3 + data-4 content lists -> residual
#  - data-2: file counts by kind (derived Smart 3D IFC; any customer IFC / DB1 / STEP / NWD)
# Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/zresidual.sh 300
#  - kit: z3conv/scan/zresidual.py from the control prefix (deploy.sh scan); one-off transient unit zresidual at nice 19; idempotent
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; O=/opt/zcensus; K=$O/kit
mkdir -p $O $K
if [ -f $O/finished.resid ]; then echo "finished $(cat $O/finished.resid)"; tail -n 3 $O/log.resid.txt | cut -c1-8000; exit 0; fi
if systemctl is-active -q zresidual; then echo "running since $(cat $O/started.resid)"; tail -n 3 $O/log.resid.txt; exit 0; fi
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/scan/zresidual.py $K/zresidual.py || exit 1
sha256sum $K/zresidual.py
date -u +%FT%TZ > $O/started.resid
systemctl reset-failed zresidual 2>/dev/null
systemd-run --unit=zresidual --collect --nice=19 --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "$PY $K/zresidual.py > $O/log.resid.txt 2>&1; echo rc=\$? >> $O/log.resid.txt; date -u +%FT%TZ > $O/finished.resid"
sleep 60
tail -n 3 $O/log.resid.txt
