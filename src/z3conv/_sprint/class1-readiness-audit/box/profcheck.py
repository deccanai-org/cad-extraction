"""profcheck.py TAG : for every model folder with its own profdb.bin, which approximate / unresolved profiles of the decode (parts list of
the TAG run) the model's OWN profdb defines with validated parameters (prof/profdb.model_catalog: angles with r1/r2, round bars) ->
profcheck.json {sha: {approx_parts, fixable_parts, names_fixable, names_not_in_profdb}} + a per-model overlay candidate (own records only)."""
import json, os, sys, glob, gzip, collections
sys.path.insert(0, 'job')
import profdb
TAG = sys.argv[1]
APPROX = {'parametric_angle', 'parametric_angle_equal', 'parametric_rhs', 'parametric_hss', 'catalog_upn_alias', 'parametric_panel', 'parametric_grating',
          'parametric_stud_shank'}
ids = {j['sha256'][:12]: j['sha256'] for j in json.load(open('job/ids.json'))}
R = {}; OV = {}
for sd in sorted(glob.glob('src/*_sib')):
    s12 = os.path.basename(sd)[:12]; pf = os.path.join(sd, 'profdb.bin'); pl = f'wk/{TAG}/{s12}/convert.json.parts.json.gz'
    if not (os.path.exists(pf) and os.path.exists(pl)): continue
    parts = json.load(gzip.open(pl, 'rt'))
    need = collections.Counter(); how = {}
    for seq, prof, cat, st, hw, guid, nc in parts:
        if (st == 'written' and hw in APPROX) or (st == 'skipped' and hw in ('unresolved', 'implausible_profile', 'profile_without_size', 'writer_skip')):
            need[prof] += 1; how[prof] = hw
    if not need: continue
    try:
        mc = profdb.model_catalog(profdb.load(pf), set(need))
    except Exception as e:
        R[ids.get(s12, s12)] = {'error': str(e)[:200]}; continue
    fix = {n: c for n, c in need.items() if n in mc}
    R[ids.get(s12, s12)] = {'approx_or_unresolved_parts': sum(need.values()), 'fixable_parts': sum(fix.values()),
                            'names_fixable': {n: [c, how[n], mc[n]['src'][:80]] for n, c in fix.items()},
                            'names_not_in_profdb': {n: [c, how[n]] for n, c in need.most_common(25) if n not in mc}}
    if mc: OV[ids.get(s12, s12)] = {n: {'kind': e['kind'], 'dims': e['dims'], 'n': need[n], 'tier': 'own_profdb', 'src': e['src']} for n, e in mc.items()}
json.dump(R, open('profcheck.json', 'w'), indent=1); json.dump(OV, open('overlay_own_profdb.json', 'w'), indent=1)
import boto3
c = boto3.client('s3', region_name='ap-south-1')
for f in ('profcheck.json', 'overlay_own_profdb.json'):
    c.upload_file(f, 'bim-proprietary-data', f'cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/{f}')
print(len(R), 'models checked;', sum(v.get('fixable_parts', 0) for v in R.values()), 'parts fixable from own profdb in',
      sum(1 for v in R.values() if v.get('fixable_parts')), 'models')
