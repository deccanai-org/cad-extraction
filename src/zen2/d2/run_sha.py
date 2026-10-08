#!/usr/bin/env python3
"""run_sha.py [NPROC] - every distinct .sha -> JSON (sha2json.convert); written once per source relpath to
/work/2d/out/json/sha/<relpath>.json (duplicates get their own relpath + the list of same-content relpaths)."""
import collections, json, os, sys, time, traceback
import multiprocessing as mp

sys.path.insert(0, '/work/2d')
SRC = '/work/in/src/'
OUT = '/work/2d/out/json/sha/'
RES = '/work/2d/state/sha_results.jsonl'


def load():
    g = collections.OrderedDict()
    for l in open('/work/out/json/source_sha256.tsv'):
        h, p = l.rstrip('\n').split('\t', 1)
        if p.lower().endswith('.sha') and not p.startswith('PLC 17072025/'):
            g.setdefault(h, []).append(p)
    return g


def work(a):
    import sha2json
    h, rels = a
    t = time.time()
    try:
        rec = sha2json.convert(SRC + rels[0], rels[0], h)
        rec['same_content_relpaths'] = rels
        for rel in rels:
            r2 = dict(rec)
            r2['source_relpath'] = rel
            fn = OUT + rel + '.json'
            os.makedirs(os.path.dirname(fn), exist_ok=True)
            with open(fn, 'w') as f:
                json.dump(r2, f, indent=1, default=str, ensure_ascii=False)
        return {'sha256': h, 'relpaths': rels, 'status': 'ok', 'fields': rec['fields'],
                'n_streams': len(rec['streams']), 'bytes': rec['size'], 'seconds': round(time.time() - t, 2)}
    except Exception as e:
        return {'sha256': h, 'relpaths': rels, 'status': 'failed', 'reason': '%s: %s' % (type(e).__name__, str(e)[:200]),
                'traceback': traceback.format_exc()[-600:]}


def main():
    import status
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    g = load()
    res = []
    with mp.get_context('fork').Pool(n) as pool:
        for r in pool.imap_unordered(work, list(g.items()), chunksize=4):
            res.append(r)
    with open(RES, 'w') as f:
        for r in res:
            f.write(json.dumps(r, default=str, ensure_ascii=False) + '\n')
    fails = [{'relpath': r['relpaths'][0], 'reason': r['reason']} for r in res if r['status'] != 'ok']
    ok = [r for r in res if r['status'] == 'ok']
    dn = collections.Counter(r['fields'].get('drawing_number') for r in ok)
    status.put_part('sha_json', {
        'stage': 'done', 'distinct_sha_files': len(g), 'relpaths': sum(len(v) for v in g.values()),
        'json_ok_distinct': len(ok), 'json_files_written': sum(len(r['relpaths']) for r in ok),
        'distinct_drawing_numbers': len(dn), 'missing_drawing_number': dn.get('', 0) + dn.get(None, 0),
        'with_revision_records': sum(1 for r in ok if r['fields'].get('revision_records')),
        'failures': fails})
    print('sha done', len(ok), 'ok', len(fails), 'failed', 'drawing numbers', len(dn))


if __name__ == '__main__':
    main()
