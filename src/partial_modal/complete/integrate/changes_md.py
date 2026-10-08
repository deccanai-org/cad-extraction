#!/usr/bin/env python3
"""CHANGES.md of a COMPLETED model, in plain language: per colour what was done, where (landmarks + mm coordinates),
why (source field / standard / basis) and how many; plus what did NOT change and the checks.

    python3 changes_md.py --tree scripts/<model> [--verification completed/verification.json] --out completed/CHANGES.md
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import completion_core as cc          # noqa: E402

ORDER = ['GREEN', 'BLUE', 'AMBER', 'MAGENTA', 'RED']
WORD = {'GREEN': 'Restored exactly from the source file', 'BLUE': 'Built from industry standard tables',
        'AMBER': 'Estimated (no exact data, no standard)', 'MAGENTA': 'Still not exact (shown honestly)',
        'RED': 'Position only (marker)'}


def n(v):
    return f'{v:,.0f}'


def centre(bb):
    if not bb or len(bb) != 6:
        return ''
    c = [(bb[i] + bb[i + 3]) / 2 for i in range(3)]
    return f'x {n(c[0])}, y {n(c[1])}, z {n(c[2])} mm'


def extent(bbs):
    bbs = [b for b in bbs if b and len(b) == 6]
    if not bbs:
        return ''
    lo = [min(b[i] for b in bbs) for i in range(3)]
    hi = [max(b[i + 3] for b in bbs) for i in range(3)]
    return f'x {n(lo[0])}..{n(hi[0])}, y {n(lo[1])}..{n(hi[1])}, z {n(lo[2])}..{n(hi[2])} mm'


def why_of(pv, col):
    if col == 'GREEN':
        return pv.get('source')
    if col == 'BLUE':
        return pv.get('standard')
    if col == 'AMBER':
        return 'estimated - ' + str(pv.get('basis'))
    if col == 'RED':
        return pv.get('source') or pv.get('basis')
    if col == 'MAGENTA':
        return (pv.get('evidence') or {}).get('baseline_flag') or pv.get('op')
    return ''


def short_what(s):
    """group key: the 'what' without per-part numbers after a colon"""
    s = str(s or '')
    return s.split(' | ')[0][:160]


def render(comp, ver=None):
    L = []
    name, tag = comp['model_name'], comp.get('tag', '')
    cnt, tot = comp['counts'], comp['totals']
    L.append(f'# {name}: what the COMPLETED model changes')
    L.append('')
    L.append(f"Sample `{tag}` ({comp.get('step_source')} model, model id `{str(comp.get('model_id'))[:16]}...`). "
             f"The ORIGINAL is the delivered STEP (`{(comp.get('delivered') or {}).get('relpath', 'model/step/...')}`), "
             f"unchanged. The COMPLETED model is that model with every gap we could close closed: "
             f"{n(tot['parts'])} parts (original rebuild: {n(tot['baseline_parts'])}).")
    L.append('')
    L.append('Every part has exactly one colour, and every colour means one thing:')
    L.append('')
    L.append('| colour | parts | means |')
    L.append('|---|---:|---|')
    for c in cc.COLOURS:
        L.append(f"| **{c}** | {n(cnt.get(c, 0))} | {comp['meaning'][c]} |")
    L.append('')
    L.append('In the coloured STEP each part\'s name starts with its colour word (`GREEN-RESTORED`, `BLUE-STANDARD`, '
             '`AMBER-ESTIMATED`, `MAGENTA-NOT-EXACT`, `RED-POSITION-ONLY`; grey parts keep their own name), says what '
             'was done and on what basis, then `| <part id> <name>`. One folder per colour: hide GREY to see only what '
             'changed. `schedules/completion.json` has the same record per part, machine readable.')
    L.append('')
    L.append('## Files')
    L.append('')
    L.append(f'* `completed/{name}_COMPLETED.step`: the completed model, colour-coded.')
    L.append(f'* `completed/{name}_COMPLETED_plain.step`: the same solids, no colours (= `build_model.py` output).')
    L.append('* `build_model.py` builds the completed model from `schedules/`; `build_completed_coloured.py` writes both '
             'STEPs (deterministic: the same bytes every run). `schedules_original/` is the original rebuild\'s schedules '
             '(`build_issues_model.py` reads it).')
    L.append('')
    # ---- unchanged
    ut = comp.get('untouched') or {}
    bc = ((comp.get('build') or {}).get('checks')) or {}
    L.append('## What did not change')
    L.append('')
    L.append(f"* {n(cnt.get('GREY', 0))} parts are GREY: original geometry, verified against the source, unchanged.")
    if ut:
        L.append(f"* Parts no fix touched: {n(ut.get('n', 0))}; their schedule rows are byte-identical to the original "
                 f"rebuild's in {n(ut.get('rows_identical', 0))} of {n(ut.get('n', 0))}"
                 + (f"; built, {n(bc.get('untouched_identical', 0))} have exactly the original volume and bounding box"
                    f" ({n(bc.get('untouched_differs', 0))} differ)." if bc else '.'))
    if comp.get('removed'):
        L.append(f"* Removed: {len(comp['removed'])} part(s) (proven duplicates of the conversion): "
                 + ', '.join(f"`{r['part_id']}` ({r.get('name', '')})" for r in comp['removed'][:10]))
    L.append('')
    # ---- per colour
    parts = comp.get('parts') or {}
    for col in ORDER:
        mine = [(pid, e) for pid, e in parts.items() if e.get('colour') == col]
        L.append(f'## {col}: {WORD[col]} ({n(len(mine))} parts)')
        L.append('')
        if not mine:
            L.append('None.' if col not in ('MAGENTA', 'RED') else 'None (as it should be).')
            L.append('')
            continue
        groups = collections.OrderedDict()
        for pid, e in mine:
            pv = [x for x in e.get('provenance') or [] if x.get('colour') == col] or (e.get('provenance') or [{}])
            key = short_what(pv[0].get('what'))
            g = groups.setdefault(key, dict(ids=[], where=collections.Counter(), why=collections.Counter(), bbs=[],
                                            status=collections.Counter(), tracks=collections.Counter()))
            g['ids'].append(pid)
            g['bbs'].append(e.get('bbox'))
            g['status'][e.get('status')] += 1
            for t in e.get('tracks') or []:
                g['tracks'][t] += 1
            if e.get('where'):
                g['where'][str(e['where'])[:160]] += 1
            for x in pv:
                w = why_of(x, col)
                if w:
                    g['why'][str(w)[:220]] += 1
        L.append('| what | parts | where | why (basis) |')
        L.append('|---|---:|---|---|')
        for key, g in sorted(groups.items(), key=lambda kv: -len(kv[1]['ids'])):
            where = '; '.join(w for w, _ in g['where'].most_common(2))
            ext = extent(g['bbs'])
            where = (where + ('<br>' if where and ext else '') + (f'within {ext}' if ext else '')) or '-'
            why = '; '.join(w for w, _ in g['why'].most_common(2)) or '-'
            L.append(f"| {key.replace('|', '/')} | {n(len(g['ids']))} | {where.replace('|', '/')} | "
                     f"{why.replace('|', '/')} |")
        L.append('')
        L.append('<details><summary>part ids, one per line, with location</summary>')
        L.append('')
        for pid, e in mine[:400]:
            L.append(f"* `{pid}` {cc.ascii_text(e.get('name'), 60)}: {e.get('status')}; at {centre(e.get('bbox')) or '?'}"
                     + (f"; {e['where']}" if e.get('where') else ''))
        if len(mine) > 400:
            L.append(f'* ... {len(mine) - 400} more in schedules/completion.json')
        L.append('')
        L.append('</details>')
        L.append('')
    # ---- unresolved / warnings / checks
    un = comp.get('unresolved') or []
    if un:
        L.append('## Problems of the original that are still open')
        L.append('')
        L.append('These baseline flags were not fixed by any track; their parts are MAGENTA above.')
        L.append('')
        cc_ = collections.Counter(u['category'] for u in un)
        L.append('| original flag | parts |')
        L.append('|---|---:|')
        for k, v in cc_.most_common():
            L.append(f'| {k} | {v} |')
        L.append('')
    if comp.get('conflicts'):
        L.append('## Parts two tracks treated differently')
        L.append('')
        L.append('The part carries the weaker colour (RED > MAGENTA > AMBER > BLUE > GREEN) and its name lists both.')
        L.append('')
        for c in comp['conflicts'][:60]:
            L.append(f"* `{c['part_id']}`: " + '; '.join(f'{t} {"/".join(v)}' for t, v in c['tracks'].items())
                     + ' - ' + ' / '.join(c['what'][:3]))
        if len(comp['conflicts']) > 60:
            L.append(f"* ... {len(comp['conflicts']) - 60} more in schedules/completion.json")
        L.append('')
    if comp.get('warnings'):
        L.append('## Notes from the merge')
        L.append('')
        for w in comp['warnings'][:50]:
            L.append(f'* {w}')
        L.append('')
    L.append('## Checks')
    L.append('')
    b = comp.get('build') or {}
    if b:
        L.append(f"* Built with the shipped script: {n(b.get('parts_built', 0))} of {n(b.get('parts', 0))} parts; "
                 f"{n(b.get('invalid_or_open', 0))} with an invalid or open solid (MAGENTA).")
        ck = b.get('checks') or {}
        if ck:
            L.append('* ' + ', '.join(f'{k.replace("_", " ")} {v}' for k, v in sorted(ck.items())) + '.')
        vm = b.get('volume_mm3') or {}
        if vm:
            L.append(f"* Steel + other volume: completed {vm.get('completed', 0) / 1e9:,.3f} m3, original rebuild "
                     f"{vm.get('baseline', 0) / 1e9:,.3f} m3.")
    if ver:
        d = ver.get('determinism') or {}
        if d:
            L.append(f"* Determinism: two independent builds byte-identical: coloured {d.get('coloured_identical')}, "
                     f"plain {d.get('plain_identical')}.")
        rb = ver.get('readback') or {}
        if rb:
            L.append(f"* Read back as a viewer does (OpenCASCADE XCAF): {json.dumps(rb.get('counts'))}, label prefix "
                     f"mismatches {rb.get('label_prefix_mismatch')}.")
    ins = comp.get('inputs') or {}
    if ins:
        L.append('* Inputs (sha256): ' + '; '.join(f'`{k}` {v[:12]}' for k, v in sorted(ins.items())))
    L.append('')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tree', required=True)
    ap.add_argument('--verification', default=None)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    comp = json.load(open(os.path.join(a.tree, 'schedules', 'completion.json'), encoding='utf-8'))
    ver = json.load(open(a.verification)) if a.verification and os.path.exists(a.verification) else None
    out = a.out or os.path.join(a.tree, 'completed', 'CHANGES.md')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w', encoding='utf-8').write(render(comp, ver))
    print('->', out)


if __name__ == '__main__':
    main()
