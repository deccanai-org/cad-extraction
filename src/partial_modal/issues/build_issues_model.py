#!/usr/bin/env python3
"""Colour-coded issue model of this model: where the delivered STEP is not perfect, one colour per part.

    python build_issues_model.py                      # our rebuild from the schedules, coloured
                                                      #   -> issues/<model>_ISSUES_highlighted.step
                                                      #   + issues/<model>_MISSING_parts_only.step (when anything is missing)
    python build_issues_model.py --from-delivered     # the package's delivered STEP itself, coloured (geometry unchanged)
                                                      #   -> issues/<model>_ISSUES_on_delivered.step (+ the MISSING file)
    python build_issues_model.py --from-delivered PATH   # ... the delivered STEP at another path (must be the same file)
    python build_issues_model.py --list               # counts per colour and what each colour holds; nothing is built
    python build_issues_model.py --jobs 8             # build in parallel (the same file as --jobs 1)
    python build_issues_model.py --verify             # also read the written files back as a viewer does
                                                      #   (OpenCASCADE XCAF: names + colours) and check the counts
    python build_issues_model.py --out FILE           # choose the output file

Colours:  GREY fine | RED MISSING from the delivered STEP (drawn only from geometry the source records; 'MARKER ONLY'
where the source records a position or an extent but not the shape) | ORANGE APPROX (approximated by the converter) |
YELLOW CHECK (suspicious) | PURPLE OUR-SCRIPT-NOT-PERFECT (our build123d script does not rebuild it to 'match' yet).
One colour per part (precedence RED > YELLOW > ORANGE > PURPLE); the part's name starts with the colour's word and
lists every reason. issues/WHERE_TO_LOOK.md says, in plain language, what each colour marks and where to find it.

Default mode builds every part from ./schedules exactly as build_model.py does (steelbuild; the same solids as
rebuilt_model.step), colours it per schedules/issues.json and adds the RED parts of schedules/missing_parts.json; the
STEP has one folder per colour (hide the GREY folder to see only the problems).
--from-delivered edits the delivered STEP as text: only part names change and colour styling is appended, every
geometry statement stays byte for byte as delivered (checked after writing), and the RED parts are appended.

Runs headless (no GUI), deterministic (the same inputs give byte-identical files). Requires Python 3.10+ and build123d
(pip install -r ../requirements.txt). Exit status 1 when a count differs from schedules/issues.json, a check fails or
a part that should be drawn is not.
"""
import argparse
import json
import os
import pickle
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                              # build_model.py (same folder)
sys.path.insert(0, os.path.dirname(HERE))             # steelbuild.py, issues_lib.py (the scripts folder)


def build_parts(folder, ids, jobs):
    """{part id: (solids, error)} built exactly as build_model.py builds them (same chunking, same pickle round trip)"""
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


def missing_shapes(missing, sched, built, sb, lib):
    """the RED parts in missing_parts.json order -> [(entry, shape or None, error)]; schedule parts come from `built`"""
    out = []
    for m in missing.get('parts', []):
        g = m['geometry']
        try:
            if g['kind'] == 'schedule_part':
                solids, err = built.get(g['part_id'], ([], 'not built'))
                if err or not solids:
                    raise ValueError(err or 'built no solid')
                shp = lib.part_shape(solids, sb)
            else:
                shp = lib.build_missing(m, sched, sb)
            out.append((m, shp, None))
        except Exception as e:                          # a source record that does not make a solid: its marker instead
            fb = m.get('fallback')
            if fb:
                try:
                    shp = lib.build_missing(dict(m, geometry=fb), sched, sb)
                    lab = m.get('fallback_label') or (m['label'] + ' - MARKER ONLY (its recorded geometry did not make a '
                                                      f'valid solid: {type(e).__name__})')
                    out.append((dict(m, label=lab), shp, None))
                    continue
                except Exception as e2:
                    e = e2
            out.append((m, None, f'{type(e).__name__}: {e}'))
    return out


def write_missing(path, title, red, lib, sb, stamp):
    """the RED parts alone, one product each, in one STEP (the same file in both modes); removed when there are none"""
    from build123d import Compound
    leaves = []
    for m, shp, err in red:
        if shp is None:
            continue
        c = lib.own_copy(shp, sb)
        c.label = lib.ascii_text(m['label'], lib.LABEL_MAX)
        leaves.append(c)
    if not leaves:
        if os.path.exists(path):
            os.remove(path)
        return 0
    t = f'{title} - MISSING parts only (red)'
    lib.export_uncoloured_then_colour(Compound(children=leaves, label=lib.ascii_text(t, 200)), path, t, stamp)
    return len(leaves)


def run_missing_only(a):
    import subprocess
    cmd = [sys.executable, os.path.abspath(__file__), '--missing-only', '--schedules', a.schedules]
    if a.missing_out:
        cmd += ['--missing-out', a.missing_out]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout[-2000:] + p.stderr[-2000:])
        raise SystemExit('writing the MISSING parts only STEP failed')
    return json.loads(p.stdout.strip().splitlines()[-1])['written']


def check_counts(what, got, want):
    keys = set(got) | set(want)
    bad = {c: (got.get(c, 0), want.get(c, 0)) for c in keys if got.get(c, 0) != want.get(c, 0)}
    if bad:
        print(f'COUNT MISMATCH ({what}): ' + ', '.join(f'{c} got {g} expected {w}' for c, (g, w) in sorted(bad.items())))
    return not bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--schedules', default=os.path.join(HERE, 'schedules'))
    ap.add_argument('--from-delivered', nargs='?', const='auto', default=None, metavar='PATH',
                    help='colour the delivered STEP instead of our rebuild (default path: the package model/step file)')
    ap.add_argument('--out', default=None, help='output STEP (default issues/<model>_ISSUES_highlighted.step, '
                                                 'or issues/<model>_ISSUES_on_delivered.step with --from-delivered)')
    ap.add_argument('--missing-out', default=None, help='MISSING parts only STEP (default issues/<model>_MISSING_parts_only.step)')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--list', action='store_true', help='print counts per colour and categories, build nothing')
    ap.add_argument('--verify', action='store_true', help='read the written files back (XCAF) and check colours / names / counts')
    ap.add_argument('--force', action='store_true', help='with --from-delivered: accept a delivered file whose sha256 differs')
    ap.add_argument('--missing-only', action='store_true', help=argparse.SUPPRESS)
    a = ap.parse_args()
    import issues_lib as lib
    issues = json.load(open(os.path.join(a.schedules, 'issues.json'), encoding='utf-8'))
    missing = json.load(open(os.path.join(a.schedules, 'missing_parts.json'), encoding='utf-8'))
    name = issues['model_name']
    title = issues.get('title') or name
    stamp = issues.get('step_time') or lib.FIXED_TIME
    out_dir = os.path.join(HERE, 'issues')
    miss_out = a.missing_out or os.path.join(out_dir, f'{name}_MISSING_parts_only.step')
    if a.list:
        print(f"{title}: {issues['step_source']} model, delivered {issues['delivered']['relpath']}")
        for mode in ('rebuild', 'delivered'):
            c = issues['counts'][mode]
            print(f'{mode:9s}: ' + ', '.join(f'{k} {c.get(k, 0)}' for k in lib.COLOURS) + f"  (total {sum(c.values())})")
        for cat in issues.get('categories', []):
            print(f"  {cat['colour']:6s} {cat['count']:6d}  {cat['category']}: {cat['what']}")
        for n in issues.get('not_drawn', []):
            print(f"  not drawn: {n}")
        return 0
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    if a.missing_only:
        # the MISSING parts only STEP, always written by a process of its own doing only this, so that both modes
        # write the same bytes (building other parts first changes OpenCASCADE state the writer depends on)
        import steelbuild as sb
        sched = sb.Schedules(a.schedules)
        ents = issues.get('parts', {})
        red_ids = [m['geometry']['part_id'] for m in missing.get('parts', []) if m['geometry']['kind'] == 'schedule_part'
                   and not (ents.get(m['geometry']['part_id']) or {}).get('no_build')]
        red = missing_shapes(missing, sched, build_parts(a.schedules, red_ids, 1), sb, lib)
        n = write_missing(miss_out, title, red, lib, sb, stamp)
        bad = [(m['id'], err) for m, shp, err in red if shp is None]
        print(json.dumps(dict(written=n, not_drawn=bad)))
        return 0
    import steelbuild as sb
    sched = sb.Schedules(a.schedules)
    entries = issues.get('parts', {})
    ok = True
    failed = []
    if a.from_delivered is None:
        # ------------------------------------------------------------------ rebuild mode
        out = a.out or os.path.join(out_dir, f'{name}_ISSUES_highlighted.step')
        # parts whose build crashes natively (verification BUILD_CRASH) are not built here either: their source box
        ids = [p['part_id'] for p in sched.parts if not (entries.get(p['part_id']) or {}).get('no_build')]
        built = build_parts(a.schedules, ids, a.jobs)
        folders = {c: [] for c in lib.COLOURS}
        for p in sched.parts:
            pid = p['part_id']
            e = entries.get(pid)
            col = e['colour'] if e else 'GREY'
            solids, err = built.get(pid, ([], 'not built (its build crashes: verification BUILD_CRASH)'))
            base = f"{pid} {p['name']}".strip()
            if solids and not err:
                shp = lib.part_shape(solids, sb)
                shp.label = lib.ascii_text(lib.label_for(e, base) if e else base, lib.LABEL_MAX)
            else:
                bb = (e or {}).get('marker_bbox')
                if not bb:
                    if not (e or {}).get('not_drawn'):
                        failed.append((pid, err or 'built no solid'))
                    continue
                shp = lib.solid_bbox_frame(bb[:3], bb[3:])
                shp.label = lib.ascii_text(lib.label_for(e, base) + f" - MARKER ONLY: {e.get('marker_what') or 'its box'} "
                                           f'(our script does not build it: {err or "no solid"})', lib.LABEL_MAX)
            folders[col].append(shp)
        red = missing_shapes(missing, sched, built, sb, lib)
        sched_ids = {p['part_id'] for p in sched.parts}
        for m, shp, err in red:
            if m.get('part_id') in sched_ids:
                continue                                # a schedule part: already in the RED folder (drawn above)
            if shp is None:
                failed.append((m['id'], err))
                continue
            c = lib.own_copy(shp, sb)
            c.label = lib.ascii_text(m['label'], lib.LABEL_MAX)
            folders['RED'].append(c)
        for d in issues.get('delivered_only', []):      # delivered parts our schedules lack: their delivered box
            if d.get('bbox'):
                shp = lib.solid_bbox_frame(d['bbox'][:3], d['bbox'][3:])
                shp.label = lib.ascii_text(d['label'] + ' - MARKER ONLY: its delivered bounding box', lib.LABEL_MAX)
                folders[d['colour']].append(shp)
        got = {c: len(v) for c, v in folders.items()}
        lib.export_coloured([(c, folders[c]) for c in lib.COLOURS], out, f'{title} - ISSUES rebuilt from the schedules '
                            '(grey ok, red missing, orange approx, yellow check, purple our script not perfect)', stamp)
        nmiss = run_missing_only(a)
        ok &= check_counts('rebuild', got, issues['counts']['rebuild'])
        print(f"rebuild: {', '.join(f'{c} {got[c]}' for c in lib.COLOURS)} -> {out} ({time.time() - t0:.1f} s)")
        if nmiss:
            print(f'missing parts only: {nmiss} -> {miss_out}')
        want = issues['counts']['rebuild']
    else:
        # ------------------------------------------------------------------ delivered mode
        out = a.out or os.path.join(out_dir, f'{name}_ISSUES_on_delivered.step')
        src = a.from_delivered
        if src == 'auto':
            src = os.path.normpath(os.path.join(HERE, '..', '..', issues['delivered']['relpath']))
        if not os.path.exists(src):
            sys.exit(f'delivered STEP not found: {src} (give its path: --from-delivered PATH)')
        sha = lib.sha256_file(src)
        if sha != issues['delivered']['sha256'] and not a.force:
            sys.exit(f"{src} is not the delivered STEP these issues were made for (sha256 {sha[:12]}..., expected "
                     f"{issues['delivered']['sha256'][:12]}...); --force to colour it anyway")
        red_ids = [m['geometry']['part_id'] for m in missing.get('parts', []) if m['geometry']['kind'] == 'schedule_part'
                   and not (entries.get(m['geometry']['part_id']) or {}).get('no_build')]
        built = build_parts(a.schedules, red_ids, a.jobs)
        red = missing_shapes(missing, sched, built, sb, lib)
        failed = [(m['id'], err) for m, shp, err in red if shp is None]
        nmiss = run_missing_only(a)
        r = lib.colour_delivered(src, issues, out, miss_out if nmiss else None, issues['delivered']['id_scheme'], title)
        got = r['counts']
        ok &= check_counts('delivered', got, issues['counts']['delivered'])
        print(f"delivered: {', '.join(f'{c} {got[c]}' for c in lib.COLOURS)}; {r['renamed']} names changed, "
              f"{r['cloned']} occurrences given their own product copy, {r['red_appended']} red parts appended "
              f"-> {out} ({time.time() - t0:.1f} s)")
        # the written file checked as text: geometry statements untouched, every leaf part coloured as planned
        ck = lib.check_delivered(src, out, got)
        print('text check: ' + json.dumps({k: ck[k] for k in ('ok', 'original_statements', 'missing', 'edited',
                                                             'n_bad_edits', 'appended', 'counts', 'n_mixed',
                                                             'n_uncoloured')}))
        if not ck['ok']:
            print('TEXT CHECK FAILED: ' + json.dumps({k: ck[k] for k in ('bad_edits', 'mixed', 'uncoloured', 'expected')}))
        ok &= ck['ok']
        want = issues['counts']['delivered']
    for pid, err in failed:
        print(f'  NOT DRAWN: {pid}: {err}')
    ok &= not failed
    if a.verify:
        rb = lib.readback_counts(out)
        print('read back:', json.dumps(rb))
        ok &= check_counts('read back', rb['counts'], want) and rb['label_prefix_mismatch'] == 0
        if nmiss:
            rm = lib.readback_counts(miss_out)
            print('read back (missing only):', json.dumps(rm))
            ok &= rm['counts'] == {'RED': nmiss} and rm['label_prefix_mismatch'] == 0
    if not ok:
        print('FAILED: see the messages above')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
