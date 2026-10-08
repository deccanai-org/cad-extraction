"""selfcheck.py SRC DB1 OUT.json : decode with the eng decoder and record layout/variant, members, profiles, axis agreement,
web-vertical share, COLUMN-name check, plates with outlines, fittings/line cuts, attr-link evidence"""
import sys, json, time, re, collections, os
src, f, out = sys.argv[1:4]
sys.path.insert(0, src); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db1dec, fittings, attrlink
from db1dec import decode, members, load, PLATE1_RE
L = json.load(open(os.path.join(src, 'layouts.json'))); VA = [v['layout'] for v in L.values() if v.get('layout')]
t = time.time(); data = load(f)
m_ = re.search(rb'(\d+\.\d+)', data[:16]); eng = m_.group(1).decode() if m_ else None
db, pts, cs, lay = decode(data, (L.get(eng) or {}).get('layout'), VA, len(data) < 20_000_000)
M = members(db, pts, cs, lay) if lay and lay.get('csys') is not None else []
r = dict(file=os.path.basename(f), engine=eng, mb=round(len(data) / 1e6, 1), decode_sec=round(time.time() - t), members=len(M),
         profiles=sum(1 for m in M if m['prof']), layout={k: v for k, v in (lay or {}).items() if k != 'tried'})
if M:
    r['axis_agreement'] = db1dec._axis_agreement(db, pts, lay, M); r['web_vertical'] = db1dec._web_vertical(M)
    cp = [m for m in M if m['prof'] and PLATE1_RE.match(m['prof']) and not m['cut']]
    r['contour_plates'] = len(cp); r['plates_with_outline'] = sum(1 for m in cp if db.polygon(lay, m))
    db.find_cut_links(M)
    F, C, fi = fittings.decode_all(db, cs, lay, M); r['fittings'] = fi
    r['attr_link_evidence'] = attrlink.evidence(db, lay, M); r['attr_link_confirmed'] = attrlink.confirmed(r['attr_link_evidence'])
    r['top_profiles'] = collections.Counter(m['prof'] for m in M if not m['cut']).most_common(10)
json.dump(r, open(out, 'w'), default=str)
print(json.dumps(r, default=str)[:600])
