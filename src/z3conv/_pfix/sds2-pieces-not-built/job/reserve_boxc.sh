W=/work/agentwork/sds2-pieces-not-built
for n in DFGH_010ffa P-02_036a18 jklu_573093 bbbn_f9466d jfkf_23c107 vfgrt_04be53 KL_10c4a7 State_Reno_df6dfb; do
  for V in a b2; do [ -d $W/ab/$V/$n ] && echo "exists $V/$n" || { mkdir -p $W/ab/$V/$n; echo "reserved $V/$n (runs on coordinator)" > $W/ab/$V/$n/ON_COORD; }; done
done
