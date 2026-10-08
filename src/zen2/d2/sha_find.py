import sys, struct, olefile, numpy as np
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1])
targets=[float(x) for x in sys.argv[2].split(',')]
tol=float(sys.argv[3]) if len(sys.argv)>3 else 1e-4
for s in o.listdir(streams=True, storages=False):
    n='/'.join(s); b=o.openstream(n).read()
    for k in range(8):
        a=np.frombuffer(b[k:len(b)-((len(b)-k)%8)],'<f8')
        for t in targets:
            with np.errstate(all='ignore'):
                idx=np.nonzero(np.abs(a-t)<=tol*max(1,abs(t)))[0]
            for i in idx[:6]:
                off=k+8*i
                ctx=np.frombuffer(b[max(0,off-48):off+56][: (len(b[max(0,off-48):off+56])//8)*8],'<f8') if off>=48 else None
                print(n[:38], 'off',off,'val',a[i], 'ctx', None if ctx is None else ' '.join('%.6g'%v for v in ctx))
