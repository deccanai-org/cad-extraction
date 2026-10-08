cd /work/agentwork/sds2v54 && ls -la | head -80
for f in a55.sh c541.sh g.sh final.sh conv.sh; do echo "=== $f"; cat $f 2>/dev/null | head -30; done
ls -la c541 2>/dev/null | head; ls out* 2>/dev/null | head
find . -maxdepth 3 -name "*GF*" -o -maxdepth 3 -name "*test_4b7e6e*" | head -20
