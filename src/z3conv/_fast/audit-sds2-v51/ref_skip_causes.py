"""Break down v5.1 'reference_part_no_closed_brep' skips by real cause, re-running v5.1's own brep.parse / brep.solid on the
piece files of the skipped and written pieces (identity placement; placement validity is checked separately from the CSV)."""
import sys, os, csv, json, collections, time
sys.path.insert(0, 'pipe/v5.1/sds2-step-pipeline/decode')
import brep
from OCP.BRepCheck import BRepCheck_Analyzer
out = {}
for jid, n in [('ee874b2b9130bd7d16a99a7a', 'I1SD_ee874b'), ('ddb0f89cfda203135cecdcf0', 'fgfg_ddb0f8')]:
    sk = list(csv.DictReader(open(f's3/out/{jid}/v5.1/{n}_stage2_skipped.csv', errors='replace')))
    wr = list(csv.DictReader(open(f's3/out/{jid}/v5.1/{n}_stage2_pieces.csv', errors='replace')))
    res = {}
    for sid in sorted(set(r['piece'] for r in sk) | set(r['piece'] for r in wr), key=int):
        b = open(f'jobs/{n}/subm/{sid}', 'rb').read()
        try:
            r = brep.parse(b)
        except Exception as e:
            res[sid] = ('parse_exception', 0, 0); continue
        if r is None:
            res[sid] = ('parse_none', 0, len(b)); continue
        V, F = r[0], r[1]
        if len(F) > 20000:
            res[sid] = ('too_many_faces', len(F), len(V)); continue
        try:
            sh = brep.solid(V, F)
        except Exception:
            sh = None
        if sh is None:
            # open shell? count faces + free edges is costly; record face/vertex counts
            res[sid] = ('no_closed_solid', len(F), len(V))
        else:
            res[sid] = ('solid_ok' + ('' if BRepCheck_Analyzer(sh).IsValid() else '_invalid'), len(F), len(V))
    skc = collections.Counter(res[r['piece']][0] for r in sk)
    sk_pieces = collections.Counter(res[s][0] for s in set(r['piece'] for r in sk))
    wrc = collections.Counter(res[r['piece']][0] for r in wr)
    faces_sk = collections.Counter(res[s][1] for s in set(r['piece'] for r in sk))
    out[n] = {'skipped_placements_by_cause': dict(skc), 'skipped_pieces_by_cause': dict(sk_pieces), 'written_placements_by_cause': dict(wrc),
              'skipped_piece_face_counts_top': faces_sk.most_common(8)}
    print(n, json.dumps(out[n]))
json.dump(out, open('out/ref_skip_causes.json', 'w'), indent=1)
