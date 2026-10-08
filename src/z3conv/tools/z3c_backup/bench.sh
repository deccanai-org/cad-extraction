#!/bin/bash
# bench.sh - run work on a cloud workbench (64 cores, Mumbai) instead of the local Mac.
#
#   bench.sh INSTANCE push NAME LOCAL_DIR          upload LOCAL_DIR (code, schedules - not big outputs) to the bench as /opt/bench/NAME
#   bench.sh INSTANCE run  NAME 'COMMAND'          start COMMAND detached in /opt/bench/NAME; prints a RUN id
#   bench.sh INSTANCE wait NAME RUN [SECONDS]      wait up to SECONDS (default 540) for RUN; prints status + log tail
#   bench.sh INSTANCE pull NAME SUBDIR LOCAL_DIR   copy /opt/bench/NAME/SUBDIR back to LOCAL_DIR (via S3)
#   bench.sh INSTANCE sh   'COMMAND'               quick synchronous command (output is cut at ~2,400 characters)
#
# On the bench: python /opt/pm/venv/bin/python (build123d 0.13, ifcopenshell 0.9); toolkit /opt/pm/kit, /opt/pm/tools
# (= the current v8 kit); sources /opt/pm/src/<stem>.ifc|.ifczip|.step; latest full-run schedules + verification
# /opt/pm/out_v7/<stem>/ (benches launched 10-07 from 10:40 PDT: /opt/pm/out_v9/<stem>/ = the published v9 results, code = v9);
# models list /opt/pm/models.json; 64 cores, 512 GB RAM. Set REGION=ap-south-2 for the Hyderabad benches.
export AWS_PROFILE=${AWS_PROFILE:-annotationprod-publish}
I=$1; OP=$2; NAME=$3
R=${REGION:-ap-south-1}          # Hyderabad benches: REGION=ap-south-2 bash /tmp/z3c/bench.sh ...
S3IN=s3://annotationprod/cad-disk-extract/_control/z3conv/coord_tmp/pm/bench/$NAME     # Mac writes, bench reads
S3=s3://bim-proprietary-data/cad-disk-extract/_state/pm_samples/bench/$NAME                 # bench writes, Mac reads
ssm() { local f; f=$(mktemp); printf '%s\n' "$1" > "$f"; bash /tmp/z3c/ssmcli.sh $R "$I" "$f" "${2:-300}"; local rc=$?; rm -f "$f"; return $rc; }
case "$OP" in
  push)
    SRC=$4; T=$(mktemp -d)/in.tgz
    (cd "$SRC" && COPYFILE_DISABLE=1 tar czf "$T" --exclude='*.step' --exclude='*.stp' --exclude='*.brep' --exclude='*.pkl' --exclude='__pycache__' .) || exit 1
    aws s3 cp --only-show-errors "$T" "$S3IN/in.tgz" || exit 1
    ssm "mkdir -p /opt/bench/$NAME && cd /opt/bench/$NAME && aws s3 cp --quiet $S3IN/in.tgz /tmp/in_$NAME.tgz && tar xzf /tmp/in_$NAME.tgz 2>/dev/null; echo pushed \$(du -sh . | cut -f1)" 300
    ;;
  run)
    CMD=$4; RUN=r$(date +%s)
    B64=$(printf '%s' "$CMD" | base64 | tr -d '\n')
    ssm "mkdir -p /opt/bench/$NAME && cd /opt/bench/$NAME && echo $B64 | base64 -d > .cmd_$RUN.sh && (export PY=/opt/pm/venv/bin/python; setsid nohup bash -c 'bash .cmd_$RUN.sh > run_$RUN.log 2>&1; echo \$? > run_$RUN.rc' > /dev/null 2>&1 < /dev/null &) ; sleep 1; echo started $RUN" 120
    echo "RUN=$RUN"
    ;;
  wait)
    RUN=$4; MAX=${5:-540}; end=$((SECONDS+MAX))
    while :; do
      out=$(ssm "cd /opt/bench/$NAME; if [ -f run_$RUN.rc ]; then echo DONE rc=\$(cat run_$RUN.rc); else echo RUNNING; fi; tail -c 1800 run_$RUN.log" 120)
      echo "$out" | grep -q "^DONE" && { echo "$out"; exit 0; }
      [ $SECONDS -gt $end ] && { echo "$out"; echo "(still running - call wait again)"; exit 2; }
      sleep 20
    done
    ;;
  pull)
    SUB=$4; DST=$5; mkdir -p "$DST"
    ssm "cd /opt/bench/$NAME && aws s3 sync --only-show-errors '$SUB' $S3/out/'$SUB' && echo synced" 600 || exit 1
    aws s3 sync --only-show-errors "$S3/out/$SUB" "$DST"
    ;;
  sh)
    ssm "$NAME" 300   # here NAME is the command
    ;;
  *) sed -n '2,12p' "$0"; exit 1;;
esac
