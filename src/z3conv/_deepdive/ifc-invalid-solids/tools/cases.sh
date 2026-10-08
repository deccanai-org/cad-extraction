#!/bin/bash
# cases.sh LABEL CONVERTER PREFIX... : full worker + classifier (run_case.py) per sample, 3 in parallel
set -u
W=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-invalid-solids/work
PY=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env/env/bin/python
label="$1"; conv="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2
export CONV_HOME=/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env
cd "$W" || exit 1
for p in "$@"; do
  sha=$(python3 -c "import json,sys;print([k for k in json.load(open('contents_sel.json')) if k.startswith(sys.argv[1])][0])" "$p") || continue
  src=$(ls "s/$p".src.* | head -1)
  wd="$W/cases/$label/$p"
  ( rm -rf -- "$wd"; mkdir -p -- "$wd"
    "$PY" ../tools/run_case.py "$conv" "$src" "$sha" "$wd" --threads 2 --kit "$W/kit_snap" --coord "$W/coord_snap" > "$wd/run.out" 2> "$wd/run.err"; echo "$label $p $(tail -1 "$wd/run.out")" ) &
  while [ "$(jobs -r | wc -l)" -ge 3 ]; do sleep 2; done
done; wait
