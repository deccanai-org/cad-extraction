import sys, os, time, json, glob
sys.path.insert(0,'/work/2d')
import pymupdf, ezdxf
import pdf2dxf as P
SRC='/work/in/src/'
rels=sys.argv[1:]
os.makedirs('/work/2d/qa',exist_ok=True)
for rel in rels:
    doc=pymupdf.open(SRC+rel)
    for pno in range(doc.page_count):
        od='/work/2d/qa/'+rel; os.makedirs(od,exist_ok=True)
        dxfp=f'{od}/page-{pno+1}.dxf'
        t0=time.time(); c=P.PageConverter(doc,pno,dxfp); d=c.convert(f'page-{pno+1}'); t1=time.time()
        d.saveas(dxfp); t2=time.time()
        png=P.render_dxf(dxfp,c.W_mm,c.H_mm); t3=time.time()
        refs=sorted(glob.glob(f'/work/out/png/{glob.escape(rel)}/page-*{pno+1}.png'))
        ref=P.ink_mask(refs[0]); out=P.ink_mask(png)
        res,sh=P.compare(ref,out); t4=time.time()
        P.diff_image(ref,sh,f'{od}/diff-{pno+1}.png',scale=0.35)
        open(f'{od}/render-{pno+1}.png','wb').write(png)
        st={k:v for k,v in c.stats.items() if v}
        print(rel[-45:], pno+1, 'ref',ref.shape,'out',out.shape, res, 'size_MB %.1f'%(os.path.getsize(dxfp)/1e6), 't conv %.1f save %.1f render %.1f cmp %.1f'%(t1-t0,t2-t1,t3-t2,t4-t3))
        print('  ',st)
