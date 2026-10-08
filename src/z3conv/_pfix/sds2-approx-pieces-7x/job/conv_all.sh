#!/bin/bash
# conv_all.sh LISTFILE "VARIANTS" NP -> runs every (variant, job) pair, NP at a time
W=/work/agentwork/sds2-approx-pieces-7x
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-approx-pieces-7x
cd $W
L=$1; VS=$2; NP=${3:-8}; TAG=${4:-conv}
for V in $VS; do for J in $(cat $W/$L); do echo "$V $J"; done; done | xargs -P $NP -L 1 bash -c 'bash '$W'/conv.sh $0 $1'
date -u +%FT%TZ > $W/${TAG}_DONE; aws s3 cp --quiet $W/${TAG}_DONE $R/${TAG}_DONE
