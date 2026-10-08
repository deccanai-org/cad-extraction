#!/usr/bin/env python3
"""The COMPLETED model of this model, colour-coded: every part one colour, every colour one meaning.

    python build_completed_coloured.py                # -> completed/<model>_COMPLETED.step        (coloured)
                                                      #  + completed/<model>_COMPLETED_plain.step  (same solids, no colours)
    python build_completed_coloured.py --jobs 8       # build in parallel (the same bytes as --jobs 1)
    python build_completed_coloured.py --list         # counts per colour and what each colour holds; nothing is built
    python build_completed_coloured.py --verify       # also read the coloured file back as a viewer does (OpenCASCADE
                                                      #   XCAF: names + colours) and check the counts per colour
    python build_completed_coloured.py --coloured-only | --plain-only

Colours (schedules/completion.json says, per part, which one and why):
  GREY     original geometry, verified correct against the source (unchanged)
  GREEN    GREEN-RESTORED     restored EXACTLY from data in the source file (DB1 / SDS/2 / IFC) the conversion ignored
  BLUE     BLUE-STANDARD      built from a cited industry standard table (bolts / nuts / washers, studs, rebar, ...)
  AMBER    AMBER-ESTIMATED    no exact data and no standard: best inference (the basis is in the name)
  MAGENTA  MAGENTA-NOT-EXACT  our rebuild still differs from the target geometry (not fixed / build or check failed)
  RED      RED-POSITION-ONLY  nothing known beyond a position: a marker
Every non-grey part's name starts with its colour word, says what was done and the source field / standard / basis,
then '| <part id> <name>'. The coloured STEP has one folder per colour (hide GREY to see only what changed).

Both files are built from ./schedules by steelbuild exactly as build_model.py builds them (the plain file IS
build_model.py's output). Runs headless, deterministic (the same inputs give byte-identical files). Requires Python
3.10+ and build123d (pip install -r ../requirements.txt). Exit status 1 when a count differs from completion.json or
a part that should be drawn is not.
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                              # build_model.py (same folder)
sys.path.insert(0, os.path.dirname(HERE))             # steelbuild.py, issues_lib.py (the scripts folder)

FIXED_TIME = '2000-01-01T00:00:00'


def use_completion_palette(lib, comp):
    """issues_lib's STEP writer / colourer / reader with the six completion colours"""
    order = ['GREY', 'GREEN', 'BLUE', 'AMBER', 'MAGENTA', 'RED']
    lib.COLOURS = collections.OrderedDict((c, tuple(comp['colours'][c])) for c in order)
    lib.PRECEDENCE = list(comp.get('precedence') or ['RED', 'MAGENTA', 'AMBER', 'BLUE', 'GREEN', 'GREY'])
    lib.PREFIX = dict(comp['prefix'])
    lib.FOLDER = {c: f"{c} - {comp['meaning'][c]}"[:200] for c in order}
    lib.VERSION = comp.get('version', 'pmp-completion')
    return order


def build_parts(folder, ids, jobs):
    """{part id: (solids, error)} built exactly as build_model.py builds them (same chunking, same pickle round trip)"""
    import pickle
    from build_model import _build_chunk
    results = {}
    if jobs > 1 and len(ids) > 50:
        from concurrent.futures import ProcessPoolExecutor
        n = max(1, len(ids) // (jobs * 8))
        chunks = [(folder, ids[i:i + n]) for i in range(0, len(ids), n)]
        with ProcessPoolExecutor(jobs) as ex:
            for res in ex.map(_build_chunk, chunks):
                for pid, solids, err in res:
                    results[pid] = (solids, err)
    elif ids:
        for pid, solids, err in pickle.loads(pickle.dumps(_build_chunk((folder, ids)))):
            results[pid] = (solids, err)
    return results


def write_plain(schedules, out, jobs):
    """build_model.py itself (its own process), header time stamp fixed"""
    cmd = [sys.executable, os.path.join(HERE, 'build_model.py'), '--schedules', schedules, '--out', out,
           '--jobs', str(jobs)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    print(p.stdout.strip().splitlines()[-1] if p.stdout.strip() else '', flush=True)
    if p.returncode != 0:
        print(p.stdout[-3000:] + p.stderr[-3000:])
        return False
    import issues_lib as lib
    lib.normalise_header(out, out, os.path.basename(out), FIXED_TIME)      # no-op if build_model.py fixed it already
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--schedules', default=os.path.join(HERE, 'schedules'))
    ap.add_argument('--out', default=None, help='coloured STEP (default completed/<model>_COMPLETED.step)')
    ap.add_argument('--plain-out', default=None, help='plain STEP (default completed/<model>_COMPLETED_plain.step)')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--coloured-only', action='store_true')
    ap.add_argument('--plain-only', action='store_true')
    a = ap.parse_args()
    comp = json.load(open(os.path.join(a.schedules, 'completion.json'), encoding='utf-8'))
    name = comp['model_name']
    out_dir = os.path.join(HERE, 'completed')
    out = a.out or os.path.join(out_dir, f'{name}_COMPLETED.step')
    plain = a.plain_out or os.path.join(out_dir, f'{name}_COMPLETED_plain.step')
    if a.list:
        print(f"{name} COMPLETED ({comp['step_source']} model): {comp['totals']['parts']} parts "
              f"(baseline {comp['totals']['baseline_parts']})")
        for c in ['GREY', 'GREEN', 'BLUE', 'AMBER', 'MAGENTA', 'RED']:
            print(f"  {c:7s} {comp['counts'].get(c, 0):6d}  {comp['meaning'][c]}")
        return 0
    os.makedirs(out_dir, exist_ok=True)
    ok = True
    t0 = time.time()
    if not a.coloured_only:
        ok &= write_plain(a.schedules, plain, a.jobs)
        print(f'plain -> {plain} ({time.time() - t0:.1f} s)', flush=True)
    if a.plain_only:
        return 0 if ok else 1
    import issues_lib as lib
    import steelbuild as sb
    order = use_completion_palette(lib, comp)
    sched = sb.Schedules(a.schedules)
    entries = comp.get('parts') or {}
    built = build_parts(a.schedules, [p['part_id'] for p in sched.parts], a.jobs)
    folders = {c: [] for c in order}
    failed = []
    for p in sched.parts:
        pid = p['part_id']
        e = entries.get(pid) or {}
        col = e.get('colour', 'GREY')
        base = f"{pid} {p['name']}".strip()
        label = e.get('label') or base
        solids, err = built.get(pid, ([], 'not built'))
        if solids and not err:
            shp = lib.part_shape(solids, sb)
        else:
            bb = e.get('bbox')
            if not bb:
                failed.append((pid, err or 'built no solid'))
                continue
            shp = lib.solid_bbox_frame(bb[:3], bb[3:])
            if col != 'MAGENTA' or 'MARKER' not in label:
                col = 'MAGENTA'
                label = (f"{comp['prefix']['MAGENTA']} our script does not build it ({err or 'no solid'}): MARKER ONLY, "
                         f"its box | {base}")
        shp.label = lib.ascii_text(label, lib.LABEL_MAX)
        folders[col].append(shp)
    got = {c: len(v) for c, v in folders.items()}
    lib.export_coloured([(c, folders[c]) for c in order], out,
                        f"{name} - COMPLETED (grey original verified, green restored from source, blue standard, "
                        f"amber estimated, magenta not exact, red position only)", FIXED_TIME)
    want = {c: comp['counts'].get(c, 0) for c in order}
    print(f"coloured: {', '.join(f'{c} {got[c]}' for c in order)} -> {out} ({time.time() - t0:.1f} s)", flush=True)
    if got != want:
        print('COUNT MISMATCH vs completion.json: ' + json.dumps({c: (got[c], want[c]) for c in order if got[c] != want[c]}))
        ok = False
    for pid, err in failed:
        print(f'  NOT DRAWN: {pid}: {err}')
    ok &= not failed
    if a.verify:
        rb = lib.readback_counts(out)
        print('read back:', json.dumps(rb))
        rbc = {c: rb['counts'].get(c, 0) for c in order}
        if rbc != want or rb['label_prefix_mismatch']:
            print('READ BACK MISMATCH')
            ok = False
    if not ok:
        print('FAILED: see the messages above')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
