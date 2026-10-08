#!/bin/bash
# BOX-A: free the inputs / work dirs of the finished phases 1-3 (phase 4 uses in/Q* and wd/Q*; out/, ref/, logs/ are kept)
cd /work/agentwork/step-verify-big
du -sh in wd 2>/dev/null
rm -f in/m1.step in/m2.step in/m3.step in/L1.step in/L2.step in/F1.step in/F2.step in/B1.step in/B2.step in/P*.step
find wd -mindepth 1 -maxdepth 1 ! -name 'Q*' -exec rm -rf {} + 2>/dev/null
rm -rf itest pred_now index_work
du -sh in wd /work/agentwork/step-verify-big 2>/dev/null; df -h /work | tail -1
