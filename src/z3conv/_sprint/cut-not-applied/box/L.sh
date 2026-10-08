#!/bin/bash
# L.sh JOBNAME [fg TIMEOUT] : stage box/ to S3 and start jobs/JOBNAME.sh on BOX-B (background unless "fg")
set -u
H=/Users/dhiren/Downloads/Deccan/z3conv/_sprint/cut-not-applied/box
J=$1; MODE=${2:-bg}; T=${3:-120}
export AWS_PROFILE=annotationprod-publish
aws s3 sync --quiet --delete $H/ s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/cut-not-applied/ --exclude "*.pyc" --exclude "__pycache__/*" --exclude "L.sh" --exclude "F.sh" --exclude "*.out" || exit 1
R=$(mktemp /tmp/cna_run.XXXX)
cat > $R <<EOS
#!/bin/bash
W=/work/agentwork/cut-not-applied; mkdir -p \$W/logs; cd \$W
aws s3 sync --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/cut-not-applied/ \$W/stage/
cp -r \$W/stage/tools \$W/stage/jobs \$W/ 2>/dev/null
if [ "$MODE" = fg ]; then bash \$W/jobs/$J.sh 2>&1 | tail -c 20000; else
setsid nohup bash \$W/jobs/$J.sh > \$W/logs/$J.log 2>&1 < /dev/null & echo "started $J pid \$!"; fi
EOS
bash /tmp/zen/ssmcli.sh ap-south-1 i-076e73980707c7dbe $R $T
rm -f $R
