import re, os, glob, collections
num = lambda x: float(re.sub(r'[a-z]+$', '', x.split(',')[0]) or 0)
def parse(path):
    L = open(path, encoding='latin1').read().replace('\r', '').split('\n')
    i = L.index('ST'); hdr = [l.strip() for l in L[i + 1:i + 30] if not l.strip().startswith('**')]
    r = dict(file=os.path.basename(path), order=hdr[0], drawing=hdr[1], phase=hdr[2], mark=hdr[3], grade=hdr[4], qty=int(float(hdr[5] or 1)),
             prof=hdr[6], code=hdr[7], length=float(hdr[8]), holes=[])
    blk = None
    for l in L:
        s = l.strip()
        if re.fullmatch(r'[A-Z]{2}', s): blk = s; continue
        if not s or blk != 'BO': continue
        t = s.split()
        if t[0] in ('v', 'o', 'u', 'h') and len(t) >= 4:
            x = num(t[1]); y = num(t[2]); d = num(t[3])
            sl = num(t[5]) if len(t) >= 6 else 0.0; sw = num(t[6]) if len(t) >= 7 else 0.0; sa = num(t[7]) if len(t) >= 8 else 0.0
            r['holes'].append(dict(face=t[0], x=x, y=y, d=d, sl=sl, sw=sw, sa=sa))
    return r
def load_dir(d):
    return [parse(p) for p in sorted(glob.glob(os.path.join(d, '*.nc1')) + glob.glob(os.path.join(d, '*.nc')))]
if __name__ == '__main__':
    import sys
    R = load_dir(sys.argv[1])
    c = collections.Counter(); cs = collections.Counter()
    for r in R:
        for h in r['holes']:
            c[(r['prof'].split('*')[0][:6], h['d'], h['sl'] > 0)] += r['qty']
            if h['sl'] > 0: cs[(h['sl'], h['sw'], h['sa'], h['face'])] += r['qty']
    print(len(R)); print(c.most_common(30)); print(cs.most_common(20))
