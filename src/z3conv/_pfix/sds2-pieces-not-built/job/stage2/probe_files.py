import sys, os
W = '/work/agentwork/sds2-pieces-not-built/jobs/'
for spec in sys.argv[1:]:
    jn, sid = spec.split(':')
    fp = os.path.join(W + jn, 'subm', sid)
    b = open(fp, 'rb').read()
    print('=====', jn, sid, len(b))
    for i in range(0, len(b), 32):
        print('  %04x %s' % (i, b[i:i + 32].hex()))
