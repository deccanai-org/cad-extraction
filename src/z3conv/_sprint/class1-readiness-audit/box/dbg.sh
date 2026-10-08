cd /work/agentwork/class1-readiness-audit
ls src | grep _sib | wc -l; cat $(ls src/*_sib/*.err | head -3) 2>&1 | head -5; ls src/*_sib/*.err 2>/dev/null | wc -l
ls kit_k2 | head -40
(cd kit_k2 && patch -p0 --dry-run < ../job/htr.patch) 2>&1 | tail -5
