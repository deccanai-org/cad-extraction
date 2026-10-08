import pickle, json, os, glob
from common import *
import docblob, pcfparse
PD = os.path.join(WORK, 'pairs')
sheets = pickle.load(open(PD + '/sheets.pkl', 'rb')); D = pickle.load(open(PD + '/docs.pkl', 'rb'))
pcf_by_mgr = {}
for d in D['docs']:
    if (d['FileType'] or '').lower() == 'pcf':
        pcf_by_mgr.setdefault(d['mgr'].upper(), []).append(d)
pl_out = {}
for f in glob.glob(WORK + '/done/piping/pb00[0-2]*.json'):
    for r in json.load(open(f))['results']:
        if 'error' not in r: pl_out[r['pl'].upper()] = r
c = connect(MDB); shown = 0
for s in sheets:
    t = (s.get('target') or '').upper()
    if t in pl_out and s.get('mgr') and s['mgr'].upper() in pcf_by_mgr and pl_out[t]['n'] > 20:
        d = pcf_by_mgr[s['mgr'].upper()][0]
        cols, rows = query(c, "SELECT DataBlob, FileCompressed FROM dbo.DRAWNGDocumentData WHERE oid='%s'" % d['doc'])
        txt, how = docblob.decode(rows[0][0], rows[0][1])
        O = pcfparse.parse(txt.decode('latin1'))
        U = pcfparse.parse(open(os.path.join(OUT, pl_out[t]['pcf_file'])).read())
        import collections
        print('==', pl_out[t]['name'], '| orig ref', O['ref'], O['units'], '| sheet', s['FileName'], s['TimeLastUpdated'])
        print(' orig types', dict(collections.Counter(x['type'] for x in O['comps'])))
        print(' ours types', dict(collections.Counter(x['type'] for x in U['comps'])))
        for x in [x for x in O['comps'] if x['type'] == 'PIPE'][:2]: print(' O PIPE', x['ep'], x['uci'], x['item'])
        for x in [x for x in U['comps'] if x['type'] == 'PIPE'][:2]: print(' U PIPE', x['ep'], x['uci'], x['item'])
        shown += 1
        if shown >= 3: break
