#!/bin/bash
# stop the superseded SDS2 canary units on this box (v5.5.10-rc / v5.5.9b baselines; rc11 void per the SDS2 fixer) and the job
# processes they started (TMPDIR in a canary work dir); production workers are untouched
for u in $(systemctl list-units --all --plain --no-legend 'z3canary-*' | awk '{print $1}'); do echo "stop $u ($(systemctl is-active $u))"; systemctl stop $u; done
sleep 3
n=0
for d in /proc/[0-9]*; do
  p=${d#/proc/}
  if tr '\0' '\n' < $d/environ 2>/dev/null | grep -q '^TMPDIR=/scratch/conv/canary_\|^TMPDIR=/opt/conv/work/canary_'; then
    echo "kill $p $(cat $d/comm 2>/dev/null)"; kill $p 2>/dev/null; n=$((n+1))
  fi
done
echo "killed $n canary job processes"; uptime
