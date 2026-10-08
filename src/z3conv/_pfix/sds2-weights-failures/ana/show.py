import json,glob,sys
files = sys.argv[1:] or sorted(glob.glob('*.json'))
for f in files:
    d=json.load(open(f))
    print('=====', d['job'], 'layout', d.get('piece_layout'), d.get('error') or '', d.get('detail_error') or '')
    for x in d.get('fam_builder',[]):
        if x['fam'] in d.get('focus',[]): print('   ', x)
    for fam, L in (d.get('detail') or {}).items():
        print('  --', fam, len(L))
        for r in L[:int(__import__('os').environ.get('NSHOW','5'))]:
            r2={k:v for k,v in r.items() if k not in ('slot_hex','why','step_lb_minmax','turned') and v not in (None,[],{})}
            if 'shape' in r2: r2['shape']={k:(round(v,4) if isinstance(v,float) else v) for k,v in r2['shape'].items()}
            for k in ('L','W','T'):
                if isinstance(r2.get(k),float): r2[k]=round(r2[k],4)
            print('    ', json.dumps(r2)[:800])
