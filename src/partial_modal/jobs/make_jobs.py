#!/usr/bin/env python3
"""make_jobs.py - the partial-tier job list for the Modal pipeline (pmp): ONE ROW PER PARTIAL MODEL.

READ-ONLY against S3 (AWS_PROFILE=bim): HEAD / GET / LIST only (s3cache.py cannot write).  Writes only under jobs/.
No geometry / pipeline compute: it reads package manifests, listings and small conversion-result JSONs.

Usage (from anywhere; uses ../.venv or any python with boto3):
  python jobs/make_jobs.py                 # all 2,418 partial packages -> jobs_partial.jsonl.gz, jobs_stats.json,
                                           #   jobs_problems.jsonl, new5.jsonl
  python jobs/make_jobs.py --new5-only     # only the packages of ../new5.json (fast) -> new5.jsonl (+ a small jobs file)
  python jobs/make_jobs.py --refresh       # re-read every cached listing / result JSON from S3 (manifests are always
                                           #   HEAD-checked; their rows + model/ listing re-read when ETag/size changed)

What one row holds (full schema: jobs/README.md):
  identity     model_id (unique over the tier; = job id, Modal volume folder, bundle name), pid, relpath, model_folder
               (scripts/<model_folder>/: sanitised STEP basename, unique case-insensitively within the package over ALL its
               partial models; '-<id[:8]>' on every member of a clash; same rule as the perfect-tier stage_full.py)
  size         bytes (delivered STEP), class S<10MB M<100MB L<500MB XL<1GB (decimal MB, delivered STEP bytes, the fleet
               job.py rule) or too_big_v1 (>= 1 GB: out of scope for v1, recorded, never silently dropped);
               source_class = the same rule on the source file bytes (information for the app's resource choice)
  inputs       step{key (the package copy = what we colour / verify against), bytes, sha256, etag},
               source{kind, format, relpath, package 3d_partial|3d (add-on), key, bytes, etag, sha256, exists},
               conv{step_key (the conversion output the package copied), files next to it}, state{results, detail}
               detail_keys{alias: key} = ONLY the conversion-detail files proven to belong to the shipped conversion run
  pins         converter (manifest), pin{...} per source: IFC writer code+suffix, DB1 kit hint + evidence,
               SDS/2 converter label/zip/sha256 (+ run family) + evidence
  record       partial{kind, issues, missing, standins}, grader, verify_verdict, verify_codes, older_revision_of ...
  problems     list of stable codes (see PROBLEM CODES below); every one is also in jobs_problems.jsonl
"""
import argparse, collections, gzip, hashlib, io, json, os, re, sys, time, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import s3cache  # noqa: E402

JOBS_V = 'pmp-jobs-2026-10-07a'
DETAIL_V = 4                       # bump when resolve_detail changes what it records (invalidates cache/detail)
PKG3P = 'cad-disk-extract/dataset/packages/3d_partial/'
PKG3 = 'cad-disk-extract/dataset/packages/3d/'
CACHE = s3cache.CACHE
P1 = '/Users/dhiren/Downloads/Deccan/report_v1/data/projects_p1.json'
NEW5 = os.path.join(ROOT, 'new5.json')

CLASSES = (('S', 10_000_000), ('M', 100_000_000), ('L', 500_000_000), ('XL', 1_000_000_000))
TOO_BIG = 'too_big_v1'

# folder naming = perfect tier (stage_full.py: NAME_MAX, RESERVED, sanitize, package_names) + the partial tier's own
# shared files in scripts/ (issues_lib.py, scripts_manifest.jsonl)
NAME_MAX = 80
RESERVED = {'readme.md', 'requirements.txt', 'steelbuild.py', 'issues_lib.py', 'scripts_manifest.jsonl', '__pycache__',
            'con', 'prn', 'aux', 'nul'} | {f'com{i}' for i in range(1, 10)} | {f'lpt{i}' for i in range(1, 10)}

# conversion-state folders per disk (results/<id>.json + detail/<id>.*), in lookup order
STATE = {'zenitude-data-3': ['_state/conv'], 'zentitude-data-4': ['_state/conv2', '_state/conv']}
# the SDS/2 r2 run (v4) has no job.json / results JSON: its deployment zip (NOTES_sds2_head.md, perfect-tier pinning,
# models_pinned.json of the f63cb79e session: 11 perfect models re-converted byte-identically with it)
R2_PREFIX = 'cad-disk-extract/sds2-step-r2-20260929-01/'
R2_PIN = {'label': 'v4', 'zip': 'sds2-step-pipeline-v4-candidate.zip',
          'sha256': 'c5b65d271d3a6c69853d745d705cbb92b431e8891686068e7a555e720b3c15f0'}
DB1_KITS = {'z3-db1-2026-10-01v': 'kit_v', 'z3-db1-2026-10-01u': 'kit_u', 'z3-db1-2026-10-01q': 'kit_q'}
LOST_KITS = {'kit_q'}

PROBLEM_CODES = {
    'too_big_v1': 'delivered STEP >= 1 GB: out of scope for v1 (recorded, not run)',
    'step_not_in_package': 'the delivered STEP (package model/step/...) is not listed in the package',
    'step_size_mismatch': 'the package STEP size differs from the manifest bytes',
    'source_missing': 'the source file (converted_from, in this package or the 3d add-on package) is not listed',
    'source_size_mismatch': 'the source file size differs from the manifest row of the source',
    'source_sha256_not_model_id': 'IFC/DB1 source sha256 (package manifest) is not the model id the conversion keyed it by',
    'source_ifcxml': 'source is ifcXML (the pipeline reads IFC-SPF; needs a conversion step or is out of scope)',
    'conv_step_missing': 'the conversion output key the package copied (step_key) no longer exists',
    'conv_step_differs': 'the conversion output at step_key differs in size/etag from the delivered STEP',
    'results_missing': 'no conversion result JSON (_state/.../results/<id>.json) for this model',
    'results_not_shipped_run': 'the result JSON describes another conversion run than the shipped STEP (detail not usable)',
    'conv_detail_missing': 'no parts/check (IFC/DB1) or pieces/skipped (SDS/2) side files next to the conversion output',
    'pin_unresolved': 'the converter version that produced the shipped STEP could not be pinned to a kit/zip',
    'pin_lost_kit': 'the producing DB1 kit is a lost kit (q): cannot regenerate',
}
# excluded = not run in v1; blocking = the job cannot run as specified; degraded = runs, but an input/proof is weaker;
# info = recorded for the issue makers (e.g. the state result JSON is a later re-run: use the conversion-folder files)
SEVERITY = {'too_big_v1': 'excluded', 'step_not_in_package': 'blocking', 'step_size_mismatch': 'blocking',
            'source_missing': 'blocking', 'source_size_mismatch': 'blocking', 'pin_lost_kit': 'blocking',
            'source_sha256_not_model_id': 'degraded', 'source_ifcxml': 'degraded', 'conv_step_missing': 'degraded',
            'conv_step_differs': 'degraded', 'results_missing': 'degraded', 'conv_detail_missing': 'degraded',
            'pin_unresolved': 'degraded', 'results_not_shipped_run': 'info'}
RUN_SUFFIX = re.compile(r'^\.(v6\d*|u|v|q)\.')          # state detail '<id>.<writer/kit suffix>.<what>' (IFC v6110, DB1 u)


# ===================================================================================================== helpers
def sha1(s):
    return hashlib.sha1(s.encode()).hexdigest()


def size_class(b):
    if b is None:
        return None
    for name, lim in CLASSES:
        if b < lim:
            return name
    return TOO_BIG


def sanitize(base):
    """a readable, shell- and file-system-safe folder name from a STEP basename (= stage_full.sanitize)"""
    s = unicodedata.normalize('NFKD', base).encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', s)
    s = re.sub(r'_+', '_', s).strip('._-')
    s = s[:NAME_MAX].rstrip('._-')
    return s or 'model'


def step_stem(relpath):
    b = os.path.basename(relpath)
    return b[:-5] if b.lower().endswith('.step') else (os.path.splitext(b)[0] or b)


def package_names(models):
    """{model_id: folder} for ALL partial models of a package [(model_id, step relpath)] (= stage_full.package_names)"""
    base = {mid: sanitize(step_stem(rp)) for mid, rp in models}
    groups = collections.defaultdict(list)
    for mid, b in base.items():
        groups[b.lower()].append(mid)
    out = {}
    for k, mids in groups.items():
        for mid in mids:
            out[mid] = base[mid] if (len(mids) == 1 and k not in RESERVED) else f'{base[mid]}-{mid[:8]}'
    seen = collections.Counter(v.lower() for v in out.values())
    for mid in sorted(out):
        if seen[out[mid].lower()] > 1:
            out[mid] = f'{base[mid]}-{mid[:16]}'
    assert len({v.lower() for v in out.values()}) == len(out), 'model folder names not unique'
    assert not ({v.lower() for v in out.values()} & RESERVED)
    return out


def src_format(kind, relpath):
    b = os.path.basename(relpath or '').lower()
    if kind == 'ifc':
        for ext, f in (('.ifczip', 'ifczip'), ('.ifcxml', 'ifcxml'), ('.ifc', 'ifc')):
            if b.endswith(ext):
                return f
        return 'ifc_no_ext'
    if kind == 'db1':
        return 'db1' if b.endswith('.db1') else 'db1_other'
    if kind == 'sds2':
        return 'sds2_zip' if b.endswith('.zip') else 'sds2_other'
    return 'unknown'


def jdump_gz(path, rows):
    """deterministic gzip (mtime 0) of JSON lines"""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode='wb', mtime=0, compresslevel=9) as g:
        for r in rows:
            g.write((json.dumps(r, ensure_ascii=False) + '\n').encode('utf-8'))
    tmp = path + '.tmp'
    open(tmp, 'wb').write(buf.getvalue())
    os.replace(tmp, path)


def load_json_cache(p):
    try:
        with gzip.open(p, 'rt') if p.endswith('.gz') else open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_json_cache(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with gzip.open(tmp, 'wt') if p.endswith('.gz') else open(tmp, 'w') as f:
        json.dump(obj, f)
    os.replace(tmp, p)


# ===================================================================================================== packages
def list_packages(args):
    p = os.path.join(CACHE, 'pkg_list.json')
    if os.path.exists(p) and not args.refresh:
        return json.load(open(p))
    _, dirs = s3cache.ls(PKG3P, '/')
    pids = sorted(d[len(PKG3P):-1] for d in dirs)
    json.dump(pids, open(p, 'w'))
    return pids


def load_package(pid, args):
    """the package's model/ manifest rows + model/ listing (cached, tied to the manifest ETag) + its top-level folders
    (always fresh: is there a scripts/ already?).  Manifest freshness is proven by a HEAD every run (etag + size)."""
    mkey = PKG3P + pid + '/manifest.jsonl'
    cp = os.path.join(CACHE, 'model_rows', sha1(pid) + '.json.gz')
    c = load_json_cache(cp)
    h = s3cache.head(mkey)
    if h is None:
        return {'pid': pid, 'error': 'manifest_missing'}
    if not (c and c['etag'] == h['etag'] and c['bytes'] == h['bytes'] and 'ls_model' in c) or args.refresh:
        body, how = None, None
        raw = s3cache.cached_path(mkey, 'man_partial')          # the previous attempt's raw manifest cache
        if os.path.exists(raw) and os.path.getsize(raw) == h['bytes']:
            b = open(raw, 'rb').read()
            if '-' not in h['etag'] and hashlib.md5(b).hexdigest() == h['etag']:
                body, how = b, 'raw_cache_md5_equals_etag'
            elif '-' in h['etag']:
                body, how = b, 'raw_cache_size_equals_head (multipart etag)'
        if body is None:
            body, how = s3cache.get_bytes(mkey), 'get'
            if body is None or len(body) != h['bytes']:
                return {'pid': pid, 'error': 'manifest_changed_while_reading'}
        rows = []
        for ln in body.splitlines():
            if b'model/' not in ln:
                continue
            r = json.loads(ln)
            if r.get('relpath', '').startswith('model/'):
                rows.append(r)
        objs, _ = s3cache.ls(PKG3P + pid + '/model/')
        c = {'pid': pid, 'etag': h['etag'], 'bytes': h['bytes'], 'mtime': h['mtime'], 'verified_by': how, 'rows': rows,
             'ls_model': {o['key']: {'size': o['bytes'], 'etag': o['etag'], 'mtime': o['mtime']} for o in objs},
             'listed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        save_json_cache(cp, c)
    _, top = s3cache.ls(PKG3P + pid + '/', '/')
    c['topnames'] = sorted(d.rstrip('/').rsplit('/', 1)[1] for d in top)
    return c


# ===================================================================================================== conversion detail
def _rel_role(stem, key):
    return key.rsplit('/', 1)[1][len(stem):]


def _summ_results(d, body, step_key):
    s = {k: d.get(k) for k in ('id', 'code', 'status', 'started', 'finished', 'sha256', 'size', 'engine', 'version',
                               'detail_prefix', 'render_key', 'input_key', 'writer', 'arc_writer', 'kind', 'schema_in')
         if d.get(k) is not None}
    s['out_key'] = d.get('out_key') or (d.get('step') or {}).get('key')
    s['out_bytes'] = d.get('out_bytes') or (d.get('step') or {}).get('bytes')
    if d.get('converter') is not None:
        s['converter'] = d.get('converter')
    if d.get('catalog_overlay') is not None:
        s['catalog_overlay'] = d.get('catalog_overlay')
    if isinstance(d.get('alternatives'), dict):
        s['alternatives'] = {k: {'status': (v or {}).get('status'), 'step_key': (v or {}).get('step_key')}
                             for k, v in d['alternatives'].items()}
    if isinstance(d.get('decoded'), dict):
        s['decoded_skipped'] = d['decoded'].get('skipped')
    s['mentions_step_key'] = step_key in body
    return s


def resolve_detail(r, args):
    """files the issue makers / source stages need, each proven to belong to the shipped conversion run (or flagged)"""
    mid, sk, src = r['model_id'], r['step_key'], r['step_source']
    cp = os.path.join(CACHE, 'detail', mid[:2], mid + '.json')
    c = load_json_cache(cp)
    if c and c.get('v') == DETAIL_V and c.get('step_key') == sk and c.get('etag_source') == r.get('etag_source') \
            and not args.refresh:
        return c
    folder, base = sk.rsplit('/', 1)
    folder += '/'
    out = {'v': DETAIL_V, 'step_key': sk, 'etag_source': r.get('etag_source'),
           'resolved_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'conv_files': [], 'conv_step': None,
           'state_dir': None, 'results': None, 'state_files': [], 'job_json': None}
    # ---- files next to the conversion output (written by the same run as the STEP itself)
    if src in ('ifc', 'db1'):
        stem = base.rsplit('.', 1)[0]                      # <mid>.v6110 | <mid>.u | <md5>_<size> | <mid>
        objs, _ = s3cache.ls(folder + stem + '.')
        keep = [o for o in objs if o['key'] == sk or o['key'].startswith(sk + '.') or o['key'] == folder + stem + '.png']
    else:
        stem = base.rsplit('.', 1)[0]                      # <JOB>_<id6>_stage2 | ..._stage1
        objs, _ = s3cache.ls(folder, '/')
        keep = [o for o in objs if o['key'].rsplit('/', 1)[1].startswith(stem) or o['key'] == folder + 'job.json']
    for o in keep:
        if o['key'] == sk:
            out['conv_step'] = o
        else:
            o = dict(o, role='conv:' + (_rel_role(stem, o['key']) if o['key'].rsplit('/', 1)[1].startswith(stem)
                                        else o['key'].rsplit('/', 1)[1]))
            out['conv_files'].append(o)
    out['conv_files'].sort(key=lambda o: o['key'])
    # ---- SDS/2 job.json (converter label / zip / sha256 of the run that wrote this folder)
    if src == 'sds2' and any(o['key'] == folder + 'job.json' for o in out['conv_files']):
        b = s3cache.get_bytes(folder + 'job.json')
        try:
            d = json.loads(b)
            out['job_json'] = {k: d.get(k) for k in ('id', 'name', 'version', 'code', 'converter', 'converted', 'qa',
                                                     'accepted', 'published') if d.get(k) is not None}
        except (TypeError, ValueError):
            out['job_json'] = {'error': 'unreadable'}
    # ---- conversion state (results JSON + detail files), searched per disk (the pid's disk when the key has none)
    kdisk = sk.split('/')[1]
    pdisk = 'zenitude-data-3' if r['project_id'].startswith('Zenitude-data-3__') else 'zentitude-data-4'
    disk = kdisk if kdisk in STATE else pdisk
    ids = [mid]
    if src == 'sds2':                                      # an SDS/2 STEP can sit in another job id's folder
        m = re.search(r'/sds2-step/([0-9a-f]{24})/', sk)
        if m and m.group(1) != mid:
            ids.append(m.group(1))
    found = False
    for st in STATE[disk]:
        for i in ids:
            base_state = f'cad-disk-extract/{disk}/{st}/{src}/'
            ro, _ = s3cache.ls(base_state + 'results/' + i + '.')
            do, _ = s3cache.ls(base_state + 'detail/' + i + '.')
            if ro or do:
                out['state_dir'] = base_state
                rk = base_state + 'results/' + i + '.json'
                for o in ro:
                    if o['key'] == rk:
                        b = s3cache.get_bytes(rk)
                        body = b.decode('utf-8', 'replace') if b is not None else ''
                        try:
                            summ = _summ_results(json.loads(body), body, sk)
                        except ValueError:
                            summ = {'error': 'unreadable'}
                        out['results'] = dict(o, summary=summ)
                    else:
                        out['state_files'].append(dict(o, role='state_results:' + o['key'].rsplit('/', 1)[1][len(i):]))
                out['state_files'] += [dict(o, role='state:' + o['key'].rsplit('/', 1)[1][len(i):]) for o in do]
                found = True
                break
        if found:
            break
    out['state_files'].sort(key=lambda o: o['key'])
    # ---- add-on source (dataset/packages/3d/...): its S3 full-object SHA-256 (the packager copied with a SHA-256 checksum)
    cfp = r.get('converted_from_package')
    if cfp and r.get('converted_from'):
        out['source_checksum'] = s3cache.head_sha256(cfp.rstrip('/') + '/' + r['converted_from'])
    save_json_cache(cp, out)
    return out


ALIASES = (  # (alias, source kinds, role suffix test) - the names the issue makers use; first match wins
    ('parts_json', ('ifc', 'db1'), lambda role: role.endswith('.parts.json') and role.startswith('conv:')),
    ('check_json', ('ifc', 'db1'), lambda role: role.endswith('.check.json') and role.startswith('conv:')),
    ('stats_json', ('ifc',), lambda role: role.endswith('.stats.json') and role.startswith('conv:')),
    ('render_png', ('ifc', 'db1', 'sds2'), lambda role: role.startswith('conv:') and role.endswith('.png')),
    ('results_json', ('ifc', 'db1', 'sds2'), lambda role: role == 'results'),
    ('src_parts', ('ifc', 'db1'), lambda role: role.endswith('.src_parts.jsonl.gz')),
    ('step_parts', ('ifc', 'db1'), lambda role: role.endswith('.step_parts.jsonl.gz')),
    ('census', ('ifc', 'db1'), lambda role: role.endswith('.census.json')),
    ('attrib', ('ifc',), lambda role: role.endswith('.attrib.json')),
    ('result_detail', ('ifc',), lambda role: role.startswith('state') and role.endswith('.result.json')),
    ('decoded_parts', ('db1',), lambda role: role.endswith('.decoded_parts.json.gz')),
    ('pieces_csv', ('sds2',), lambda role: role.startswith('conv:') and role.endswith('_pieces.csv')),
    ('skipped_csv', ('sds2',), lambda role: role.startswith('conv:') and role.endswith('_skipped.csv')),
    ('manifest_json', ('sds2',), lambda role: role.startswith('conv:') and role.endswith('_manifest.json')),
    ('log', ('sds2',), lambda role: role.startswith('conv:') and role.endswith('.log')),
    ('job_json', ('sds2',), lambda role: role == 'conv:job.json'),
    ('state_pieces_csv', ('sds2',), lambda role: role.startswith('state:') and role.endswith('_pieces.csv')),
    ('state_skipped_csv', ('sds2',), lambda role: role.startswith('state:') and role.endswith('_skipped.csv')),
)


# ===================================================================================================== one row
def build_row(r, pkg, names, n_models, addon_ls, det):
    pid, mid, src = r['project_id'], r['model_id'], r['step_source']
    probs = []
    cls = size_class(r['bytes'])
    if cls == TOO_BIG:
        probs.append('too_big_v1')
    pkg_prefix = PKG3P + pid + '/'
    # ---- delivered STEP (package copy)
    skey = pkg_prefix + r['relpath']
    so = pkg['ls_model'].get(skey)
    if so is None:
        probs.append('step_not_in_package')
    elif so['size'] != r['bytes']:
        probs.append('step_size_mismatch')
    step = {'key': skey, 'bytes': r['bytes'], 'sha256': r.get('sha256'), 'etag': (so or {}).get('etag', r.get('etag')),
            'listed': so is not None}
    # ---- source file
    cfp = r.get('converted_from_package')
    addon = bool(cfp)
    sp = (cfp.rstrip('/') + '/') if addon else pkg_prefix
    srel = r.get('converted_from')
    skey2 = sp + srel if srel else None
    lsm = addon_ls if addon else pkg['ls_model']
    sobj = lsm.get(skey2) if skey2 else None
    srow = None if addon else next((x for x in pkg['rows'] if x['relpath'] == srel), None)
    sfmt = src_format(src, srel)
    source = {'kind': src, 'format': sfmt, 'relpath': srel, 'package': '3d' if addon else '3d_partial', 'pkg_prefix': sp,
              'key': skey2, 'bytes': (sobj or {}).get('size'), 'etag': (sobj or {}).get('etag'),
              'sha256': (srow or {}).get('sha256'), 'exists': sobj is not None,
              'sha256_is_model_id': None}
    if sobj is None:
        probs.append('source_missing')
    if srow is not None and sobj is not None and srow.get('bytes') != sobj['size']:
        probs.append('source_size_mismatch')
    ck = det.get('source_checksum') or {}
    if addon and ck.get('sha256'):
        source['sha256'] = ck['sha256']
        source['sha256_from'] = 's3_full_object_checksum'
    elif srow is not None:
        source['sha256_from'] = 'package_manifest'
    if src in ('ifc', 'db1'):
        if source['sha256'] is not None:
            source['sha256_is_model_id'] = source['sha256'] == mid
            if not source['sha256_is_model_id']:
                probs.append('source_sha256_not_model_id')
    if sfmt == 'ifcxml':
        probs.append('source_ifcxml')
    # ---- conversion output + detail
    conv_step = det.get('conv_step')
    conv = {'step_key': r['step_key'], 'step_etag_manifest': r.get('etag_source'),
            'step_bytes': (conv_step or {}).get('bytes'), 'step_etag': (conv_step or {}).get('etag'),
            'same_as_delivered': None, 'folder': r['step_key'].rsplit('/', 1)[0] + '/', 'files': det.get('conv_files', [])}
    if conv_step is None:
        probs.append('conv_step_missing')
    else:
        conv['same_as_delivered'] = conv_step['bytes'] == r['bytes'] and conv_step['etag'] == r.get('etag_source')
        if not conv['same_as_delivered']:
            probs.append('conv_step_differs')
    res = det.get('results')
    summ = (res or {}).get('summary') or {}
    if res is None:
        probs.append('results_missing')
        res_ok = False
    else:
        if src in ('ifc', 'db1'):
            res_ok = summ.get('out_key') == r['step_key'] and summ.get('out_bytes') == r['bytes']
        else:
            res_ok = bool(summ.get('mentions_step_key')) and (summ.get('out_bytes') in (None, r['bytes']))
        if not res_ok:
            probs.append('results_not_shipped_run')
    # a state detail file belongs to the shipped run when the result JSON does AND (IFC/DB1) its writer/kit suffix is
    # the shipped STEP's (an IFC model can hold v6110 and v6111 detail side by side; only one of them was shipped)
    run_sfx = None
    if src in ('ifc', 'db1'):
        stem = r['step_key'].rsplit('/', 1)[1].rsplit('.', 1)[0]
        run_sfx = stem.split('.', 1)[1] if '.' in stem else None

    def state_ok(o):
        if not res_ok:
            return False
        if src in ('ifc', 'db1'):
            m = RUN_SUFFIX.match(o['role'].split(':', 1)[1])
            if m and m.group(1) != run_sfx:
                return False
        return True
    state = {'dir': det.get('state_dir'), 'results': res and dict(res, matches_shipped=res_ok),
             'files': [dict(o, matches_shipped=state_ok(o)) for o in det.get('state_files', [])]}
    # ---- detail_keys: aliases over the files that belong to the shipped run
    usable = [(o['role'], o['key']) for o in conv['files']]
    if res_ok:
        usable.append(('results', res['key']))
        usable += [(o['role'], o['key']) for o in state['files'] if o['matches_shipped']]
    detail_keys = {}
    for alias, kinds, test in ALIASES:
        if src not in kinds:
            continue
        for role, key in usable:
            if test(role):
                detail_keys[alias] = key
                break
    need = ('parts_json', 'check_json') if src in ('ifc', 'db1') else ('pieces_csv', 'skipped_csv')
    if not all(k in detail_keys for k in need):
        probs.append('conv_detail_missing')
    # ---- converter pin
    conv_m = r.get('converter') or {}
    pin = {'converter': conv_m}
    if src == 'ifc':
        m = re.search(r'\.(v6\d*)\.step$', r['step_key'])
        pin.update(writer_suffix=m.group(1) if m else None, code=conv_m.get('code'),
                   results_code=summ.get('code') if res_ok else None)
        if not conv_m.get('code') or (res_ok and summ.get('code') != conv_m.get('code')):
            pin['note'] = 'converter code unknown or differs from the result JSON of the shipped run'
            probs.append('pin_unresolved')
    elif src == 'db1':
        code = conv_m.get('code')
        kit = DB1_KITS.get(code)
        ev = []
        if res_ok and summ.get('code') == code:
            ev.append(f'result JSON {res["key"].rsplit("/", 1)[1]} code {code} wrote out_key = step_key with '
                      f'out_bytes = delivered bytes ({r["bytes"]})')
        elif res_ok:
            ev.append(f'result JSON code {summ.get("code")} differs from the manifest converter code {code}')
            kit = None
        else:
            ev.append('no result JSON of the shipped run: kit from the manifest converter code only')
        if conv['same_as_delivered']:
            ev.append('conversion output at step_key is byte-size/etag equal to the package STEP')
        pin.update(code=code, kit=kit, kit_evidence='; '.join(ev), engine=summ.get('engine') if res_ok else None,
                   catalog_overlay=summ.get('catalog_overlay') if res_ok else None,
                   decoded_skipped=summ.get('decoded_skipped') if res_ok else None)
        if kit is None:
            probs.append('pin_unresolved')
        elif kit in LOST_KITS:
            probs.append('pin_lost_kit')
    else:  # sds2
        jj = det.get('job_json') or {}
        vfold = re.search(r'/sds2-step/[0-9a-f]{24}/(v[0-9][^/]*)/', r['step_key'])
        pin.update(version=conv_m.get('version'), version_folder=vfold.group(1) if vfold else None,
                   run=None, label=None, zip=None, zip_sha256=None, code=None, evidence=None)
        if r['step_key'].startswith(R2_PREFIX):
            pin.update(run='r2_v4', label=R2_PIN['label'], zip=R2_PIN['zip'], zip_sha256=R2_PIN['sha256'],
                       evidence='STEP written by the sds2-step-r2-20260929-01 run (no job.json); its deployment zip per '
                                'NOTES_sds2_head.md (11 perfect-tier models re-converted byte-identically with it)')
        elif isinstance(jj.get('converter'), dict) and jj['converter'].get('zip'):
            cv = jj['converter']
            pin.update(run='v5_fleet', label=cv.get('label'), zip=cv.get('zip'), zip_sha256=cv.get('sha256'),
                       code=jj.get('code'), evidence='job.json next to the shipped STEP (same conversion folder)')
        elif jj:
            pin.update(run='v4_fleet' if conv_m.get('version') == 'v4' else 'unknown', code=jj.get('code'),
                       evidence=f'job.json next to the shipped STEP names code {jj.get("code")} but no converter zip')
            probs.append('pin_unresolved')
        else:
            pin.update(evidence='no job.json next to the shipped STEP and not an r2-run key')
            probs.append('pin_unresolved')
        if pin['version_folder'] and conv_m.get('version') and pin['version_folder'] != conv_m.get('version'):
            pin['note'] = f'version folder {pin["version_folder"]} != manifest converter.version {conv_m.get("version")}'
    # ---- row
    row = {
        'jobs_v': JOBS_V, 'model_id': mid, 'pid': pid, 'relpath': r['relpath'], 'model_folder': names[mid],
        'step_source': src, 'partial_kind': (r.get('partial') or {}).get('kind'), 'bytes': r['bytes'], 'class': cls,
        'source_class': size_class(source['bytes']), 'grader_class': r.get('class'),
        'pkg_prefix': pkg_prefix, 'scripts_prefix': pkg_prefix + 'scripts/', 'n_models_in_pkg': n_models,
        'addon': addon, 'step': step, 'source': source, 'conv': conv, 'state': state, 'detail_keys': detail_keys,
        'pin': pin, 'partial': r.get('partial'), 'grader': r.get('grader'), 'verify_verdict': r.get('verify_verdict'),
        'verify_codes': r.get('verify_codes'), 'older_revision_of': r.get('older_revision_of'),
        'sds2_primary': r.get('sds2_primary'), 'also_model_ids': r.get('also_model_ids'),
        'manifest': {'key': pkg_prefix + 'manifest.jsonl', 'etag': pkg['etag'], 'bytes': pkg['bytes'],
                     'placed_at': r.get('placed_at')},
        'problems': sorted(set(probs)),
    }
    row['severity'] = max((SEVERITY[p] for p in row['problems']), key=['info', 'degraded', 'blocking', 'excluded'].index,
                          default='ok')
    return row


# ===================================================================================================== stats
def hist_bucket(n):
    for lo, hi, lab in ((1, 1, '1'), (2, 2, '2'), (3, 5, '3-5'), (6, 10, '6-10'), (11, 20, '11-20'), (21, 50, '21-50'),
                        (51, 100, '51-100'), (101, 10 ** 9, '>100')):
        if lo <= n <= hi:
            return lab


def make_stats(rows, pids, pkgs, p1_ids, errors):
    S = {'jobs_v': JOBS_V, 'built_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    S['packages'] = {'listed_under_3d_partial': len(pids), 'in_projects_p1': len(p1_ids),
                     'listed_not_in_p1': sorted(set(pids) - p1_ids)[:20], 'p1_not_listed': sorted(p1_ids - set(pids))[:20],
                     'with_models': len({r['pid'] for r in rows}), 'errors': errors[:50],
                     'with_existing_scripts_folder': sorted(p for p, k in pkgs.items() if 'scripts' in k.get('topnames', []))}
    S['packages']['with_existing_scripts_folder_count'] = len(S['packages']['with_existing_scripts_folder'])
    S['models'] = len(rows)
    by = collections.defaultdict(lambda: {'models': 0, 'step_bytes': 0, 'source_bytes': 0})
    for r in rows:
        for k in ((r['step_source'], r['class']), (r['step_source'], 'ALL'), ('ALL', r['class']), ('ALL', 'ALL')):
            b = by[k]
            b['models'] += 1
            b['step_bytes'] += r['bytes']
            b['source_bytes'] += r['source']['bytes'] or 0
    order = ['S', 'M', 'L', 'XL', TOO_BIG, 'ALL']
    S['source_x_class'] = {s: {c: by[(s, c)] for c in order if (s, c) in by} for s in ('ifc', 'db1', 'sds2', 'ALL')}
    S['source_x_partial_kind'] = {f'{a}/{b}': n for (a, b), n in sorted(collections.Counter(
        (r['step_source'], r['partial_kind']) for r in rows).items())}
    S['class_step_vs_source'] = {f'{a}->{b}': n for (a, b), n in sorted(collections.Counter(
        (r['class'], r['source_class']) for r in rows if r['class'] != r['source_class']).items(), key=str)}
    S['source_formats'] = dict(collections.Counter(f'{r["step_source"]}/{r["source"]["format"]}' for r in rows))
    ad = [r for r in rows if r['addon']]
    addon_p = collections.defaultdict(set)
    for r in rows:
        addon_p[r['pid']].add(r['addon'])
    S['addons'] = {'models_with_source_in_3d_package': len(ad),
                   'by_source': dict(collections.Counter(r['step_source'] for r in ad)),
                   'unique_3d_packages': len({r['source']['pkg_prefix'] for r in ad}),
                   'partial_packages_all_models_addon': sum(1 for v in addon_p.values() if v == {True}),
                   'partial_packages_no_addon': sum(1 for v in addon_p.values() if v == {False}),
                   'partial_packages_mixed': sum(1 for v in addon_p.values() if v == {True, False})}
    per = collections.Counter(r['pid'] for r in rows)
    S['models_per_package'] = {
        'histogram': {k: v for k, v in sorted(collections.Counter(hist_bucket(n) for n in per.values()).items(),
                                               key=lambda x: ['1', '2', '3-5', '6-10', '11-20', '21-50', '51-100', '>100'].index(x[0]))},
        'max': max(per.values()) if per else 0, 'mean': round(len(rows) / max(1, len(per)), 2),
        'median': sorted(per.values())[len(per) // 2] if per else 0,
        'top10': [{'pid': p, 'models': n} for p, n in per.most_common(10)]}
    S['model_folders'] = {'suffixed_on_clash_or_reserved': sum(1 for r in rows if r['model_folder'] != sanitize(step_stem(r['relpath']))),
                          'fallback_name_model': sum(1 for r in rows if sanitize(step_stem(r['relpath'])) == 'model'),
                          'max_len': max((len(r['model_folder']) for r in rows), default=0)}
    S['pins'] = {
        'ifc_codes': dict(collections.Counter(str(r['pin'].get('code')) for r in rows if r['step_source'] == 'ifc')),
        'ifc_writer_suffix': dict(collections.Counter(str(r['pin'].get('writer_suffix')) for r in rows if r['step_source'] == 'ifc')),
        'db1_kits': dict(collections.Counter(str(r['pin'].get('kit')) for r in rows if r['step_source'] == 'db1')),
        'sds2_runs': dict(collections.Counter(str(r['pin'].get('run')) for r in rows if r['step_source'] == 'sds2')),
        'sds2_zips': dict(collections.Counter(str(r['pin'].get('zip')) for r in rows if r['step_source'] == 'sds2')),
        'sds2_versions': dict(collections.Counter(str(r['pin'].get('version')) for r in rows if r['step_source'] == 'sds2')),
    }
    pc = collections.Counter(p for r in rows for p in r['problems'])
    S['problems'] = {p: {'models': pc[p], 'severity': SEVERITY[p], 'meaning': PROBLEM_CODES[p],
                         'by_source': dict(collections.Counter(r['step_source'] for r in rows if p in r['problems'])),
                         'examples': [r['model_id'] for r in rows if p in r['problems']][:8]}
                     for p in sorted(pc)}
    S['models_without_problems'] = sum(1 for r in rows if not r['problems'])
    S['severity'] = dict(collections.Counter(r['severity'] for r in rows))
    S['severity_x_source'] = {f'{a}/{b}': n for (a, b), n in sorted(collections.Counter(
        (r['step_source'], r['severity']) for r in rows).items())}
    S['runnable_v1'] = {'models': sum(1 for r in rows if r['class'] != TOO_BIG),
                        'blocking_problems_excluding_too_big': sum(1 for r in rows if r['class'] != TOO_BIG and set(r['problems']) & {
                            'step_not_in_package', 'source_missing', 'conv_step_missing', 'pin_lost_kit'})}
    S['detail_aliases'] = dict(collections.Counter(f'{r["step_source"]}/{a}' for r in rows for a in r['detail_keys']))
    return S


# ===================================================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--refresh', action='store_true', help='re-read cached listings and result JSONs from S3')
    ap.add_argument('--new5-only', action='store_true', help='only the packages of ../new5.json')
    ap.add_argument('--pids-from', help='only these package ids (JSON list or one per line)')
    ap.add_argument('--workers', type=int, default=48)
    ap.add_argument('--out', default=os.path.join(HERE, 'jobs_partial.jsonl.gz'))
    args = ap.parse_args()
    t0 = time.time()
    new5 = json.load(open(NEW5))
    p1 = json.load(open(P1))
    p1_ids = {p['id'] for p in p1 if p.get('tier') == 'partial'}
    pids = list_packages(args)
    sel = pids
    if args.new5_only:
        sel = sorted({n['pid'] for n in new5})
        if args.out == os.path.join(HERE, 'jobs_partial.jsonl.gz'):
            args.out = os.path.join(HERE, 'jobs_new5_pkgs.jsonl.gz')
    elif args.pids_from:
        txt = open(args.pids_from).read()
        sel = json.loads(txt) if txt.lstrip().startswith('[') else [l.strip() for l in txt.splitlines() if l.strip()]
    print(f'[make_jobs] {len(pids)} packages listed under 3d_partial/, {len(p1_ids)} partial in projects_p1; '
          f'resolving {len(sel)}', flush=True)

    # ---- packages (manifest model rows + listings)
    pkgs, errors = {}, []

    def one_pkg(pid):
        try:
            return pid, load_package(pid, args)
        except Exception as e:                                       # recorded, never silently skipped
            return pid, {'pid': pid, 'error': f'{type(e).__name__}: {e}'[:300]}
    done = 0
    for pid, pk in s3cache.pmap(one_pkg, sel, workers=min(args.workers, 32)):
        done += 1
        if pk.get('error'):
            errors.append({'pid': pid, 'error': pk['error']})
            continue
        pkgs[pid] = pk
    print(f'[make_jobs] packages loaded: {len(pkgs)} ok, {len(errors)} errors ({time.time() - t0:.0f}s)', flush=True)

    # ---- add-on source packages (dataset/packages/3d/<pid>/model/)
    addon_pfx = sorted({(r['converted_from_package'].rstrip('/') + '/') for pk in pkgs.values() for r in pk['rows']
                        if r['relpath'].startswith('model/step/') and r.get('converted_from_package')})
    addon_ls = {}

    def one_addon(p):
        try:
            return p, s3cache.list_prefix(p + 'model/', 'ls_model_3d', refresh=args.refresh)
        except Exception as e:
            return p, {'__error__': str(e)[:300]}
    for p, lst in s3cache.pmap(one_addon, addon_pfx, workers=min(args.workers, 32)):
        if '__error__' in lst:
            errors.append({'pid': p, 'error': 'addon listing: ' + lst['__error__']})
            lst = {}
        addon_ls[p] = lst
    print(f'[make_jobs] add-on 3d packages listed: {len(addon_ls)} ({time.time() - t0:.0f}s)', flush=True)

    # ---- per model detail
    models = [(pid, r) for pid in sorted(pkgs) for r in pkgs[pid]['rows'] if r['relpath'].startswith('model/step/')]
    print(f'[make_jobs] resolving conversion detail for {len(models)} models ...', flush=True)
    dets = {}
    cnt = [0]

    def one_det(item):
        pid, r = item
        try:
            d = resolve_detail(r, args)
        except Exception as e:
            d = {'v': DETAIL_V, 'error': f'{type(e).__name__}: {e}'[:300]}
        cnt[0] += 1
        if cnt[0] % 2000 == 0:
            print(f'  ... {cnt[0]}/{len(models)} ({time.time() - t0:.0f}s)', flush=True)
        return r['model_id'], d
    for mid, d in s3cache.pmap(one_det, models, workers=args.workers):
        dets[mid] = d

    # ---- rows
    rows = []
    for pid in sorted(pkgs):
        pk = pkgs[pid]
        steps = [r for r in pk['rows'] if r['relpath'].startswith('model/step/')]
        names = package_names([(r['model_id'], r['relpath']) for r in steps])
        for r in steps:
            d = dets.get(r['model_id']) or {}
            if d.get('error'):
                errors.append({'pid': pid, 'model_id': r['model_id'], 'error': 'detail: ' + d['error']})
            cfp = r.get('converted_from_package')
            row = build_row(r, pk, names, len(steps), addon_ls.get((cfp or '').rstrip('/') + '/', {}), d)
            if d.get('error'):
                row['problems'] = sorted(set(row['problems']) | {'results_missing'})
                row['detail_error'] = d['error']
            rows.append(row)
    rows.sort(key=lambda x: (x['pid'], x['model_folder'].lower()))
    assert len({r['model_id'] for r in rows}) == len(rows), 'model_id not unique over the tier'
    jdump_gz(args.out, rows)
    probs = [{'model_id': r['model_id'], 'pid': r['pid'], 'model_folder': r['model_folder'], 'step_source': r['step_source'],
              'class': r['class'], 'problem': p, 'severity': SEVERITY[p], 'meaning': PROBLEM_CODES[p]}
             for r in rows for p in r['problems']]
    stats = make_stats(rows, pids if not (args.new5_only or args.pids_from) else sel, pkgs, p1_ids, errors)
    stats['elapsed_s'] = round(time.time() - t0, 1)
    sfx = '' if not (args.new5_only or args.pids_from) else '_subset'
    jp = os.path.join(HERE, f'jobs_problems{sfx}.jsonl')
    open(jp + '.tmp', 'w').write(''.join(json.dumps(p) + '\n' for p in probs))
    os.replace(jp + '.tmp', jp)
    sp = os.path.join(HERE, f'jobs_stats{sfx}.json')
    json.dump(stats, open(sp + '.tmp', 'w'), indent=1)
    os.replace(sp + '.tmp', sp)

    # ---- new5.jsonl (the 5 NEW test models; never the original 5 samples)
    byid = {r['model_id']: r for r in rows}
    out5 = []
    for n in new5:
        r = byid.get(n['model_id'])
        if r is None:
            print(f'[make_jobs] new5 {n["tag"]}: model {n["model_id"]} not in the job list', file=sys.stderr)
            continue
        for k in ('pid', 'relpath', 'step_source', 'partial_kind', 'bytes'):     # new5.json must agree with the manifest
            assert r[k] == n[k], (n['tag'], k, r[k], n[k])
        assert r['source']['relpath'] == n['converted_from'], (n['tag'], 'converted_from')
        assert r['n_models_in_pkg'] == n['n_in_pkg'], (n['tag'], 'n_in_pkg', r['n_models_in_pkg'], n['n_in_pkg'])
        out5.append(dict({'tag': n['tag']}, **r))
    if len(out5) == len(new5):
        p5 = os.path.join(HERE, 'new5.jsonl')
        open(p5 + '.tmp', 'w').write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in out5))
        os.replace(p5 + '.tmp', p5)
    # ---- report
    print(json.dumps({'models': stats['models'], 'source_x_class': {s: {c: v['models'] for c, v in d.items()}
                                                                    for s, d in stats['source_x_class'].items()},
                      'problems': {p: v['models'] for p, v in stats['problems'].items()},
                      'errors': len(errors), 'new5_rows': len(out5)}, indent=1))
    print(f'[make_jobs] wrote {args.out} ({len(rows)} rows), {sp}, {jp} in {time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
