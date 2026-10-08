W=/work/agentwork/sds2-pieces-not-built
for V in v553 v553q; do echo "== $V"; grep -a "manifest\|read-back\|repair\|solids:" $W/ab553/$V/FGBVF_c2e2f4/convert.log | grep -v "^\*" | tail -4 | cut -c1-260; done
for V in v553 v553r; do echo "== SR $V"; grep -a "manifest\|read-back\|repair" $W/ab553/$V/State_Reno_df6dfb/convert.log | tail -3 | cut -c1-200; done
