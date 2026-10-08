#!/bin/bash
# Zenitude-data-2 file extraction on cad-zen2-files (run via SSM with nohup). Everything lands under
# s3://annotationprod/cad-disk-extract/zenitude-data-2/{extracted,dxf,png,json,_state}/ (per-disk folder, nothing shared).
set -u
B=s3://annotationprod/cad-disk-extract/zenitude-data-2
SRC=$B/source
W=/work; IN=$W/in/src; OUT=$W/out
mkdir -p $IN $OUT/extracted $OUT/dxf $OUT/png $OUT/json/drawings_text $OUT/state
LOG=$OUT/state/files_jobs.log
log() { echo "$(date -u +%FT%TZ) $*" | tee -a $LOG; aws s3 cp --quiet $LOG $B/_state/files_jobs.log; }

log "start on $(hostname), $(nproc) cpu"
# 1. pull everything except the SQL backups (those are handled on cad-zen2-sql)
aws s3 sync --only-show-errors $SRC/ $IN/ --exclude "PLC 17072025/*.dat" --exclude "PLC 17072025/*.7z"
aws s3 cp --only-show-errors "$SRC/PLC 17072025/New folder/SharedContent_MLNG(S3Dv13).7z" "$W/in/SharedContent_MLNG(S3Dv13).7z"
log "pulled: $(find $IN -type f | wc -l) files, $(du -sh $IN | cut -f1) + SharedContent $(stat -c %s "$W/in/SharedContent_MLNG(S3Dv13).7z") B"

# 2. inventory + sha256 of every source file (duplicate report)
( cd $IN && find . -type f -print0 | xargs -0 -P 16 -n 50 sha256sum ) | sed 's#  \./#\t#' > $OUT/json/source_sha256.tsv
awk -F'\t' '{c[$1]++; f[$1]=f[$1] "\n    " $2} END {for (h in c) if (c[h]>1) {d++; print c[h] "x " h f[h]}; print "duplicate groups: " d+0 > "/dev/stderr"}' $OUT/json/source_sha256.tsv > $OUT/json/source_duplicates.txt 2>> $LOG
log "sha256 done: $(wc -l < $OUT/json/source_sha256.tsv) files, $(cut -f1 $OUT/json/source_sha256.tsv | sort -u | wc -l) distinct"

# 3. SharedContent: full unpack (no password prompt ever: -p with empty password)
T0=$(date +%s)
7z x -y -p"" -bb0 -bd "$W/in/SharedContent_MLNG(S3Dv13).7z" -o"$OUT/extracted/SharedContent_MLNG(S3Dv13)" > $OUT/state/sharedcontent_7z.log 2>&1
log "SharedContent unpacked rc=$? in $(( $(date +%s)-T0 ))s: $(find "$OUT/extracted/SharedContent_MLNG(S3Dv13)" -type f | wc -l) files, $(du -sh "$OUT/extracted/SharedContent_MLNG(S3Dv13)" | cut -f1)"
( cd "$OUT/extracted/SharedContent_MLNG(S3Dv13)" && find . -type f -printf '%s\t%P\n' ) > $OUT/json/sharedcontent_files.tsv
awk -F'\t' '{n=split($2,a,"."); e=(n>1)?tolower(a[n]):"(none)"; c[e]++; s[e]+=$1} END {for (e in c) printf "%d\t%d\t%s\n", c[e], s[e], e}' $OUT/json/sharedcontent_files.tsv | sort -k2,2nr > $OUT/json/sharedcontent_by_ext.tsv

# 4. nested archives among the loose files (e.g. TEC COMMENTS/OneDrive zip)
find $IN -type f \( -iname '*.zip' -o -iname '*.7z' -o -iname '*.rar' \) | while read -r a; do
  rel=${a#$IN/}; 7z x -y -p"" -bd "$a" -o"$OUT/extracted/${rel}!" > /dev/null 2>> $LOG && log "unpacked $rel" || log "FAILED unpack $rel"
done

# 5. DWG -> DXF (ASCII). .bak files that are DWG inside (AC10xx magic) are converted too.
if ! command -v dwg2dxf > /dev/null; then
  apt-get install -y -q build-essential > /dev/null 2>&1
  ( cd /tmp && curl -sL https://github.com/LibreDWG/libredwg/releases/download/0.13.3/libredwg-0.13.3.tar.xz | tar xJ \
    && cd libredwg-0.13.3 && ./configure --disable-bindings --disable-docs > /dev/null && make -j"$(nproc)" -s > /dev/null 2>&1 && make install -s > /dev/null && ldconfig ) \
    && log "built LibreDWG: $(dwg2dxf --version 2>&1 | head -1)" || log "LibreDWG build FAILED"
fi
find $IN $OUT/extracted -type f \( -iname '*.dwg' -o -iname '*.bak' \) > $W/dwg_list.txt
ok=0; bad=0; : > $OUT/state/dxf_failures.tsv
while read -r f; do
  head -c 4 "$f" | grep -q '^AC10' || continue
  rel=${f#$IN/}; rel=${rel#$OUT/extracted/}; o="$OUT/dxf/${rel}.dxf"; mkdir -p "$(dirname "$o")"
  if timeout 300 dwg2dxf -y -o "$o" "$f" > /dev/null 2>&1 && [ -s "$o" ]; then ok=$((ok+1)); else bad=$((bad+1)); printf '%s\t%s\n' "$rel" "$(head -c 6 "$f")" >> $OUT/state/dxf_failures.tsv; rm -f "$o"; fi
done < $W/dwg_list.txt
log "DWG->DXF (LibreDWG): ok=$ok failed=$bad"

# 6. PDF -> PNG (150 dpi) + layout text for title-block parsing
find $IN $OUT/extracted -type f -iname '*.pdf' > $W/pdf_list.txt
cat > $W/pdf1.sh <<'EOS'
#!/bin/bash
f="$1"; IN="$2"; OUT="$3"
rel=${f#$IN/}; rel=${rel#$OUT/extracted/}; d="$OUT/png/$rel"; mkdir -p "$d"
if timeout 600 pdftoppm -r 150 -png "$f" "$d/page"; then pdftotext -layout "$f" "$OUT/json/drawings_text/${rel//\//__}.txt"; else echo "PDF_FAIL $rel"; fi
EOS
chmod +x $W/pdf1.sh
tr '\n' '\0' < $W/pdf_list.txt | xargs -0 -P 24 -I{} $W/pdf1.sh {} "$IN" "$OUT" >> $LOG 2>&1
log "PDF->PNG: $(find $OUT/png -name '*.png' | wc -l) pages from $(wc -l < $W/pdf_list.txt) PDFs"

# 7. push outputs
for d in extracted dxf png json; do aws s3 sync --only-show-errors $OUT/$d/ $B/$d/; done
aws s3 sync --only-show-errors $OUT/state/ $B/_state/files/
log "files jobs DONE; outputs in $B/{extracted,dxf,png,json}/"
