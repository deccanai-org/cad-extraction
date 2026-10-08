#!/bin/bash
# Zenitude-data-2 deep pass on cad-zen2-files (nohup/setsid):
#  1. unpack every nested archive under /work/out/extracted (SharedContent zips, zips in zips...) into "<name>!/" to depth 15;
#     password-locked ones are recorded, not tried
#  2. unpack the two .7z wrappers (catalog + model backups) and prove they are byte-identical to the .dat files (sha256)
#  3. sha256 + per-type stats (raw and unique) for everything extracted; upload tree, manifest and stats
set -u
B=s3://annotationprod/cad-disk-extract/zenitude-data-2
X=/work/out/extracted; S=/work/out/state; J=/work/out/json; mkdir -p $S $J
LOG=$S/deep.log
log() { echo "$(date -u +%FT%TZ) $*" | tee -a $LOG; aws s3 cp --quiet $LOG $B/_state/deep.log; }
if [ ! -x /usr/local/bin/7zz ]; then
  curl -sfL https://www.7-zip.org/a/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz || curl -sfL https://github.com/ip7z/7zip/releases/download/24.08/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz
  tar xJf /tmp/7z.tar.xz -C /usr/local/bin 7zz; chmod +x /usr/local/bin/7zz
fi
if [ ! -x /usr/local/bin/s5cmd ]; then
  curl -sfL https://github.com/peak/s5cmd/releases/download/v2.2.2/s5cmd_2.2.2_Linux-64bit.tar.gz | tar xz -C /usr/local/bin s5cmd
fi
Z=/usr/local/bin/7zz
log "deep pass start ($($Z | sed -n 2p | cut -c1-30))"

# 1. nested archives, breadth-first until nothing new (depth <= 15)
: > $S/nested.tsv; : > $S/encrypted_nested.tsv
for depth in $(seq 1 15); do
  find $X -type f \( -iname '*.zip' -o -iname '*.7z' -o -iname '*.rar' -o -iname '*.cab' -o -iname '*.tar' -o -iname '*.tgz' -o -iname '*.gz' -o -iname '*.bz2' -o -iname '*.xz' \) -size +0 > $S/cand.txt
  new=0
  while IFS= read -r a; do
    [ -d "$a!" ] && continue
    grep -qxF "$a" $S/encrypted_nested.tsv 2>/dev/null && continue
    if $Z l -slt -p "$a" < /dev/null 2>/dev/null | grep -q '^Encrypted = +'; then printf '%s\n' "$a" >> $S/encrypted_nested.tsv; continue; fi
    $Z x -y -p -bso0 -bsp0 -o"$a!" "$a" < /dev/null > /dev/null 2>> $S/nested_errors.log; rc=$?
    printf '%s\t%s\t%s\n' "$depth" "$rc" "${a#$X/}" >> $S/nested.tsv; new=$((new+1))
  done < $S/cand.txt
  log "depth $depth: unpacked $new nested archives"
  [ $new -eq 0 ] && break
done
log "nested total $(wc -l < $S/nested.tsv), encrypted $(wc -l < $S/encrypted_nested.tsv), non-zero rc $(awk -F'\t' '$2!=0' $S/nested.tsv | wc -l)"

# 2. .7z wrappers vs .dat (unpack to scratch, compare sha256 with the .dat streamed from S3; store only if different)
SRC="$B/source/PLC 17072025"
mkdir -p /work/wrap && cd /work/wrap
for base in PLC_CatalogBackup PLC_Model_Backup; do
  /usr/local/bin/s5cmd --numworkers 32 cp --concurrency 32 --part-size 128 "$SRC/$base.7z" "/work/wrap/$base.7z" > /dev/null
  $Z l -slt "/work/wrap/$base.7z" < /dev/null | grep -E '^(Path|Size|CRC|Modified) = ' > $S/wrap_${base}_listing.txt
  $Z x -y -p -bso0 -bsp0 -o/work/wrap/x "/work/wrap/$base.7z" < /dev/null; rc=$?
  h7=$(sha256sum "/work/wrap/x/$base.dat" | cut -d' ' -f1)
  hd=$(/usr/local/bin/s5cmd cat "$SRC/$base.dat" | sha256sum | cut -d' ' -f1)
  if [ "$h7" = "$hd" ]; then verdict=identical; else verdict=DIFFERENT; aws s3 cp --only-show-errors "/work/wrap/x/$base.dat" "$B/extracted/$base.7z!/$base.dat"; fi
  printf '%s\t7z_rc=%s\tsha256_from_7z=%s\tsha256_of_dat=%s\t%s\n' "$base" "$rc" "$h7" "$hd" "$verdict" >> $S/wrap_check.tsv
  log "$base.7z: rc=$rc, unpacked .dat vs source .dat: $verdict"
  rm -rf /work/wrap/x "/work/wrap/$base.7z"
done

# 3. manifest (sha256) + per-type stats for the whole extracted tree
cd $X && find . -type f -print0 | xargs -0 -P 24 -n 100 sha256sum | sed 's#  \./#\t#' > $J/extracted_sha256.tsv
python3 - <<'PY'
import collections, json, os
X = '/work/out/extracted'
by = collections.defaultdict(lambda: [0, 0, set(), 0])
for line in open('/work/out/json/extracted_sha256.tsv', errors='replace'):
    h, rel = line.rstrip('\n').split('\t', 1)
    base = rel.rsplit('/', 1)[-1].lower()
    e = base.rsplit('.', 1)[-1] if '.' in base else '(none)'
    if len(e) > 12: e = '(other)'
    try: size = os.path.getsize(os.path.join(X, rel))
    except OSError: size = 0
    x = by[e]; x[0] += 1; x[1] += size
    if h not in x[2]: x[2].add(h); x[3] += size
out = [{'type': k, 'files': v[0], 'bytes': v[1], 'stored_files': len(v[2]), 'stored_bytes': v[3]} for k, v in sorted(by.items(), key=lambda kv: -kv[1][0])]
json.dump(out, open('/work/out/json/extracted_types.json', 'w'))
print(len(out), 'types', sum(t['files'] for t in out), 'files')
PY
log "extracted tree: $(wc -l < $J/extracted_sha256.tsv) files, $(cut -f1 $J/extracted_sha256.tsv | sort -u | wc -l) distinct"
aws s3 sync --only-show-errors $X/ $B/extracted/
aws s3 cp --only-show-errors $J/extracted_sha256.tsv $B/json/extracted_sha256.tsv
aws s3 cp --only-show-errors $J/extracted_types.json $B/_state/stats/extracted_types.json
aws s3 sync --only-show-errors $S/ $B/_state/files/
log "deep pass DONE"
