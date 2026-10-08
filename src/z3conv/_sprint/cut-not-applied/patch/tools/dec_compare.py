"""dec_compare.py DIR_BEFORE DIR_AFTER : per model, decode-level effect of the patch (parts, cuts, linkable cuts, phantom cut bodies)"""
import sys, os, json, glob, collections
A, B = sys.argv[1], sys.argv[2]
def stats(d):
    P = {p[0]: p for p in d['parts']}
    ok = {p[0] for p in d['parts'] if p[7] is not False}       # axis guard drops the others
    cuts = {i for i in ok if P[i][2]}; real = {i for i in ok if not P[i][2] and not P[i][3]}
    rel = {int(k): v for k, v in d['cut_rel'].items()}
    pairs = [(p_, c_) for p_, cs in rel.items() for c_ in cs]
    linkable = [(p_, c_) for p_, c_ in pairs if p_ in real and c_ in cuts]
    phantom = [i for i in real if P[i][4] == 11]                 # boolean operative parts written as steel
    linked_cuts = {c_ for p_, c_ in linkable}
    return dict(parts=len(ok), real=len(real), cuts=len(cuts), pairs=len(pairs), linkable=len(linkable), cuts_linked=len(linked_cuts),
                cuts_unlinked=len(cuts - {c_ for _, c_ in pairs}), cuts_parent_missing=len({c_ for p_, c_ in pairs if c_ in cuts and p_ not in P}),
                phantom_type11_steel=len(phantom), info=d.get('info', {}))
rows = []
tot = collections.Counter()
for fa in sorted(glob.glob(os.path.join(A, '*.json'))):
    fb = os.path.join(B, os.path.basename(fa))
    if not os.path.exists(fb): continue
    a, b = json.load(open(fa)), json.load(open(fb))
    if 'parts' not in a: continue
    sa, sb = stats(a), stats(b)
    PA = {p[0]: p for p in a['parts']}; PB = {p[0]: p for p in b['parts']}
    new = [PB[i] for i in PB if i not in PA]; gone = [PA[i] for i in PA if i not in PB]
    newp = collections.Counter((p[1], 'cut' if p[2] else 'part') for p in new)
    tocut = collections.Counter(PB[i][1] for i in PB if i in PA and PB[i][2] and not PA[i][2])
    rows.append((os.path.basename(fa)[:16], a['engine'], sa, sb, len(new), len(gone), newp, tocut))
    for k in ('parts', 'real', 'cuts', 'linkable', 'phantom_type11_steel'):
        tot[k + '_before'] += sa[k]; tot[k + '_after'] += sb[k]
    tot['new_parts'] += len(new); tot['gone'] += len(gone)
for r in sorted(rows, key=lambda r: (r[1], r[0])):
    n, e, sa, sb, nn, ng, newp, tocut = r
    print('%s %.2f parts %d->%d real %d->%d cuts %d->%d linkable %d->%d (pairs %d->%d) unlinked %d->%d parent_missing %d->%d phantom %d->%d | new %d gone %d | salv %s strides %s'
          % (n, e, sa['parts'], sb['parts'], sa['real'], sb['real'], sa['cuts'], sb['cuts'], sa['linkable'], sb['linkable'], sa['pairs'], sb['pairs'],
             sa['cuts_unlinked'], sb['cuts_unlinked'], sa['cuts_parent_missing'], sb['cuts_parent_missing'], sa['phantom_type11_steel'], sb['phantom_type11_steel'],
             nn, ng, sb['info'].get('attr_salvaged'), sb['info'].get('relation_type11_by_stride')))
    if newp or tocut:
        print('      new parts', newp.most_common(5), '| became cut bodies', tocut.most_common(5))
print('TOTAL', dict(tot))
