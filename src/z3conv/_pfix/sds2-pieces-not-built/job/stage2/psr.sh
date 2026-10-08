W=/work/agentwork/sds2-pieces-not-built
for V in v553 v553r; do echo "== $V"; grep -a -i "reference\|budget\|placed\|skipped\|stage 2\|wrote\|read-back\|verify" $W/ab553/$V/State_Reno_df6dfb/convert.log | grep -v "^\*" | tail -8 | cut -c1-250; ls -la --time-style=+%H:%M $W/ab553/$V/State_Reno_df6dfb/ | tail -4; done
