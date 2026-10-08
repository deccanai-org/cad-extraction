#!/usr/bin/env python3
"""sds2_probe.py - run ONE pinned SDS/2 converter build on a job folder with read-only instrumentation and dump what it
decoded that the restoration needs (converter env /opt/conv, python 3.12).

Nothing the converter computes is changed: the wrappers only record arguments / results of
  bolts.member_bolts      SDS/2's own bolt records per member (head point, axis, dia, length, grip, type, layout)
  to_step2.bolt_stacks    coaxial decoded hole stacks of >= 2 pieces (the nominal-bolt candidates)
  to_step2.derive_bolt_holes  the converter's bolt list (todo: records + nominal) and the placed decoded holes (hw)
and afterwards it reads members / pieces / bolt types with the converter's own readers.

usage: sds2_probe.py CONV_ROOT JOB_DIR OUT_DIR [--no-step]
  CONV_ROOT  the converter tree (contains decode/sds2_to_step.py)
  writes OUT_DIR/probe.json and (unless --no-step) OUT_DIR/<job>_stage2.step + the converter's side tables
"""
import json, os, runpy, sys, collections, time

conv_root, job, out = sys.argv[1], sys.argv[2], sys.argv[3]
no_step = '--no-step' in sys.argv
dec = os.path.join(conv_root, 'decode')
sys.path.insert(0, dec)
os.makedirs(out, exist_ok=True)
import numpy as np  # noqa: E402
import bolts as BR  # noqa: E402
import to_step2  # noqa: E402

CAP = dict(member_bolts=[], stacks_out=None, derive=None, t0=time.time())


def _j(v):
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


_mb = BR.member_bolts


def member_bolts(job_, n, frame=None):
    r = _mb(job_, n, frame)
    CAP['member_bolts'].append(dict(member=n, frame=None if frame is None else [np.asarray(frame[0]).tolist(), np.asarray(frame[1]).tolist()],
                                    recs=[{k: _j(v) for k, v in x.items()} for x in r]))
    return r


BR.member_bolts = member_bolts
_bs = to_step2.bolt_stacks


def bolt_stacks(C, A, D, T, I):
    r = _bs(C, A, D, T, I)
    CAP['stacks_out'] = [dict(entry=np.asarray(e).tolist(), axis=np.asarray(a).tolist(), grip=float(g), dia=float(d)) for e, a, g, d in r]
    return r


to_step2.bolt_stacks = bolt_stacks
_dh = to_step2.derive_bolt_holes


def derive_bolt_holes(job_, todo, hw, shared_inst, stats, *a, **k):
    r = _dh(job_, todo, hw, shared_inst, stats, *a, **k)
    CAP['derive'] = dict(
        todo=[dict(e=np.asarray(t[0]).tolist(), a=np.asarray(t[1]).tolist(), grip=float(t[2]), d=float(t[3]),
                   L=(None if t[4] is None else float(t[4])), ty=str(t[5]), src=t[6]) for t in todo],
        hw=[dict(entry=np.asarray(h[0]).tolist(), axis=np.asarray(h[1]).tolist(), depth=float(h[2]), bolt=float(h[3]),
                 row=int(h[4]), dia=float(h[5]), slot=float(h[6]), piece=int(h[7])) for h in hw],
        derived_by_piece={str(k_): _j(v) for k_, v in (r or {}).get('derived_by_piece', {}).items()},
        not_cut={str(k_): _j(v) for k_, v in dict((r or {}).get('not_cut', {})).items()})
    return r


to_step2.derive_bolt_holes = derive_bolt_holes

name = os.path.basename(job.rstrip('/')).replace(' ', '_')
step = os.path.join(out, f'{name}_stage2.step')
if not no_step:
    sys.argv = ['sds2_to_step.py', job, '-o', step, '--stage', '2', '--verify']
    try:
        runpy.run_path(os.path.join(dec, 'sds2_to_step.py'), run_name='__main__')
    except SystemExit as e:
        CAP['converter_exit'] = str(e.code)
else:
    to_step2.convert(job, step)

from sds2job import read_members  # noqa: E402
from piece_table import read_pieces  # noqa: E402
mems, _ = read_members(job)
CAP['members'] = [dict(id=m.id, type=m.type, section=(m.section.name if m.section else None),
                       p1=np.asarray(m.p1).tolist(), p2=np.asarray(m.p2).tolist()) for m in mems]
pieces = read_pieces(job)
CAP['pieces'] = {str(k): {kk: (vv if isinstance(vv, (int, float, str, type(None))) else str(vv)) for kk, vv in
                          (p.items() if isinstance(p, dict) else vars(p).items())} for k, p in pieces.items()}
CAP['bolt_types'] = {str(k): v for k, v in BR.bolt_types(job).items()}
# every bolt record of the job read with the converter's main-material frames AND with the header frames (both views)
try:
    fr = BR.main_frames(job, pieces)
except Exception as e:  # noqa: BLE001
    fr = {}
    CAP['main_frames_error'] = repr(e)
allrec = []
for m in mems:
    for how, f in (('main', fr.get(m.id)), ('header', None)):
        try:
            rr = _mb(job, m.id, f)
        except Exception as e:  # noqa: BLE001
            rr = []
        for r in rr:
            allrec.append(dict({k: _j(v) for k, v in r.items()}, frame=how))
CAP['all_records'] = allrec
CAP['seconds'] = round(time.time() - CAP.pop('t0'), 1)
json.dump(CAP, open(os.path.join(out, 'probe.json'), 'w'))
nrec = sum(len(x['recs']) for x in CAP['member_bolts'])
print('members', len(mems), 'record calls', len(CAP['member_bolts']), 'records', nrec,
      'layouts', dict(collections.Counter(r['layout'] for x in CAP['member_bolts'] for r in x['recs'])),
      'stacks', len(CAP['stacks_out'] or []),
      'todo', dict(collections.Counter(t['src'] for t in CAP['derive']['todo'])) if CAP['derive'] else None,
      'all_records', len(allrec))
