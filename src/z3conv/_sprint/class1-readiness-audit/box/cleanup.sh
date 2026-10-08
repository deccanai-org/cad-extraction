cd /work/agentwork/class1-readiness-audit || exit 0
pgrep -f "class1-readiness-audit|job/aud.py|job/fullconv.py" -a | grep -v pgrep | head
du -sh . 2>/dev/null
rm -rf wk/*/*/model.ifc wk/*/*/model.stp arch src/*.db1.part
find wk -name "*.ifc" -delete 2>/dev/null; find wk -name "*.stp" -delete 2>/dev/null
rm -f src/*.db1
du -sh . 2>/dev/null
