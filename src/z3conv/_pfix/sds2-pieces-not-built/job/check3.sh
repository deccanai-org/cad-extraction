W=/work/agentwork/sds2-pieces-not-built
for n in 888_Boylston_Embeds_Only_b9c720 BG_Residental_tower_Job_0bda20 hk_86b590 THERMOFISHER_JOB_bff8f8; do echo "== $n"; tail -c 600 $W/smoke/$n/convert.log; echo; done
