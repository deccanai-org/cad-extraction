#!/bin/bash
# finish_pl.sh: when h_nb is complete stop run5 before its i pass (h->i changes only bolt code; bolts are off here), wait for j_nb and
# jfix_nb (extra job), then parts_lost with KITS b0,c,f,g,h,j,jfix
cd /work/agentwork/audit-db1-codes
n() { ls dec/$1/ 2>/dev/null | grep -c '[0-9a-f].json$'; }
until [ "$(n h_nb)" -ge 106 ]; do sleep 20; done
for p in $(pgrep -f "run5.sh|decode_all.py b0,c,f,g,h,i,j,jfix|kits/i/convert_one.py src/.* dec/i_nb"); do c=$(readlink /proc/$p/cwd 2>/dev/null); [ "$c" = "$PWD" ] && kill $p; done
until [ "$(n j_nb)" -ge 106 ] && [ "$(n jfix_nb)" -ge 106 ]; do sleep 20; done
sed -i "s/KITS = \['b0', 'c', 'f', 'g', 'h', 'i', 'j', 'jfix'\]/KITS = ['b0', 'c', 'f', 'g', 'h', 'j', 'jfix']/; s/for k in 'bcfghij'}/for k in 'bcfghj'}/" parts_lost.py
RUNTAG=fin bash phase.sh parts_lost
echo finished > logs/finish_pl.done
aws s3 cp logs/finish_pl.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-db1-codes/logs/finish_pl.done --only-show-errors
