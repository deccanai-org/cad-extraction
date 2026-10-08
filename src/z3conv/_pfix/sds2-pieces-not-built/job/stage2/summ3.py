import json,sys,glob,collections
for f in sorted(glob.glob('*.v553p.json')):
    d=json.load(open(f))
    print('=====',d['job'],'slot',d['slot'],len(d['pieces']))
    agg=collections.defaultdict(list)
    for p in d['pieces']:
        pc=p.get('piece') or {}
        b=p.get('brep') or {}
        key=(p['reason'],p['name'][:14],p.get('kind'),p.get('file_bytes') if (p.get('file_bytes') or 0)<1000 else '>1k',
             'brep:'+('none' if not b else ('solid' if b.get('solid') else 'open')), p.get('brep_why','')[:50], p.get('special_why') or ('special ok' if p.get('special') else ''),
             str(p.get('gap_b'))[:60])
        agg[key].append((p['sid'],p['n_inst'],pc.get('L'),pc.get('W'),pc.get('T'),pc.get('wt'),b.get('wt_ratio'),b.get('edge_use'),b.get('degenerate_faces'),p.get('nominal_lb'),p.get('table_standin_lb'),(p.get('section') or {}).get('weight'),b.get('ext'),p.get('pv_ext'),p.get('mv_ext')))
    for k,v in sorted(agg.items(), key=lambda kv:-sum(x[1] for x in kv[1])):
        print(' ',sum(x[1] for x in v),'inst',len(v),'pcs',k)
        for x in v[:3]: print('     ',x)
