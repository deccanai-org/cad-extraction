#!/usr/bin/env python3
"""Rebuild this model from its schedules with build123d.

    python build_model.py                       # whole model -> rebuilt_model.step
    python build_model.py --out my.step         # choose the output file
    python build_model.py --parts ID1,ID2       # only some parts (ids from schedules/parts.csv)
    python build_model.py --mark 1149A          # one piece: every part with this piece mark
    python build_model.py --assembly 302B       # one assembly mark: every assembly carrying this mark
    python build_model.py --assembly-id 2nhYEdn3X8j8KZi6y9Sai2   # one assembly and every assembly nested in it (ids in schedules/assemblies.csv)
    python build_model.py --role member         # one role: member, plate, bolt, weld, accessory, concrete or other
    python build_model.py --jobs 8              # build in parallel
    python build_model.py --list                # print the schedule summary and exit
    python build_model.py --assembly-id ID --list-parts   # print the ids of the parts a selection builds and exit

An assembly (--assembly-id, --assembly) includes the assemblies nested in it, at any depth: a part belongs to the
assembly in its assembly_id column (schedules/parts.csv) and that assembly to the one in its parent_id column
(schedules/assemblies.csv), so an assembly whose members are only other assemblies builds all of their parts.

Runs headless (no GUI). Requires Python 3.10+ and build123d (pip install -r ../requirements.txt).
The schedules are in ./schedules (millimetres, model coordinates); edit them and run again to get a modified model:
change a profile's dimensions in profiles.csv, a member's extrusion vector (its length) in solids.csv, the path of a
swept solid (a bent rod, a weld) in paths.json, a cut in cuts.csv, and so on. See ../README.md for the meaning of every
column.
"""
import argparse
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))           # steelbuild.py sits in the scripts folder


def _build_chunk(args):
    import steelbuild
    folder, ids = args
    sched = steelbuild.Schedules(folder)
    by = {p['part_id']: p for p in sched.parts}
    out = []
    for pid in ids:
        try:
            out.append((pid, steelbuild.build_part(by[pid], sched), None))
        except Exception as e:                          # report, keep going
            out.append((pid, [], f'{type(e).__name__}: {e}'))
    return out


# ---------------------------------------------------------------------------------------------- selection (no CAD)
def read_assemblies(folder):
    """{assembly_id: row} of schedules/assemblies.csv (assembly_mark, parent_id, ...); {} when it is absent or empty"""
    fn = os.path.join(folder, 'assemblies.csv')
    if not os.path.exists(fn) or os.path.getsize(fn) == 0:
        return {}
    with open(fn, newline='', encoding='utf-8') as fh:
        return {r['assembly_id']: r for r in csv.DictReader(fh)}


def nested_in(ids, assemblies):
    """the given assembly ids and every assembly nested in them, at any depth (parent_id of assemblies.csv)"""
    subs = {}
    for aid, r in assemblies.items():
        if r.get('parent_id'):
            subs.setdefault(r['parent_id'], []).append(aid)
    out, todo = set(), list(ids)
    while todo:
        a = todo.pop()
        if a in out:
            continue
        out.add(a)
        todo += subs.get(a, [])
    return out


def select(parts, assemblies, ids='', role='', mark='', assembly='', assembly_id=''):
    """the parts (rows of parts.csv) a command line selection names; the options combine (all must hold), each takes a
    comma separated list. --assembly / --assembly-id include the parts of the assemblies nested in the named ones."""
    if ids:
        want = set(ids.split(','))
        parts = [p for p in parts if p['part_id'] in want]
    if role:
        parts = [p for p in parts if p['role'] == role]
    if mark:
        want = {m.strip().lower() for m in mark.split(',')}
        parts = [p for p in parts if p['part_mark'].lower() in want]
    if assembly:
        want = {m.strip().lower() for m in assembly.split(',')}
        hit = {p['assembly_id'] for p in parts if p['assembly_id'] and p['assembly_mark'].lower() in want}
        hit |= {aid for aid, r in assemblies.items() if (r.get('assembly_mark') or '').lower() in want}
        inner = nested_in(hit, assemblies) - hit        # sub-assemblies of an assembly carrying the mark
        parts = [p for p in parts if p['assembly_mark'].lower() in want or p['assembly_id'] in inner]
    if assembly_id:
        want = nested_in({m.strip() for m in assembly_id.split(',')}, assemblies)
        parts = [p for p in parts if p['assembly_id'] in want]
    return parts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--schedules', default=os.path.join(HERE, 'schedules'))
    ap.add_argument('--out', default=os.path.join(HERE, 'rebuilt_model.step'))
    ap.add_argument('--parts', default='')
    ap.add_argument('--role', default='')
    ap.add_argument('--mark', default='', help='piece mark(s), comma separated')
    ap.add_argument('--assembly', default='', help='assembly mark(s), comma separated (nested assemblies included)')
    ap.add_argument('--assembly-id', default='', help='assembly id(s) (IFC GlobalId of the assembly), comma separated '
                                                      '(nested assemblies included)')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--list-parts', action='store_true', help='print the part ids the selection builds and exit')
    a = ap.parse_args()
    import steelbuild
    sched = steelbuild.Schedules(a.schedules)
    asm = read_assemblies(a.schedules)
    if a.assembly_id:
        unknown = [m.strip() for m in a.assembly_id.split(',') if m.strip() not in asm and
                   not any(p['assembly_id'] == m.strip() for p in sched.parts)]
        if unknown:
            sys.exit(f'unknown assembly id(s): {", ".join(unknown)} (see schedules/assemblies.csv)')
    parts = select(sched.parts, asm, a.parts, a.role, a.mark, a.assembly, a.assembly_id)
    if not parts:
        sys.exit('no parts match the selection')
    if a.list_parts:
        print('\n'.join(p['part_id'] for p in parts))
        return
    if a.list:
        from collections import Counter
        print(len(sched.parts), 'parts;', dict(Counter(p['role'] for p in sched.parts)), dict(Counter(p['geometry'] for p in sched.parts)))
        swept = f' ({len(sched.paths)} swept along a path)' if sched.paths else ''
        print(f'{len(sched.profiles)} profiles, {len(sched.solids)} solids{swept}, {len(sched.cuts)} cuts, {len(sched.openings)} openings')
        if asm:
            print(f'{len(asm)} assemblies ({sum(1 for r in asm.values() if r.get("parent_id"))} nested in another)')
        return
    t0 = time.time()
    ids = [p['part_id'] for p in parts]
    results = {}
    if a.jobs > 1 and len(ids) > 50:
        from concurrent.futures import ProcessPoolExecutor
        n = max(1, len(ids) // (a.jobs * 8))
        chunks = [(a.schedules, ids[i:i + n]) for i in range(0, len(ids), n)]
        # shapes come back through pickling (build123d shapes are picklable)
        with ProcessPoolExecutor(a.jobs) as ex:
            for res in ex.map(_build_chunk, chunks):
                for pid, solids, err in res:
                    results[pid] = (solids, err)
    else:
        # the same serialisation round trip as the parallel path, so the output does not depend on --jobs
        import pickle
        for pid, solids, err in pickle.loads(pickle.dumps(_build_chunk((a.schedules, ids)))):
            results[pid] = (solids, err)
    errors = {pid: err for pid, (s, err) in results.items() if err}
    items = [(p, results[p['part_id']][0]) for p in parts if results[p['part_id']][0]]
    bad = steelbuild.write_step(items, a.out, name=os.path.basename(HERE))
    print(f'built {len(items)} of {len(parts)} parts in {time.time() - t0:.1f} s -> {a.out}')
    if bad:
        print(f'{bad} solids are not valid or not closed (listed above on stderr): a CAD tool reading the file may drop them')
    if errors:
        print(f'{len(errors)} parts failed:')
        for pid, err in errors.items():
            print(' ', pid, err)
        sys.exit(1)


if __name__ == '__main__':
    main()
