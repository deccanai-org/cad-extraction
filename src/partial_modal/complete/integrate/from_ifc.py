#!/usr/bin/env python3
"""Form B (INTERFACES.md section 7): a track's completed SOURCE (model_completed.ifc + restoration_log.json), run through
the baseline pipeline (schedules of the completed IFC), turned into an ordinary patch:

  * part in both, construction rows equal (canonical, ids ignored)        -> nothing (baseline rows kept)
  * part in both, rows differ, the log says 'restored' (a geometry event) -> replace_part GREEN, geometry schedule_part,
                                                                             provenance = the log's events
  * part in both, rows differ, no restoration event                       -> baseline kept + warning (never claimed)
  * part only in the completed schedules                                   -> add_part GREEN (schedule_part)
  * part only in the baseline                                              -> baseline kept + warning

    python3 from_ifc.py --baseline SCHED_DIR --completed SCHED_DIR --log restoration_log.json --track db1 --tag T --out patch.json
"""
import argparse
import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import completion_core as cc          # noqa: E402

# restoration event kind -> the baseline issue categories it resolves
EVENT_RESOLVES = {
    'slotted_hole': ['slotted_holes_round', 'slotted_ply_round_holes'],
    'fitting_applied': ['fitting_not_applied'],
    'line_cut_applied': ['fitting_not_applied'],
}
GEOM_EVENT_KINDS = {'slotted_hole', 'fitting_applied', 'line_cut_applied', 'part_restored', 'profile_restored',
                    'contour_restored', 'bolt_restored', 'washer_restored', 'nut_restored'}


def event_text(ev):
    k = ev.get('kind', 'event')
    bits = [str(ev[f]) for f in ('what', 'detail', 'how') if ev.get(f)]
    fields = ev.get('field') or ev.get('fields') or ev.get('db1_field')
    if fields:
        bits.append('field ' + (', '.join(map(str, fields)) if isinstance(fields, list) else str(fields)))
    return f"{k}" + (f" ({'; '.join(bits)})" if bits else '')


def make_patch(baseline, completed, log, track, tag, model_id=None, source_label='DB1'):
    B, Cm = cc.src_schedules(baseline), cc.src_schedules(completed)
    lp = (log or {}).get('parts') or {}
    ops, warn = [], []
    stats = collections.Counter()
    for p in Cm['parts']:
        pid = p['part_id']
        le = lp.get(pid) or {}
        evs = le.get('events') or []
        rec = le.get('record')
        src = f"{source_label} record {rec}" if rec is not None else f"{source_label} (completed source, product {pid})"
        if pid in B['part']:
            same = cc.canonical_part(B, pid) == cc.canonical_part(Cm, pid)
            if same:
                stats['unchanged'] += 1
                continue
            geo = [e for e in evs if e.get('kind') in GEOM_EVENT_KINDS] or (evs if le.get('geometry') == 'restored' else [])
            if le.get('geometry') != 'restored' and not geo:
                stats['changed_without_event_kept_baseline'] += 1
                warn.append(f'{pid}: completed-source schedules differ but the log has no restoration event '
                            f"(log geometry {le.get('geometry')!r}): baseline kept")
                continue
            res = []
            kinds = {e.get('kind') for e in geo}
            if kinds and kinds <= set(EVENT_RESOLVES):
                res = [{'part_id': pid, 'category': c} for k in sorted(kinds) for c in EVENT_RESOLVES[k]]
            op = {'op': 'replace_part', 'id': f'restore:{pid}', 'colour': 'GREEN', 'part_id': pid,
                  'geometry': {'kind': 'schedule_part', 'schedules': completed, 'part_id': pid},
                  'provenance': {'what': '; '.join(dict.fromkeys(event_text(e) for e in geo)) or 'restored from the source',
                                 'source': f"{src}: " + '; '.join(dict.fromkeys(event_text(e) for e in geo))[:300],
                                 'evidence': {'record': rec, 'events': geo[:20], 'log_geometry': le.get('geometry')}}}
            if res:
                op['resolves'] = res
            if p.get('name') and p['name'] != B['part'][pid].get('name'):
                op['part'] = {'name': p['name']}
            ops.append(op)
            stats['restored'] += 1
        else:
            op = {'op': 'add_part', 'id': f'new:{pid}', 'colour': 'GREEN',
                  'part': {k: p.get(k, '') for k in cc.PART_FIELDS if k not in ('geometry', 'note')},
                  'geometry': {'kind': 'schedule_part', 'schedules': completed, 'part_id': pid},
                  'provenance': {'what': f"part the shipped conversion dropped, decoded from the source: {p.get('name')}",
                                 'source': f"{src}" + (': ' + '; '.join(event_text(e) for e in evs)[:300] if evs else
                                                       ' (new product of the completion decode)'),
                                 'evidence': {'record': rec, 'events': evs[:20]}}}
            ops.append(op)
            stats['added'] += 1
    for p in B['parts']:
        if p['part_id'] not in Cm['part']:
            stats['missing_in_completed_kept'] += 1
            warn.append(f"{p['part_id']}: not in the completed source's schedules: baseline kept")
    return {'schema': cc.PATCH_SCHEMA, 'track': track, 'tag': tag, 'model_id': model_id,
            'generated_by': 'complete/integrate/from_ifc.py (Form B: completed source -> pipeline -> canonical diff)',
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'inputs': {}, 'ops': ops, 'notes': warn[:200], 'stats': dict(stats)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--completed', required=True)
    ap.add_argument('--log', default=None)
    ap.add_argument('--track', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--model-id', default=None)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    log = json.load(open(a.log)) if a.log and os.path.exists(a.log) else {}
    p = make_patch(a.baseline, a.completed, log, a.track, a.tag, a.model_id,
                   'DB1' if a.track == 'db1' else 'SDS/2' if 'sds2' in a.tag else 'IFC')
    json.dump(p, open(a.out, 'w'), indent=1)
    print(json.dumps(p['stats']))


if __name__ == '__main__':
    main()
