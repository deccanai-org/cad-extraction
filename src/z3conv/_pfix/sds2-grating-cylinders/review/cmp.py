import json,glob,os
jobs=sorted(os.listdir('v553h'))
def L(v,j):
    p=glob.glob(f'{v}/{j}/*_manifest.json')
    return json.load(open(p[0])) if p else None
for j in jobs:
    a,b=L('v553',j),L('v553h',j)
    if not a or not b: print(j,'missing',bool(a),bool(b)); continue
    ca,cb=a['counts'],b['counts']
    ra,rb=a['readback'],b['readback']
    sa,sb=a['standins']['by_type'],b['standins']['by_type']
    keys=sorted(set(sa)|set(sb))
    d={k:(sa.get(k,0),sb.get(k,0)) for k in keys if sa.get(k,0)!=sb.get(k,0)}
    print(f"== {j}: class {a['class']}{a['corpus']}->{b['class']}{b['corpus']} placed {ca['placed_pieces']}->{cb['placed_pieces']} written {ca['pieces_written']}->{cb['pieces_written']} exact {ca['pieces_exact']}->{cb['pieces_exact']} approx {ca['pieces_approx']}->{cb['pieces_approx']} skipped {a['skipped']['total']}->{b['skipped']['total']}")
    print(f"   readback solids {ra.get('solids')}/{ra.get('valid')} inv {ra.get('invalid')} -> {rb.get('solids')}/{rb.get('valid')} inv {rb.get('invalid')}; ratio {a['weight_check']['ratio']}->{b['weight_check']['ratio']}; stand-ins {a['standins']['total']}->{b['standins']['total']}")
    print('   standin diffs',d)
    print('   skipped',a['skipped']['by_reason'],'->',b['skipped']['by_reason'])
    print('   grating',{k:v for k,v in b.get('grating',{}).items() if k!='note'})
    print('   rods',b.get('rods'))
    print('   reasons', b['class_reasons'][:3])
