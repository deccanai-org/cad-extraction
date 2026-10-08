"""Apply Smart 3D iso conventions learned from the original PCFs (WORK/skey_learned.json) and regenerate all PCFs.

Rule per part class (>= 20 matched parts, >= 80 % agreement in the originals):
  SKEY  'XX**' (wildcard ends) -> 'XX' + our end suffix ; concrete SKEY -> as in the originals
  type  -> the originals' PCF record type
JSON keeps the catalogue-derived values as skey_catalog / pcf_type_catalog.
"""
import os, sys, json, glob, collections
import multiprocessing as mp
from common import *
import pcfgen

MIN_N, MIN_SHARE = 20, 0.8
KNOWN = {'PIPE', 'ELBOW', 'BEND', 'TEE', 'OLET', 'REDUCER-CONCENTRIC', 'REDUCER-ECCENTRIC', 'FLANGE', 'FLANGE-BLIND', 'VALVE', 'VALVE-ANGLE',
         'VALVE-3WAY', 'INSTRUMENT', 'INSTRUMENT-ANGLE', 'INSTRUMENT-3WAY', 'CAP', 'COUPLING', 'UNION', 'FILTER', 'MISC-COMPONENT',
         'REINFORCEMENT-PAD', 'LAPJOINT-STUBEND', 'TRAP-OFFSET', 'TRAP-RETURN'}
L = None


def rules():
    lr = json.load(open(os.path.join(WORK, 'skey_learned.json')))
    out = {}
    for pc, v in lr.items():
        if pc in ('?', 'None') or v['n'] < MIN_N:
            continue
        r = {}
        if v.get('orig_skey') and v['orig_skey_share'] >= MIN_SHARE:
            r['skey'] = v['orig_skey']
        if v.get('orig_type') and v['orig_type_share'] >= MIN_SHARE and v['orig_type'] in KNOWN:
            r['type'] = v['orig_type']
        if r:
            r['n'] = v['n']
            out[pc] = r
    return out


def one(path):
    try:
        J = read_json(path)
        ch = collections.Counter()
        for C in J['components']:
            r = L.get(C.get('part_class') or '')
            if not r or C['pcf_type'] == 'PIPE':
                continue
            if 'skey' in r:
                sk = r['skey']
                old = C.get('skey_catalog', C.get('skey'))
                new = (sk[:2] + (old[2:4] if old and len(old) >= 4 and not old.endswith('**') else 'BW')) if sk.endswith('**') else sk
                if new != C.get('skey'):
                    C.setdefault('skey_catalog', C.get('skey'))
                    C['skey'] = new
                    C['skey_source'] = 'Smart 3D iso convention (learned from %d matched original PCF parts)' % r['n']
                    ch['skey'] += 1
            if 'type' in r and r['type'] != C['pcf_type']:
                C.setdefault('pcf_type_catalog', C['pcf_type'])
                C['pcf_type'] = r['type']
                ch['type'] += 1
        txt, st = pcfgen.to_pcf(J)
        J['checks']['pcf'] = st
        write_json(path, J)
        pp = os.path.join(OUT, J['files']['pcf'])
        with open(pp + '.tmp', 'w') as f:
            f.write(txt)
        os.replace(pp + '.tmp', pp)
        return dict(ch), None
    except Exception as e:
        return {}, '%s: %s: %s' % (path, type(e).__name__, str(e)[:150])


def main():
    global L
    L = rules()
    json.dump(L, open(os.path.join(WORK, 'pcf_conventions_applied.json'), 'w'), indent=1)
    files = sorted(glob.glob(os.path.join(OUT, 'json', 'pipelines', '*.json.gz')))
    log('rules for %d part classes; %d pipelines' % (len(L), len(files)))
    tot = collections.Counter(); errs = []
    with mp.get_context('fork').Pool(8) as pool:
        for i, (ch, err) in enumerate(pool.imap_unordered(one, files, chunksize=50)):
            tot.update(ch)
            if err:
                errs.append(err)
            if i % 5000 == 0:
                log('%d %s' % (i, dict(tot)))
    log('regen done %s errors %d %s' % (dict(tot), len(errs), errs[:3]))


if __name__ == '__main__':
    main()
