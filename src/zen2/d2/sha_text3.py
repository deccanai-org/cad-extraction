import sys, struct, collections, olefile, re, math, pymupdf
SRC='/work/in/src/'
def recs(b):
    k=8; out=[]
    while k+6<=len(b):
        t,ln=struct.unpack_from('<HI',b,k); out.append((t,b[k+6:k+6+ln])); k+=6+ln
    return out
PR=re.compile(r'^[\x20-\x7e°±Øø⌀]+$')
def find_str(p):
    best=None
    for k in range(18, len(p)-3):
        L=struct.unpack_from('<H',p,k)[0]
        if 1<=L<=4000 and k+2+2*L<=len(p):
            try: s=p[k+2:k+2+2*L].decode('utf-16le')
            except: continue
            if PR.match(s) and (best is None or L>best[1]): best=(k,L,s)
    return best
def find_pos(p, start):
    for k in range(start, len(p)-31):
        x,y,c,s=struct.unpack_from('<4d',p,k)
        if -0.01<=x<=1.3 and -0.01<=y<=1.0 and abs(c*c+s*s-1)<1e-6 and (abs(x)>1e-4 or abs(y)>1e-4): return k,(x,y,c,s)
    return None
def main():
    o=olefile.OleFileIO(SRC+sys.argv[1])
    pg=pymupdf.open(SRC+sys.argv[2])[0]; H=pg.rect.height
    spans={}
    for b in pg.get_text('dict')['blocks']:
        for l in b.get('lines',[]):
            for sp in l['spans']:
                spans.setdefault(sp['text'].strip(),[]).append((sp['origin'][0]*25.4/72e3,(H-sp['origin'][1])*25.4/72e3, sp['size']*25.4/72e3, sp['bbox']))
    stats=collections.Counter(); offs=[]
    for n in sys.argv[3].split(','):
        for t,p in recs(o.openstream(n).read()):
            if t&0x7fff!=77: continue
            r=find_str(p)
            if not r: stats['nostr']+=1; continue
            k,L,s=r; q=find_pos(p,k+2+2*L)
            if not q: stats['nopos']+=1; continue
            stats['ok']+=1
            x,y,c,sn=q[1]
            if s.strip() in spans:
                best=min(spans[s.strip()], key=lambda v: math.hypot(v[0]-x,v[1]-y))
                dx,dy=best[0]-x,best[1]-y
                if math.hypot(dx,dy)<0.05: offs.append((round(dx*1000,2),round(dy*1000,2),round(best[2]*1000,2),s[:20],round(math.degrees(math.atan2(sn,c))), q[0]-(k+2+2*L)))
    print(stats)
    for v in offs[:25]: print(v)

if __name__ == '__main__':
    main()
