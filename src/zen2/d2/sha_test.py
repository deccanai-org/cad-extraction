import sys, os, glob, time, math, collections
sys.path.insert(0,'/work/2d')
import pdf2dxf as P, sha2dxf as S, numpy as np, pymupdf
SRC='/work/in/src/'
sha, pdf, tag = sys.argv[1], sys.argv[2], sys.argv[3]
od='/work/2d/qa_sha'; os.makedirs(od, exist_ok=True)
t0=time.time(); dec=S.Decoder(SRC+sha); dec.run()
print(dict(dec.stats)); print('unknown', dec.unknown.most_common(14))
pg=pymupdf.open(SRC+pdf)[0]; W=pg.rect.width*P.PT; H=pg.rect.height*P.PT; Hp=pg.rect.height
spans=collections.defaultdict(list)
for b in pg.get_text('dict')['blocks']:
    for l in b.get('lines',[]):
        for sp in l['spans']: spans[sp['text'].strip()].append((sp['origin'][0]*P.PT/1000,(Hp-sp['origin'][1])*P.PT/1000,sp['size']*P.PT/1000, sp['font']))
rat=collections.defaultdict(list)
for kind,d,lay,w in dec.ents:
    if kind!='text': continue
    (x,y),s,h,ang,just,face=d
    c=[v for v in spans.get(s.strip(),[]) if math.hypot(v[0]-x,v[1]-y)<0.02]
    if c and h>0: rat[(face,c[0][3])].append(round(c[0][2]/h,3))
for k,v in rat.items(): print('height ratio pdf_size/font_h', k, len(v), sorted(v)[len(v)//2], min(v), max(v))
doc=dec.to_dxf(); f=f'{od}/{tag}.dxf'; doc.saveas(f)
png=P.render_dxf(f,W,H); out=P.ink_mask(png)
ref=P.ink_mask(sorted(glob.glob('/work/out/png/'+glob.escape(pdf)+'/page-*1.png'))[0])
res,sh=P.compare(ref,out); print(res, 'sec %.1f'%(time.time()-t0))
P.diff_image(ref,sh,f'{od}/{tag}-diff.png',scale=0.35); open(f'{od}/{tag}-render.png','wb').write(png)
