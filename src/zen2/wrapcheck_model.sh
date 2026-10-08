#!/bin/bash
# Prove each .7z wrapper holds a byte-identical copy of its .dat: unpack and compare sha256 with the source .dat.
B=s3://annotationprod/cad-disk-extract/zenitude-data-2
SRC="$B/source/PLC 17072025"
OUT=/work/out/state/wrap_check_model.tsv; : > $OUT
W=/work/wrapm; mkdir -p $W && cd $W
for base in PLC_Model_Backup; do
  rm -rf $W/x "$W/$base.7z"
  /usr/local/bin/s5cmd --numworkers 32 cp --concurrency 32 --part-size 128 "s3://bim-proprietary-data/Zenitude-data-2/PLC 17072025/$base.7z" "$W/$base.7z" > $W/dl_$base.log 2>&1
  if [ ! -s "$W/$base.7z" ]; then printf '%s\tdownload_failed\t%s\n' "$base" "$(tail -c 300 $W/dl_$base.log | tr '\n' ' ')" >> $OUT; continue; fi
  /usr/local/bin/7zz x -y -p -bso0 -bsp0 -o$W/x "$W/$base.7z" < /dev/null > $W/x_$base.log 2>&1; rc=$?
  f=$(ls $W/x/*.dat 2>/dev/null | head -1)
  if [ $rc -ne 0 ] || [ -z "$f" ]; then printf '%s\t7z_rc=%s\terror\t%s\n' "$base" "$rc" "$(tail -c 300 $W/x_$base.log | tr '\n' ' ')" >> $OUT; continue; fi
  h7=$(sha256sum "$f" | cut -d' ' -f1); s7=$(stat -c %s "$f")
  hd=$(/usr/local/bin/s5cmd cat "$SRC/$base.dat" | sha256sum | cut -d' ' -f1)
  v=$([ "$h7" = "$hd" ] && echo identical || echo DIFFERENT)
  printf '%s\t7z_rc=%s\tsize=%s\tsha256_7z=%s\tsha256_dat=%s\t%s\n' "$base" "$rc" "$s7" "$h7" "$hd" "$v" >> $OUT
  rm -rf $W/x "$W/$base.7z"
done
aws s3 cp --quiet $OUT $B/_state/files/wrap_check_model.tsv
echo "$(date -u +%FT%TZ) wrapper check: $(cut -f1,2,6,7 $OUT | tr '\n' ';')" >> /work/out/state/deep.log; aws s3 cp --quiet /work/out/state/deep.log $B/_state/deep.log
