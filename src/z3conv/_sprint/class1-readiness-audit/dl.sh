#!/bin/bash
export AWS_PROFILE=bim
cd /Users/dhiren/Downloads/Deccan/z3conv/_sprint/class1-readiness-audit
while IFS=$'\t' read -r sha size key; do
  [ -s "src/$sha.db1" ] && continue
  aws s3 cp "s3://bim-proprietary-data/$key" "src/$sha.db1.part" --only-show-errors && mv "src/$sha.db1.part" "src/$sha.db1" && echo "ok $sha $size" || echo "FAIL $sha $key"
done < dl_list.tsv
echo DONE
