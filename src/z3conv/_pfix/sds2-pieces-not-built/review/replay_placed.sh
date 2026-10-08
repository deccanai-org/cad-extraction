#!/bin/bash
# replay on the pieces actually placed (pieces.csv + skipped.csv of both A/B runs), per job once both runs are done
W=/work/agentwork/sds2-pieces-not-built-review; cd $W
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built-review/replay_placed
PY=/work/agentwork/sds2-pieces-not-built/env/bin/python
mkdir -p $W/replay_placed
one() { N=$1; O=$W/replay_placed/$N; [ -f $O.done ] && return
  cut -d, -f3 $W/ab/v553/$N/*_pieces.csv $W/ab/v553p/$N/*_pieces.csv $W/ab/v553/$N/*_skipped.csv $W/ab/v553p/$N/*_skipped.csv 2>/dev/null | grep -E '^[0-9]+$' | sort -u > $O.ids
  OMP_NUM_THREADS=1 timeout 7200 $PY $W/stage/replay.py $W/jobs/$N $O.jsonl ${NMAX:-4000} $O.ids 2> $O.err; echo $? > $O.done
  aws s3 cp --quiet $O.jsonl $R/$N.jsonl; }
export -f one; export W R PY NMAX
while true; do
  todo=""
  for n in $(cat $W/out/ab_dirs.txt $W/out/ab2_dirs.txt 2>/dev/null); do
    [ -f $W/replay_placed/$n.done ] && continue
    if [ -f $W/ab/v553/$n/rc.txt ] && [ -f $W/ab/v553p/$n/rc.txt ]; then todo="$todo $n"; fi
  done
  [ -n "$todo" ] && echo $todo | tr ' ' '\n' | xargs -P ${RPAR:-4} -L 1 bash -c 'one "$0"'
  if [ -f $W/out/AB_DONE ] && [ -f $W/out/AB2_DONE ]; then
    left=0; for n in $(cat $W/out/ab_dirs.txt $W/out/ab2_dirs.txt); do [ -f $W/replay_placed/$n.done ] || left=1; done
    [ $left = 0 ] && break
  fi
  sleep 60
done
date -u +%FT%TZ > $W/out/REPLAY_PLACED_DONE; aws s3 cp --quiet $W/out/REPLAY_PLACED_DONE $R/REPLAY_PLACED_DONE
