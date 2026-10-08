#!/bin/bash
# Repair the coordinator's status repo clone (detached HEAD after a pull --rebase that raced the Mac publisher). Only touches
# /opt/status/cad-extract-status; its local auto-commits are regenerated stats and are re-made next round.
cd /opt/status/cad-extract-status || exit 1
systemctl stop z3status
git rebase --abort 2>/dev/null; git merge --abort 2>/dev/null
git fetch -q origin
B=$(git remote show origin | sed -n 's/.*HEAD branch: //p'); B=${B:-main}
git checkout -q -B $B origin/$B && git branch -q --set-upstream-to=origin/$B $B
git status -sb | head -2
systemctl start z3status
sleep 150
git log --format='%h %an %s' -3
git status -sb | head -1
git log origin/$B --format='%h %an %s' -2
