import json, glob, gzip, collections, math, os
from common import *
D = os.path.join(WORK, 'done', 'piping')
fails = collections.Counter(); ex = collections.defaultdict(list)
for f in sorted(glob.glob(D + '/pb*.json')):
    for r in json.load(open(f))['results']:
        if 'error' in r: continue
        c = r['checks']
        if c['point_count_fail'] or c['open_ports'] or c['pipe_length_mismatch'] or r['pcf'].get('tee_missing_branch'):
            J = read_json(os.path.join(OUT, r['json']))
            comp = {x['oid']: x for x in J['components']}
            for s in J['checks']['point_count_fail_samples']:
                C = comp[s['oid']]
                fails['pc:' + C['pcf_type']] += 1
                ex['pc:' + C['pcf_type']].append((J['name'], C['name'], C['part_class'], [(q['index'], q['xyz'] is not None, q['conn'] is not None) for q in C['ports']], C['matrix'], C['cp']))
            for C in J['components']:
                for q in C['ports']:
                    if not q['xyz']:
                        fails['open:' + C['pcf_type']] += 1
                        ex['open:' + C['pcf_type']].append((J['name'], C['name'], C['part_class'], [(p['index'], p['xyz'], p['conn'] is not None) for p in C['ports']], C['matrix'], C['cp'], sorted((C.get('catalog_attrs') or {}).items())[:12]))
                if C['pcf_type'] == 'PIPE' and C.get('length') and C['ep1'] and C['ep2'] and abs(math.dist(C['ep1'], C['ep2']) - C['length']) > 0.001:
                    fails['len'] += 1
                    ex['len'].append((J['name'], C['length'], math.dist(C['ep1'], C['ep2']), C.get('cut_length'), C['feature_class'], C.get('bend')))
                if C['pcf_type'] == 'TEE' and not C['ep3']:
                    fails['teebr'] += 1
                    ex['teebr'].append((J['name'], C['name'], C['part_class'], [(p['index'], p['xyz'], p['conn'] is not None) for p in C['ports']], C['matrix'], C['cp'], C['ep1'], C['ep2']))
print(fails)
for k, v in ex.items():
    print('==', k)
    for e in v[:3]:
        print('  ', json.dumps(e)[:700])
# a good tee for axis convention
for f in sorted(glob.glob(D + '/pb*.json'))[:1]:
    for r in json.load(open(f))['results'][:60]:
        J = read_json(os.path.join(OUT, r['json']))
        for C in J['components']:
            if C['pcf_type'] in ('TEE', 'ELBOW', 'FLANGE', 'VALVE', 'OLET', 'REDUCER-ECCENTRIC') and C['matrix'] and C['ep1'] and C['ep2']:
                print('AX', C['pcf_type'], C['part_class'], 'ep1', C['ep1'], 'ep2', C['ep2'], 'ep3', C['ep3'], 'cp', C['cp'], 'M', C['matrix'])
