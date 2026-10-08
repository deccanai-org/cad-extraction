import json,glob,sys,os
fams=set(sys.argv[1].split(',')); files=sys.argv[2:]
N=int(os.environ.get('NSHOW','4'))
for f in files:
    d=json.load(open(f))
    for fam, L in (d.get('detail') or {}).items():
        if fam not in fams: continue
        print('=====', d['job'][:40], '--', fam, len(L))
        for r in L[:N]:
            r2={k:v for k,v in r.items() if k not in ('slot_hex','why','step_lb_minmax','turned') and v not in (None,[],{})}
            if 'shape' in r2: r2['shape']={k:(round(v,4) if isinstance(v,float) else v) for k,v in r2['shape'].items()}
            for k in ('L','W','T'):
                if isinstance(r2.get(k),float): r2[k]=round(r2[k],4)
            print('    ', json.dumps(r2)[:900])
