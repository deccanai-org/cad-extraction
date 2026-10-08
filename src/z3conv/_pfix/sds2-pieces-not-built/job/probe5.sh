cd /work/agentwork/sds2v54 && cat v55.sh; echo; ls -la out/v55/*/ | head -40
for j in test_4b7e6e GF_691744 01-NOV-21_RH_PALO_ALTO_JOB_88fb6a KJL_f3e696; do echo "=== $j"; cat out/v55/$j/rc.txt 2>/dev/null; tail -25 out/v55/$j/${j}_stage2.log 2>/dev/null | cut -c1-300; done
