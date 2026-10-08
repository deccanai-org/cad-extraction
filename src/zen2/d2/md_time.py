import sys, time, glob, os
sys.path.insert(0,'/work/2d')
import sha2json, sha2dxf, pdf2dxf, md_run
for f in sorted(glob.glob('/work/md/sample/sha/*ISO*.sha'))[:4]:
    t=time.time(); j=sha2json.convert(f,'x',''); t1=time.time()
    dec=sha2dxf.Decoder(f); dec.run(); doc=dec.to_dxf(); t2=time.time()
    doc.saveas('/tmp/mdt.dxf'); W,H=md_run.sheet_size(doc); t3=time.time()
    png=pdf2dxf.render_dxf('/tmp/mdt.dxf',W,H,dpi=100); t4=time.time()
    print(os.path.basename(f)[:40], 'json %.2f decode %.2f save %.2f render %.2f png %d KB'%(t1-t, t2-t1, t3-t2, t4-t3, len(png)//1024), W, H)
