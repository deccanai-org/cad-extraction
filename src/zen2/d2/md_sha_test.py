import sys, os, glob, time, json, collections
sys.path.insert(0, '/work/2d')
import sha2dxf as S, sha2json as J, pdf2dxf as P
for f in sorted(glob.glob('/work/md/sample/sha/*.sha')):
    t = time.time()
    rec = J.convert(f, os.path.basename(f), '')
    fl = rec['fields']
    dec = S.Decoder(f); dec.run()
    doc = dec.to_dxf(include_text=False)
    out = f[:-4] + '.dxf'; doc.saveas(out)
    ms = doc.modelspace()
    ext = None
    try:
        from ezdxf import bbox
        e = bbox.extents(ms); ext = (round(e.extmin.x), round(e.extmin.y), round(e.extmax.x), round(e.extmax.y))
    except Exception as ex:
        ext = str(ex)[:40]
    t1 = time.time() - t
    print(os.path.basename(f)[:50], 'fields', {k: fl.get(k) for k in ('drawing_number', 'sheet', 'title', 'revision')}, 'tagged', list(rec['tagged_text'].keys())[:5])
    print('   stats', dict(dec.stats), 'unknown', dec.unknown.most_common(6), 'ents', len(ms), 'ext', ext, 'sec %.1f' % t1, 'texts', len(dec.texts()))
