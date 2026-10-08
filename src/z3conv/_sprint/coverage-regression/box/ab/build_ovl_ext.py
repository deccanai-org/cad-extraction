#!/usr/bin/env python3
"""BOX (coverage-regression): per-model profile overlay entries for REUSED DB1 models that the overlay (built for the 52
data-3 'convert' models) never covered, from each model's OWN folder profdb.bin (same decoder + same acceptance rules as
the profile improver: db1_v2/prof/profdb.model_catalog -> angles family 2 with r1/r2, round bars family 6 'R.B Ø<d>').
Only names the model's own parts use are kept. Nothing is guessed: a name the profdb does not define stays unresolved.

usage: build_ovl_ext.py MODELS_JSON BASE_OVERLAY OUT_EXT OUT_MERGED
  MODELS_JSON: [{"sha256", "zip_key", "member"}]   member = path of the .db1 inside the zip
"""
import os, sys, json, gzip, io, zipfile, hashlib, collections
import boto3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profdb
B = 'bim-proprietary-data'
DET = 'cad-disk-extract/zenitude-data-3/_state/conv/db1/detail'
s3 = boto3.client('s3', region_name='ap-south-1')
models, basep, outp, mergedp = sys.argv[1:5]
models = json.load(open(models)); base = json.load(open(basep))
ext = {'per_model': {}, 'evidence': {}}
for m in models:
    sha = m['sha256']; ev = {'zip_key': m['zip_key'], 'member': m['member']}
    raw = s3.get_object(Bucket=B, Key=m['zip_key'])['Body'].read()
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()
    db1 = z.read(m['member']); got = hashlib.sha256(db1).hexdigest()
    ev['db1_sha256_in_zip'] = got; ev['db1_matches'] = got == sha
    folder = m['member'].rsplit('/', 1)[0] + '/'
    pk = next((n for n in names if n.lower() == (folder + 'profdb.bin').lower()), None)
    ev['profdb'] = pk
    if not ev['db1_matches'] or not pk:
        ext['evidence'][sha] = ev; continue
    pb = z.read(pk); ev['profdb_bytes'] = len(pb); ev['profdb_sha256'] = hashlib.sha256(pb).hexdigest()
    d = profdb.load_bytes(pb) if hasattr(profdb, 'load_bytes') else (gzip.decompress(pb) if pb[:2] == b'\x1f\x8b' else pb)
    # names the model's own parts use (code-i decoder parts list: [seq, profile, category, status, how, guid, n_cuts])
    try:
        pl = json.load(gzip.open(io.BytesIO(s3.get_object(Bucket=B, Key=f'{DET}/{sha}.decoded_parts.json.gz')['Body'].read()), 'rt'))
    except Exception as e:
        pl = []; ev['parts_list_error'] = str(e)[:200]
    used = collections.Counter(p[1] for p in pl if p[1])
    miss = collections.Counter(p[1] for p in pl if p[3] != 'written' and p[2] != 'feature')
    cat = profdb.model_catalog(d, wanted=set(used))
    ent = {}
    for nm, v in cat.items():
        g = (base.get('global') or {}).get(nm)
        e = {'kind': v['kind'], 'dims': v['dims'], 'n': used[nm], 'tier': 'P', 'src': 'model folder profdb.bin: ' + v['src']}
        if g is not None and (g.get('kind') != v['kind'] or [round(x, 6) if isinstance(x, float) else x for x in (g.get('dims') or [])] !=
                              [round(x, 6) if isinstance(x, float) else x for x in v['dims']]):
            e['differs_from_global'] = {'kind': g.get('kind'), 'dims': g.get('dims')}
        ent[nm] = e
    ext['per_model'][sha] = ent
    ev['names_used'] = len(used); ev['entries'] = len(ent)
    ev['entries_by_kind'] = dict(collections.Counter(v['kind'] for v in ent.values()))
    ev['resolves_missing'] = {nm: miss[nm] for nm in ent if miss.get(nm)}
    ev['still_missing'] = {nm: n for nm, n in miss.most_common() if nm not in ent}
    ev['angles_also_in_global'] = sum(1 for nm in ent if nm in (base.get('global') or {}))
    ev['angles_differing_from_global'] = sorted(nm for nm, e in ent.items() if 'differs_from_global' in e)
    ext['evidence'][sha] = ev
    print(sha[:12], 'db1 ok' if ev['db1_matches'] else 'DB1 MISMATCH', 'entries', len(ent), 'resolves', ev['resolves_missing'], 'still', dict(list(ev['still_missing'].items())[:5]), flush=True)
json.dump(ext, open(outp, 'w'), indent=1)
merged = json.loads(json.dumps(base))
for sha, ent in ext['per_model'].items():
    if ent:
        merged.setdefault('per_model', {}).setdefault(sha, {}).update(ent)
merged.setdefault('meta', {})['coverage_regression_ext'] = {'models': sorted(s for s, e in ext['per_model'].items() if e),
                                                            'note': 'reused DB1 models (disk-1/2 reuse, re-converted into data-3 since code h/i) '
                                                                    'that the 52-model overlay never covered; entries from each model folder profdb.bin'}
json.dump(merged, open(mergedp, 'w'))
print('DONE', sum(1 for e in ext['per_model'].values() if e), 'models with entries')
