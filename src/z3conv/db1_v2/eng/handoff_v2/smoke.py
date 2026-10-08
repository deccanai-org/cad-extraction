import sys, json, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.append('/Users/dhiren/Downloads/Deccan/z3conv/db1')
import db1step
cat = json.load(open('/Users/dhiren/Downloads/Deccan/z3conv/db1/tekla_profiles.json'))
L = json.load(open('layouts.json')); VA = [v['layout'] for v in L.values() if v.get('layout')]
D = '/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/eng/data/'
for f, eng in [(D + '7.30_template.db1', '7.30'), (D + '8.07_no_member_layout_e011e3f7f2.db1', '8.07'), (D + '8.85_no_member_layout_4faa624772.db1', '8.85'),
               (D + '8.85_suspect_attr_link_80bd353ac7.db1', '8.85'), (D + '9.08_ok_f34e32d507.db1', '9.08')]:
    t = time.time(); st = db1step.convert(f, '/tmp/eng_smoke.ifc', cat, (L.get(eng) or {}).get('layout'), VA, False)
    print(os.path.basename(f), st.get('status'), 'members', st.get('members'), 'written', st.get('written'), 'variant', (st.get('layout') or {}).get('variant'),
          'contour', (st.get('sources') or {}).get('contour_plate'), 'no_outline', (st.get('skipped') or {}).get('contour_plate_no_outline'),
          'empty_reason', st.get('empty_reason'), 'attr_ev', st.get('attr_link_evidence'), round(time.time() - t), 's', flush=True)
