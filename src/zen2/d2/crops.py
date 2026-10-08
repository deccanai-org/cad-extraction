import sys, glob, io, numpy as np
from PIL import Image
sys.path.insert(0,'/work/2d'); import pdf2dxf as P
rel, pno, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
boxes=[tuple(map(int,b.split(','))) for b in sys.argv[4:]]
od='/work/2d/qa/'+rel
ref=np.asarray(Image.open(sorted(glob.glob(f'/work/out/png/{glob.escape(rel)}/page-*{pno}.png'))[0]).convert('RGB'))
ren=np.asarray(Image.open(f'{od}/render-{pno}.png').convert('RGB'))
tiles=[]
for (x,y,w,h) in boxes:
    a=ref[y:y+h,x:x+w]; b=ren[y:y+h,x:x+w]
    ma=a.min(2)<235; mb=b.min(2)<235
    d=np.full(a.shape,255,np.uint8); d[ma&mb]=0; d[ma&~mb]=(230,0,0); d[~ma&mb]=(0,90,255)
    tiles.append(np.concatenate([a,np.full((h,4,3),128,np.uint8),b,np.full((h,4,3),128,np.uint8),d],1))
W=max(t.shape[1] for t in tiles)
img=np.concatenate([np.pad(t,((0,6),(0,W-t.shape[1]),(0,0)),constant_values=200) for t in tiles],0)
Image.fromarray(img).save(out)
