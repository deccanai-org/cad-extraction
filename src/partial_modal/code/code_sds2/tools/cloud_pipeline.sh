#!/bin/bash
# on the cloud box, for every model (largest first), results synced to S3:
#   extract -> exact (+ exact_check) -> props -> recover -> views -> verify --ifc -> reference_defects -> verify_levels
#   -> tekla_checks -> kiss_check -> e2e
# Every step's exit code and wall time go to out/<stem>/step_times.tsv (step, exit code, seconds). IfcOpenShell and
# OpenCASCADE never share a process: extract / props / verify_levels / tekla_checks import ifcopenshell; exact.py runs
# exact_check.py, verify.py / recover.py / reference_defects.py run srcbrep.py, tekla_checks runs its build123d workers,
# each in a process of its own.
cd /opt/pm
PY=/opt/pm/venv/bin/python
J=${J:-60}
OUT=${OUT:-s3://bim-proprietary-data/cad-disk-extract/_state/pm_samples/out}
LOGKEY=${LOGKEY:-s3://bim-proprietary-data/cad-disk-extract/_state/pm_samples/pipeline.log}
MODELS=${MODELS:-}
export EXACT_JOBS=$J                     # exact.py: worker processes of its exact_check.py build check
$PY - <<'P' > /opt/pm/mlist.txt
import json, os
M = json.load(open('models.json'))
want = [x for x in os.environ.get('MODELS', '').split(',') if x]
if want:
    M = [m for m in M if m['stem'] in want]
M.sort(key=lambda m: -os.path.getsize(m['step_local']))
for m in M: print('\t'.join([m['stem'], m['step_local'], m['ifc_local'], m['project']]))
P
# run_step NAME LOG COMMAND...: COMMAND with its output appended to LOG; exit code and seconds appended to step_times.tsv
run_step() {
  local name=$1 log=$2; shift 2
  local t0=$(date +%s%N)
  "$@" < /dev/null >> "$log" 2>&1          # never the model list the loop reads
  local rc=$?
  local ms=$(( ($(date +%s%N) - t0) / 1000000 ))
  printf '%s\t%s\t%d.%03d\n' "$name" "$rc" $((ms / 1000)) $((ms % 1000)) >> "out/$stem/step_times.tsv"
  return $rc
}
while IFS=$'\t' read stem step ifc proj; do
  [ -n "$stem" ] || continue
  s=$(date +%s)
  rm -rf "out/$stem"; mkdir -p "out/$stem"          # every output of a model comes from this run (no stale paths.json)
  printf 'step\texit_code\tseconds\n' > "out/$stem/step_times.tsv"
  O="out/$stem"
  run_step extract+exact "$O/extract.log" $PY -c "import sys; sys.path.insert(0,'tools'); import extract, exact, json; i=extract.extract('$ifc','$O'); exact.main('$O','$step'); print(json.dumps(i['status']), json.dumps(i.get('exact_faces')))"
  run_step props "$O/extract.log" $PY tools/props.py "$ifc" "$O"
  # recovery is accepted on verify.py's own rule and references (the IFC's kernel geometry, the delivered STEP)
  run_step recover "$O/recover.log" $PY tools/recover.py "$O" --jobs $J --ifc "$ifc" --step "$step" --time-budget 1800 --mem-budget-gb 6
  run_step views "$O/views.log" $PY tools/views.py "$O"
  # verify writes verification.csv / verification_summary.json and, from its source pass, the kernel's log
  # (source_kernel_log.jsonl) and B-rep census (source_brep_census.csv) that reference_defects.py reads
  run_step verify "$O/verify.log" $PY tools/verify.py "$O" "$step" --ifc "$ifc" --jobs $J
  run_step reference_defects "$O/refdefects.log" $PY tools/reference_defects.py "$O" --ifc "$ifc"
  run_step verify_levels "$O/levels.log" $PY tools/verify_levels.py "$O" "$ifc"
  # authoring-tool facts (Tekla / Revit weights, volumes, lengths, elevations, centres of gravity) vs the rebuild
  run_step tekla_checks "$O/tekla.log" $PY tools/tekla_checks.py "$O" --ifc "$ifc" --jobs $J --kit /opt/pm/kit --stem "$stem"
  # fabricator KISS lists of the same project (checksum: marks, quantities, profiles, grades, lengths, holes, bolts)
  KD=/opt/pm/kiss/$proj
  if ls "$KD"/*.kss > /dev/null 2>&1; then
    run_step kiss_check "$O/kiss.log" $PY tools/kiss_check.py "$O" "$KD"/*.kss --ifc "$ifc"
  fi
  # end-to-end: run the packaged script exactly as a user would, from a package-shaped folder holding every schedule the
  # build reads (paths.json: swept solids, written by recover.py only when a model has any; assemblies.csv: the assembly
  # hierarchy --assembly-id / --assembly select through)
  E=/opt/pm/e2e/$stem; rm -rf $E; mkdir -p $E/scripts/model/schedules
  cp kit/steelbuild.py $E/scripts/; cp kit/build_model.py $E/scripts/model/; cp "$O/verification.csv" $E/scripts/model/
  for f in parts.csv profiles.csv profile_outlines.json solids.csv cuts.csv cut_boundaries.json openings.csv paths.json exact_geometry.jsonl assemblies.csv; do
    if [ -f "$O/$f" ]; then cp "$O/$f" $E/scripts/model/schedules/; fi
  done
  run_step e2e "$O/e2e.log" $PY tools/e2e.py $E/scripts/model --jobs $J --sample 15
  cp $E/scripts/model/e2e_results.csv $E/scripts/model/e2e_summary.json "$O/" 2>/dev/null
  aws s3 sync --only-show-errors "$O" "$OUT/$stem" < /dev/null
  fails=$(awk -F'\t' 'NR > 1 && $2 != 0 {printf "%s(rc %s) ", $1, $2}' "$O/step_times.tsv")
  echo "$(date -u +%H:%M:%S) $stem $(($(date +%s)-s))s failed_steps=[${fails}] $(cat $O/recover_summary.json 2>/dev/null | tr -d '\n ') $($PY -c "import json;d=json.load(open('$O/verification_summary.json'));c=d.get('source_coverage',{});print(d['parts'],d['status'],'src',d['source_check'],'del',d['delivered_check'],'src_checked',c.get('checked_against_source'),'notbuilt',d['delivered_parts_not_built'],d['seconds'])" 2>&1 | tail -1) refdefects=$($PY -c "import json;print(json.load(open('$O/reference_defects_summary.json'))['verdict'])" 2>&1 | tail -1) levels=$($PY -c "import json;print(json.load(open('$O/levels_summary.json'))['model'])" 2>&1 | tail -1) e2e=$(cat $O/e2e_summary.json 2>/dev/null | $PY -c "import json,sys;d=json.load(sys.stdin);print({k:d[k] for k in ('model','determinism','assembly','piece')})" 2>&1 | tail -1)" >> pipeline.log
  aws s3 cp --only-show-errors pipeline.log $LOGKEY < /dev/null
done < /opt/pm/mlist.txt
echo ALLDONE >> pipeline.log
aws s3 cp --only-show-errors pipeline.log $LOGKEY
