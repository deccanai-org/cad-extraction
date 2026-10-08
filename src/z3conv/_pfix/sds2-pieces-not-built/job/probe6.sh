cd /work/agentwork/sds2v54/out/v55 && cat GF_691744/convert.log; echo; head -5 test_4b7e6e/test_4b7e6e_stage2_skipped.csv; cut -d, -f7 test_4b7e6e/test_4b7e6e_stage2_skipped.csv | sort | uniq -c | sort -rn | head; cut -d, -f5 test_4b7e6e/test_4b7e6e_stage2_skipped.csv | sort | uniq -c | sort -rn | head
grep -a "not built\|solids:\|ratio\|class" test_4b7e6e/convert.log | tail -8 | cut -c1-400
head -3 KJL_f3e696/KJL_f3e696_stage2_skipped.csv; cut -d, -f7 KJL_f3e696/KJL_f3e696_stage2_skipped.csv | sort | uniq -c | sort -rn | head
grep -a "not built\|solids:\|ratio\|class\|Error\|error" KJL_f3e696/convert.log | tail -8 | cut -c1-400
cat 01-NOV-21_RH_PALO_ALTO_JOB_88fb6a/01-NOV-21_RH_PALO_ALTO_JOB_88fb6a_stage2_skipped.csv
