#!/usr/bin/env python3
"""General CAD packaging core (projpkg4, class-1 STEP only).  Disk-agnostic; disks plug in through adapters/.

  plan   adapter + common conversion index -> per-project plan (read-only: GET/HEAD/LIST only)
  apply  plan -> server-side copies (CopyObject with ChecksumAlgorithm=SHA256: S3 computes the SHA-256 of every copied
         file, compared with the expected digest) + SDS2 job zips + manifest.jsonl + project.json   [FLEET ONLY]
  verify project prefix vs manifest vs project.json vs shipped set (sizes, ETags, S3-stored SHA-256, invariants)
  ledger per-project ledger parts (written after verify passes) -> compacted ledger.jsonl + ledger_index.json
  delta  shipped set - ledger -> package jobs; STEP ETag/key change -> refresh; left the shipped set -> removals queue

Format = projpkg4 as published in cad-disk-extract/dataset/main (pkg_final.py vocabulary), plus: real sha256 on every row,
STEP provenance fields, model/sds2/<job>.zip for SDS2 job folders, steps_not_shipped / native_steps_not_graded in project.json.
ADDITIVE ONLY: never deletes. Removals are queued for the owner.
"""
from __future__ import annotations
import base64, collections, gzip, hashlib, io, json, os, re, threading, time, zipfile
from concurrent.futures import ThreadPoolExecutor

VERSION = 'pkg-2026-10-02g'      # b: reserved PII fields (rows + project.json)
                                  # (10-06) PKG_TIER=partial: the separate partial tier (owner 10-05): same projpkg4 format under
                                  #   packages/3d_partial/, class-2 STEP only, every STEP row flagged (class 2 + partial.kind/issues/
                                  #   missing/standins); PKG_TIER unset = perfect tier, byte-identical behaviour
                                  # g (04:05Z): files trigger on the FULL unresolved list (sidecar); a manifest with duplicate STEP
                                  #   content goes through apply_plan even with nothing to copy
                                  # f (01:55Z): disk12_sha_map + Disk-1/2 folder naming in the adapter (pkg-resolver); representative
                                  #   path per content chosen after resolving; updates add files an earlier run left unresolved
                                  # e (01:30Z): step row size = the copied object's size; a final one-file-per-content pass over the
                                  #   whole manifest; unlisted objects under a project queued for the owner (orphan_unlisted)
                                  # c (lead 00:10Z): one model/step file per STEP content (also_converted_from / also_model_ids);
                                  #   a resolved source whose bytes differ from the manifest sha is never shipped (unresolved:sha_mismatch;
                                  #   a wrong-content object already written goes to the owner's removal queue, never deleted)
                                  # d (owner 00:15Z): one placement per model, in its primary project (pkg.primary_map)
PII_EMPTY = {'method': None, 'verified': None, 'original_sha256': None, 'redacted_at': None}
BUCKET = os.environ.get('PKG_BUCKET', 'bim-proprietary-data')
DATASET = os.environ.get('PKG_DATASET', 'cad-disk-extract/dataset/packages')
TIER = os.environ.get('PKG_TIER', 'perfect')
assert TIER in ('perfect', 'partial'), TIER
ROUTE = '3d' if TIER == 'perfect' else '3d_partial'
PSTATE = os.environ.get('PKG_STATE', 'cad-disk-extract/_state/packaging' if TIER == 'perfect' else 'cad-disk-extract/_state/packaging_partial')
if TIER == 'partial':
    assert PSTATE != 'cad-disk-extract/_state/packaging', 'partial tier must not use the perfect tier state'
# partial tier: a pipeline whose re-run is in progress ships only results of the current converter code (else the STEP would be
# copied now and replaced hours later): {"db1": "z3-db1-2026-10-01v"}
PARTIAL_REQUIRE_CODE = json.loads(os.environ.get('PKG_PARTIAL_REQUIRE_CODE', '{}') or '{}')
# partial tier (owner 10-06): an SDS2 job folder with a few unresolvable non-model files (e.g. meta/properties) still ships its partial STEP;
# the job zip lists every missing member (members_missing_count / members_missing; full list in the sds2_members sidecar). The converter
# inputs (main/mem/subm) must still resolve. The perfect tier keeps sds2_zip_require_complete = True.
MAX_PID = 200

# ---------------------------------------------------------------- projpkg4 vocabulary (pkg_final.py + documented additions)
MODEL = {'.step': 'model/step', '.stp': 'model/step', '.ifc': 'model/ifc', '.db1': 'model/db1', '.db2': 'model/db2',
         '.sat': 'model/sat', '.obj': 'model/obj', '.stl': 'model/stl', '.gltf': 'model/gltf', '.glb': 'model/glb',
         '.ifczip': 'model/ifc', '.ifcxml': 'model/ifc'}            # + ifczip/ifcxml: IFC sources of shipped STEP
DRAW = {'.pdf': 'drawings/pdf', '.dwg': 'drawings/dwg', '.dxf': 'drawings/dxf', '.dg': 'drawings/dg', '.dpm': 'drawings/dpm'}
FAB = {'.nc1': 'fab/nc1'}
TABLE = {'.xls': 'tables/bom', '.xlsx': 'tables/bom', '.csv': 'tables/bom',
         '.kis': 'tables/kiss', '.kiss': 'tables/kiss', '.kss': 'tables/kiss'}  # + .kss: SDS/2 KISS (lead package_cad.py)
STEP_EXT = ('.step', '.stp')
SLOTS = ['model_step', 'model_ifc', 'model_db1', 'model_db2', 'model_sds2', 'drawings', 'fab_nc1', 'bom', 'abm', 'kiss',
         'drawing_index']
ROW_KEYS = ['project_id', 'relpath', 'modality', 'role', 'bytes', 'sha256', 'parser_ok', 'units', 'supersedes', 'etag',
            'source_key']                                           # pkg_final.py order; extras follow
DEFAULT_POLICY = {
    'require_verified': ['db1', 'sds2'],   # index field verified == True (build_index verify_merge) for these pipelines
    'ship_verify_held': False,             # rows whose verifier FAIL/WARN codes are only "held" (V_SDS2_HOLD) do not ship
    'native_step_mode': 'list',            # list: archive STEP files are listed (not graded, not shipped); ship: model/step
    'sds2_zip': True,
    'zip_inline_members_max': 1000,
    'sds2_zip_require_complete': True,     # every file of the job folder resolved, else the SDS2 STEP is not placed
}
if TIER == 'partial':
    DEFAULT_POLICY['sds2_zip_require_complete'] = False


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def ext_of(name: str) -> str:
    low = name.rsplit('/', 1)[-1].lower(); d = low.rfind('.')
    return low if d == 0 else (low[d:] if d > 0 else '')


def classify(name: str, ctx: str):
    """-> (channel, modality, role) exactly as pkg_final.py (ctx = archive folder + '/' + member path)."""
    e = ext_of(name); p = ctx.lower()
    if e in MODEL:
        return MODEL[e], e.lstrip('.'), 'steel_model'
    if e in FAB:
        return FAB[e], 'nc1', 'part_cnc'
    if e in TABLE:
        ch = TABLE[e]
        if 'abm' in p or 'advanced bill' in p: ch = 'tables/abm'
        elif 'kiss' in p: ch = 'tables/kiss'
        elif 'index' in p: ch = 'tables/drawing_index'
        return ch, e.lstrip('.'), 'table'
    if e in DRAW:
        if 'shop' in p: role = 'shop'
        elif 'erect' in p or 'erection' in p or 'general' in p: role = 'ga'
        else: role = 'shop' if e == '.pdf' else 'ga'
        return DRAW[e], e.lstrip('.'), role
    return None, None, None


def flat_name(name: str, srckey: str, taken: set) -> str:
    """pkg_final.py collision rule: bare name first, else <stem>-<sha256(srckey)[:6]>.<ext> (reproducible)."""
    if name not in taken:
        taken.add(name); return name
    stem, dot, ext = name.rpartition('.')
    if not dot: stem, ext = name, ''
    h = hashlib.sha256(srckey.encode('utf-8', 'surrogateescape')).hexdigest()[:6]
    cand = f'{stem}-{h}{dot}{ext}' if dot else f'{stem}-{h}'
    i = 0
    while cand in taken:
        i += 1
        h2 = hashlib.sha256(f'{srckey}#{i}'.encode('utf-8', 'surrogateescape')).hexdigest()[:6]
        cand = f'{stem}-{h2}{dot}{ext}' if dot else f'{stem}-{h2}'
    taken.add(cand); return cand


def project_id(disk: str, tag: str) -> str:
    pid = f'{disk}__{tag}'
    if len(pid) > MAX_PID:   # pkg_final.py cut at 200 (collision-prone); keep 193 + '-' + 6 hex of the full id
        pid = pid[:MAX_PID - 7] + '-' + hashlib.sha256(pid.encode('utf-8', 'surrogateescape')).hexdigest()[:6]
    return pid


def b64_to_hex(b):
    return base64.b64decode(b).hex() if b else None


def hex_to_b64(h):
    return base64.b64encode(bytes.fromhex(h)).decode() if h else None


# ---------------------------------------------------------------- shipping policy (one auditable function)
PERFECT_STATE = 'cad-disk-extract/_state/packaging'
# stand-ins that copy what the source holds (a surface the source stores as a surface, open shells kept as faces, reference meshes);
# every other stand-in type is geometry the converter made up or changed (member / joist envelopes, concrete prisms, nominal or
# guessed bolts, bounding boxes, shells closed by healing) and makes the model 'approximated'
FAITHFUL_STANDINS = {'v6_L4-surface', 'v6_open-surface', 'v6_L3-partial-surface', 'reference_open_surface', 'brep_open_surface'}


def partial_kind(row: dict):
    """class-2 model: 'complete_to_source' only when every listed shortfall is the source's own (category source_data_absent) AND every
    stand-in is a faithful copy of source geometry; else 'approximated' (review 10-06: synthesized stand-ins count)"""
    cats = {m.get('category') for m in (row.get('missing') or []) if isinstance(m, dict)}
    synth = [s_ for s_ in (row.get('standins') or []) if not (isinstance(s_, dict) and s_.get('type') in FAITHFUL_STANDINS)]
    return 'complete_to_source' if cats and cats <= {'source_data_absent'} and not synth else 'approximated'


def partial_block(m: dict):
    return ({'kind': partial_kind(m), 'issues': (m.get('issues') or [])[:50], 'missing': (m.get('missing') or [])[:50],
             'standins': (m.get('standins') or [])[:50]} if m.get('class') == 2 else None)


def partial_sig(m: dict):
    b = partial_block(m)
    return hashlib.sha256(json.dumps(b, sort_keys=True, default=str).encode()).hexdigest()[:16] if b else None


def partial_policy_record(pol: dict):
    """(review 10-06) project.json records the policy actually applied in the partial tier"""
    return {'tier': 'partial', 'ships': 'class-2 STEP only (class 1 ships in the 3d tier; class 3 never)', 'require_verified': [],
            'partial_require_code': PARTIAL_REQUIRE_CODE, 'native_step_mode': pol.get('native_step_mode'), 'sds2_zip': pol.get('sds2_zip'),
            'sds2_zip_require_complete': pol.get('sds2_zip_require_complete'), 'zip_inline_members_max': pol.get('zip_inline_members_max')}


_PERF_RM = None


def _perfect_project_removal_pending(pid):
    """read-only: is the perfect-tier package of pid queued for removal as a whole project?"""
    global _PERF_RM
    if _PERF_RM is None:
        d = get_bytes(BUCKET, f'{PERFECT_STATE}/removals_pending.jsonl') or b''
        _PERF_RM = {json.loads(l)['project_id'] for l in d.decode('utf-8', 'surrogateescape').split('\n') if l.strip()
                    and json.loads(l).get('model_key') is None and json.loads(l).get('reason') in ('left_shipped_set_project', 'dedup_non_primary_project')}
    return pid in _PERF_RM


def ship_decision_partial(row: dict):
    if row.get('class') != 2:
        return False, f"class {row.get('class')}"
    if not row.get('step_key'):
        return False, 'no step_key'
    if row.get('status') not in (None, 'converted', 'converted_stage1_members_only'):
        return False, f"status {row.get('status')}"
    need = PARTIAL_REQUIRE_CODE.get(row.get('pipeline'))
    if need and row.get('converter_code') != need:
        return False, f"re-run on {need} pending"
    return True, 'shipped'


def ship_decision(row: dict, policy: dict = None):
    """-> (shipped: bool, reason).  row = common conversion-index row (see SPEC.md 'common index schema')."""
    if TIER == 'partial':
        return ship_decision_partial(row)
    pol = dict(DEFAULT_POLICY, **(policy or {}))
    if row.get('class') != 1:
        return False, f"class {row.get('class')}"
    if row.get('grader_class') is not None and row.get('grader_class') != 1:
        return False, f"grader_class {row.get('grader_class')}"
    if not row.get('step_key'):
        return False, 'no step_key'
    if row.get('status') not in (None, 'converted'):
        return False, f"status {row.get('status')}"
    if row['pipeline'] in pol['require_verified']:
        if row.get('verified') is not True:
            return False, f"not verified ({row.get('verify_verdict')})"
        held = row.get('verify_held') or []
        if held and not pol['ship_verify_held']:
            return False, 'verify_held:' + ','.join(held)
        if row.get('verify_verdict') not in ('PASS', 'WARN') and not (held and pol['ship_verify_held']):
            return False, f"verify_verdict {row.get('verify_verdict')}"
    return True, 'shipped'


# ---------------------------------------------------------------- S3 helpers (thread-local clients)
_tl = threading.local()


def s3c():
    c = getattr(_tl, 'c', None)
    if c is None:
        import boto3
        from botocore.config import Config
        c = boto3.client('s3', region_name='ap-south-1', config=Config(
            max_pool_connections=int(os.environ.get('PKG_POOL', '64')), retries={'max_attempts': 12, 'mode': 'standard'},
            connect_timeout=30, read_timeout=300))
        _tl.c = c
    return c


def get_bytes(b, k):
    from botocore.exceptions import ClientError
    try:
        return s3c().get_object(Bucket=b, Key=k)['Body'].read()
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') in ('NoSuchKey', '404', 'NotFound'):
            return None
        raise


def get_json(b, k):
    d = get_bytes(b, k)
    if d is None:
        return None
    if d[:2] == b'\x1f\x8b':
        d = gzip.decompress(d)
    return json.loads(d)


def head(b, k, checksum=False):
    from botocore.exceptions import ClientError
    try:
        kw = {'ChecksumMode': 'ENABLED'} if checksum else {}
        return s3c().head_object(Bucket=b, Key=k, **kw)
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') in ('NoSuchKey', '404', 'NotFound'):
            return None
        raise


def list_keys(b, prefix, cap=None):
    out = []; tok = None
    while True:
        kw = {'Bucket': b, 'Prefix': prefix, 'MaxKeys': 1000}
        if tok: kw['ContinuationToken'] = tok
        r = s3c().list_objects_v2(**kw)
        for o in r.get('Contents') or []:
            out.append((o['Key'], int(o.get('Size') or 0), (o.get('ETag') or '').strip('"')))
        if cap and len(out) >= cap: break
        if not r.get('IsTruncated'): break
        tok = r['NextContinuationToken']
    return out


def put_json(b, k, obj, gz=False, if_none_match=False, if_match=None):
    body = json.dumps(obj, indent=None if gz else 1, sort_keys=False).encode()
    kw = {}
    if gz:
        body = gzip.compress(body); kw['ContentEncoding'] = 'gzip'
    if if_none_match: kw['IfNoneMatch'] = '*'
    if if_match: kw['IfMatch'] = if_match
    return s3c().put_object(Bucket=b, Key=k, Body=body, ContentType='application/json', **kw)


def sha256_stream(b, k):
    h = hashlib.sha256(); n = 0
    body = s3c().get_object(Bucket=b, Key=k)['Body']
    for chunk in iter(lambda: body.read(1 << 22), b''):
        h.update(chunk); n += len(chunk)
    return h.hexdigest(), n


# ---------------------------------------------------------------- PLAN
def plan_project(adapter, proj: dict, shipped: list, notshipped: list, policy: dict = None, step_heads: dict = None,
                 existing: list = None, index_ref: dict = None, existing_pj: dict = None):
    """proj = adapter project ref; shipped / notshipped = common rows whose source_paths touch this project.
    existing = current manifest rows (incremental update keeps every existing relpath unchanged).
    Returns the plan dict (no writes)."""
    pol = dict(DEFAULT_POLICY, **(policy or {}))
    pid = proj['project_id']; base = f"{DATASET}/{ROUTE}/{pid}"
    files = sorted(adapter.files(proj), key=lambda r: r['path'].encode('utf-8', 'surrogateescape'))
    # (partial tier, owner 10-05 'deduped everywhere') the project is already packaged in the perfect tier: this package is an ADD-ON
    # that holds only the partial STEP (and an SDS2 job zip the perfect package lacks); the source files are referenced in the perfect
    # package (converted_from_package), never copied a second time
    addon_of = None; perf_rows = []
    if TIER == 'partial':
        if existing:                                  # (review 10-06) decided once, at create: a standalone package stays standalone
            addon_of = (existing_pj or {}).get('addon_of')
            perf_rows = read_manifest(BUCKET, addon_of) if addon_of else []
        elif not _perfect_project_removal_pending(pid):
            perf_rows = read_manifest(BUCKET, f'{DATASET}/3d/{pid}')
            addon_of = f'{DATASET}/3d/{pid}' if perf_rows else None
    taken = collections.defaultdict(set); have_rel = {}
    step_by_content = {}                              # (source STEP etag, bytes) -> step item / existing row placed in this project
    items = []; seen = {}; dup = 0; excluded = 0; zero = 0; natives = []
    if existing:                                      # incremental: existing file rows and relpaths never change
        for r in existing:
            ch = r['relpath'].rsplit('/', 1)[0]; taken[ch].add(r['relpath'].rsplit('/', 1)[1]); have_rel[r['relpath']] = r
            if r.get('sha256'): seen.setdefault((ch, r['sha256']), r['relpath'])
            if r.get('modality') == 'step' and r.get('etag_source'):
                step_by_content.setdefault((r['etag_source'], r.get('bytes')), r)
    def _cand(f, name, ch, modality, role):
        it = {'kind': 'file', 'channel': ch, 'modality': modality, 'role': role, 'bytes': f['size'], 'sha256': f['sha256'],
              'source_path': proj['source_prefix'] + f['path'], 'raw_key': f.get('key'), 'dedup': f.get('dedup'), '_name': name}
        if ext_of(name) in STEP_EXT:
            it.update(modality='step', step_source='native', graded=False)
        if name.lower() == 'xslib.db1':
            it['component_library'] = True            # Tekla component library, not a model (kept for parity, tagged)
        return it
    groups = collections.OrderedDict()                # (channel, sha) -> candidate paths (content dedup inside the project)
    unres_prev = {u.get('path') for u in ((existing_pj or {}).get('unresolved_files') or []) if isinstance(u, dict)} if existing else set()
    for f in (files if not addon_of else []):
        name = f['path'].rsplit('/', 1)[-1]
        if not name:
            continue
        e = ext_of(name)
        if e in STEP_EXT and pol['native_step_mode'] != 'ship':
            natives.append({'path': f['path'], 'bytes': f['size'], 'sha256': f['sha256']})
            continue
        if existing and (proj['source_prefix'] + f['path']) not in unres_prev:
            continue                                  # (f) update: only files an earlier run left unresolved are looked at again
        ch, modality, role = classify(name, proj['tag'] + '/' + f['path'])
        if ch is None:
            if not existing: excluded += 1
            continue
        if f['size'] == 0 and not existing: zero += 1
        ident = (ch, f['sha256'])
        if ident in seen:                             # (update) content already in the package
            continue
        groups.setdefault(ident, []).append(_cand(f, name, ch, modality, role))
    if existing and existing_pj:
        excluded = existing_pj.get('excluded_non_asset_files', 0); dup = existing_pj.get('duplicates_collapsed', 0)
        zero = existing_pj.get('zero_byte_files', 0)
    allc = [c for L in groups.values() for c in L]
    if allc:
        adapter.resolve(proj, allc)
    # (f, packager review 01:50Z) the representative path of each content is chosen AFTER resolving: a resolvable path wins over the
    # first path (which was often inside a nested archive the old extraction never opened)
    for ident, L in groups.items():
        best = next((c for c in L if c.get('src_key') or c['bytes'] == 0), L[0])
        if not existing:
            dup += len(L) - 1
        fn = flat_name(best['_name'], best['source_path'], taken[ident[0]])
        best['relpath'] = f'{ident[0]}/{fn}'; seen[ident] = best['relpath']
        best.pop('_name', None)
        items.append(best)
    unresolved = [it for it in items if it['kind'] == 'file' and not it.get('src_key') and it['bytes'] > 0]
    items = [it for it in items if it not in unresolved]
    if existing:
        # (f) the unresolved list of an updated project: earlier entries minus those resolved now
        now_res = {it['source_path'] for it in items}
        keep_unres = [u for u in ((existing_pj or {}).get('unresolved_files') or []) if not (isinstance(u, dict) and u.get('path') in now_res)]
    else:
        keep_unres = None
    rel_of_sha = {}
    for (ch, sha), rel in seen.items():
        if ch.startswith('model/') and ch != 'model/step':
            rel_of_sha.setdefault(sha, rel)
    perf_rel = set()
    if addon_of:
        for r in perf_rows:
            ch = r['relpath'].rsplit('/', 1)[0]
            if ch.startswith('model/') and ch != 'model/step' and r.get('sha256'):
                rel_of_sha.setdefault(r['sha256'], r['relpath']); perf_rel.add(r['relpath'])
    unres_rel = {it['relpath'] for it in unresolved}
    # ---- shipped STEP + SDS2 zips
    steps = []; zips = []; not_placed = []; attach = []
    for m in sorted(shipped, key=lambda r: (r['pipeline'], r['id'])):
        members_here = [mp for a, mp in m['source_paths'] if adapter.project_of(a) == pid]
        if not members_here:
            continue
        hd = (step_heads or {}).get(m['step_key'])
        if hd is None:
            hd = head(m.get('step_bucket') or BUCKET, m['step_key'])
        if not hd:
            not_placed.append(dict(_ns(m, 'step object missing'))); continue
        if m['pipeline'] in ('ifc', 'db1'):
            src_rel = rel_of_sha.get(m['source_sha256'])
            if not src_rel or src_rel in unres_rel:
                not_placed.append(dict(_ns(m, 'source file not resolvable in this project'))); continue
            stem = members_here[0].rsplit('/', 1)[-1].rsplit('.', 1)[0]
            zipit = None
            from_perf = bool(addon_of)                # add-on: every IFC/DB1 source row comes from the perfect package
        else:                                        # sds2: job folder -> model/sds2/<job>.zip
            root = members_here[0]
            job = root.rstrip('/').rsplit('/', 1)[-1] or 'job'
            stem = job
            ez = next((r for r in existing or [] if r.get('modality') == 'sds2' and
                       r.get('source_path') == proj['source_prefix'] + root), None)
            ezp = next((r for r in perf_rows if r.get('modality') == 'sds2' and
                        r.get('source_path') == proj['source_prefix'] + root), None) if addon_of else None
            from_perf = False
            if ez:                                   # update: the job zip is already in the project
                zipit = None; src_rel = ez['relpath']
            elif ezp:                                # add-on: the job zip is already in the perfect package
                zipit = None; src_rel = ezp['relpath']; perf_rel.add(src_rel); from_perf = True
            else:
                zipit = plan_sds2_zip(adapter, proj, files, root, job, taken, pol, m)
                if zipit.get('error'):
                    not_placed.append(dict(_ns(m, zipit['error']))); continue
                src_rel = zipit['relpath']
        prior = _existing_step(existing, m)
        if prior:                                    # already in the project: refresh only when the STEP changed
            if prior.get('step_key') == m['step_key'] and prior.get('etag_source') == hd['ETag'].strip('"') and \
                    (TIER == 'perfect' or json.dumps(prior.get('partial'), sort_keys=True, default=str) == json.dumps(partial_block(m), sort_keys=True, default=str)):
                continue
            rel = prior['relpath']; mode = 'refresh'
        else:
            # (c) a second model whose STEP has the same content as one already placed here (two source files that convert to
            # identical bytes): no second model/step file; the model is attached to the first (also_converted_from / also_model_ids)
            ck = (hd['ETag'].strip('"'), int(hd['ContentLength']))
            first = step_by_content.get(ck)
            if first is not None and m['pipeline'] in ('ifc', 'db1'):
                also = {'model_id': m['id'], 'model_key': m['model_key'], 'converted_from': src_rel, 'step_key': m['step_key'],
                        'step_source': m['pipeline']}
                if first.get('kind') == 'step':      # placed by this plan
                    first.setdefault('also', []).append(also)
                elif not any(a.get('model_id') == m['id'] for a in first.get('also_models') or []):
                    attach.append({'relpath': first['relpath'], 'also': also})     # existing row: attach at apply (no copy)
                continue
            rel = 'model/step/' + flat_name(stem + '.step', m['step_key'], taken['model/step']); mode = 'add'
        if zipit and not any(z['relpath'] == zipit['relpath'] for z in zips) and zipit['relpath'] not in have_rel:
            zips.append(zipit)
        st_ = _step_item(m, rel, src_rel, hd, mode, members_here)
        if addon_of and from_perf:                   # (review 10-06) decided by where the source came from, not by name
            st_['converted_from_package'] = addon_of
        steps.append(st_)
        if mode == 'add':
            step_by_content.setdefault((st_['etag_source'], st_['bytes']), st_)
    ns = [_ns(r, ship_reason(r, pol)) for r in notshipped] + not_placed
    ns.sort(key=lambda x: (x['pipeline'], str(x['model_id'])))
    st = collections.Counter(i['channel'] for i in items)
    plan = {'project_id': pid, 'disk': adapter.disk, 'source': f"{adapter.disk}/{proj['tag']}",
            'source_archive': proj['source_key'], 'kind': proj.get('kind', 'archive'), 'tag': proj['tag'],
            'bucket': BUCKET, 'dest_prefix': base + '/', 'route': ROUTE, 'mode': 'update' if existing else 'create',
            'planned_at': now(), 'packager': VERSION, 'policy': pol if TIER == 'perfect' else partial_policy_record(pol), 'index_ref': index_ref,
            'items': items, 'steps': steps, 'sds2_zips': zips, 'step_attach': attach, 'addon_of': addon_of,
            'steps_not_shipped': ns, 'native_steps_not_graded': natives,
            'unresolved_files': ([{'path': i['source_path'], 'bytes': i['bytes'], 'sha256': i['sha256'], 'dedup': i.get('dedup'),
                                   'raw_key': i.get('raw_key'), 'why': i.get('src_how')} for i in unresolved]
                                 if not existing else list(keep_unres or [])),
            'excluded_non_asset_files': excluded, 'duplicates_collapsed': dup, 'zero_byte_files': zero,
            'stats': {'files': len(items), 'bytes': sum(i['bytes'] for i in items), 'channels': dict(st),
                      'steps': len(steps), 'step_bytes': sum(s['bytes'] for s in steps),
                      'zips': len(zips), 'zip_member_bytes': sum(z['members_bytes'] for z in zips),
                      'unresolved': len(unresolved), 'unresolved_bytes': sum(i['bytes'] for i in unresolved),
                      'resolved_by': dict(collections.Counter(i.get('src_how') for i in items))}}
    plan['status'] = 'ok' if steps or attach or existing else 'skip_no_shipped_step'
    return plan


def ship_reason(r, pol):
    return ship_decision(r, pol)[1]


def _ns(r, reason):
    return {'model_id': r['id'], 'pipeline': r['pipeline'], 'class': r.get('class'), 'reason': reason,
            'reasons': (r.get('reasons') or r.get('issues') or [])[:3], 'step_key': r.get('step_key')}


def _existing_step(existing, m):
    for r in existing or []:
        if r.get('modality') == 'step' and r.get('model_id') == m['id'] and r.get('step_source') == m['pipeline']:
            return r
    return None


def _step_item(m, rel, src_rel, hd, mode, members_here):
    return {'kind': 'step', 'mode': mode, 'relpath': rel, 'channel': 'model/step', 'modality': 'step',
            'role': 'steel_model', 'bytes': int(hd['ContentLength']), 'sha256': None,
            'src_bucket': m.get('step_bucket') or BUCKET, 'src_key': m['step_key'], 'src_how': 'conversion',
            'etag_source': hd['ETag'].strip('"'),
            'step_source': m['pipeline'], 'converted_from': src_rel, 'model_id': m['id'], 'model_key': m['model_key'],
            'step_key': m['step_key'], 'source_paths_in_project': members_here[:20],
            'converter': {'code': m.get('converter_code'), 'version': m.get('converter')},
            'class': 1 if TIER == 'perfect' else m.get('class'), 'grader': {k: m.get(k) for k in ('grader_class', 'graded_by', 'corpus', 'domain', 'coverage_all',
                                                           'parts_source', 'parts_step', 'solids', 'invalid_solids',
                                                           'schema', 'reused', 'rerun_pending') if m.get(k) is not None},
            'verify_verdict': m.get('verify_verdict'), 'verify_evidence': m.get('verify_evidence'),
            'verify_codes': m.get('verify_codes'), 'verify_held': m.get('verify_held'),
            'sds2_primary': m.get('sds2_primary'), 'older_revision_of': m.get('older_revision_of'),
            'source_sha256': m.get('source_sha256'), 'fpc': m.get('fpc'),
            'partial': partial_block(m)}


def plan_sds2_zip(adapter, proj, files, root, job, taken, pol, m):
    """model/sds2/<job>.zip = every file under the job folder, stored (no compression), exact bytes, sorted names."""
    mem = [f for f in files if f['path'].startswith(root)]
    if not mem:
        return {'error': 'sds2 job folder not in manifest'}
    items = [{'relpath': None, 'bytes': f['size'], 'sha256': f['sha256'], 'raw_key': f.get('key'), 'dedup': f.get('dedup'),
              'rel': f['path'][len(root):], 'source_path': proj['source_prefix'] + f['path'], 'kind': 'member'} for f in mem]
    adapter.resolve(proj, items, sds2_fpc=m.get('fpc'))
    miss = [i for i in items if not i.get('src_key') and i['bytes'] > 0]
    model_miss = [i for i in miss if i['rel'].split('/', 1)[0].lower() in ('main', 'mem', 'subm')]
    if model_miss:
        return {'error': f'sds2 converter inputs unresolved ({len(model_miss)} files)'}
    if miss and pol.get('sds2_zip_require_complete', True):
        return {'error': f'sds2 job folder incomplete: {len(miss)} of {len(items)} files unresolved (e.g. {miss[0]["rel"]})',
                'members_missing': [i['rel'] for i in miss][:50]}
    keep = [i for i in items if i not in miss]
    lines = ''.join(f"{i['rel']}\t{i['bytes']}\t{i['sha256']}\n" for i in sorted(keep, key=lambda i: i['rel']))
    rel = 'model/sds2/' + flat_name(job + '.zip', proj['source_prefix'] + root, taken['model/sds2'])
    return {'kind': 'sds2zip', 'relpath': rel, 'channel': 'model/sds2', 'modality': 'sds2', 'role': 'steel_model',
            'job': job, 'job_root': proj['source_prefix'] + root, 'fpc': m.get('fpc'), 'jsetup_sha256': m.get('jsetup_sha256'),
            'members_count': len(keep), 'members_bytes': sum(i['bytes'] for i in keep),
            'members_digest': hashlib.sha256(lines.encode('utf-8', 'surrogateescape')).hexdigest(),
            'members_missing': [i['rel'] for i in miss][:200], 'members_missing_count': len(miss),
            **({'members_missing_all': [i['rel'] for i in miss]} if miss and TIER == 'partial' else {}),
            'members': [{'p': i['rel'], 'bytes': i['bytes'], 'sha256': i['sha256'], 'src_bucket': i.get('src_bucket'),
                         'src_key': i.get('src_key'), 'how': i.get('src_how')} for i in sorted(keep, key=lambda i: i['rel'])]}


# ---------------------------------------------------------------- APPLY (fleet only)
class ApplyError(Exception):
    pass


def _copy(it, dst_b, dst_k):
    """server-side copy with an S3-computed SHA-256; returns (sha256_hex, etag)."""
    c = s3c(); size = it['bytes']
    src = {'Bucket': it.get('src_bucket') or BUCKET, 'Key': it['src_key']}
    if size == 0 and not it.get('src_key'):
        r = c.put_object(Bucket=dst_b, Key=dst_k, Body=b'', ChecksumAlgorithm='SHA256')
        return b64_to_hex(r.get('ChecksumSHA256')), r['ETag'].strip('"')
    if size <= 5 * 1024 ** 3:
        r = c.copy_object(Bucket=dst_b, Key=dst_k, CopySource=src, MetadataDirective='COPY', TaggingDirective='REPLACE',
                          ChecksumAlgorithm='SHA256')
        cr = r['CopyObjectResult']
        return b64_to_hex(cr.get('ChecksumSHA256')), cr['ETag'].strip('"')
    part = 512 * 1024 ** 2
    mpu = c.create_multipart_upload(Bucket=dst_b, Key=dst_k, ChecksumAlgorithm='SHA256')
    uid = mpu['UploadId']
    try:
        parts = []; pos = 0; n = 0
        while pos < size:
            last = min(pos + part, size) - 1; n += 1
            r = c.upload_part_copy(Bucket=dst_b, Key=dst_k, UploadId=uid, PartNumber=n, CopySource=src,
                                   CopySourceRange=f'bytes={pos}-{last}')
            parts.append({'ETag': r['CopyPartResult']['ETag'], 'PartNumber': n,
                          'ChecksumSHA256': r['CopyPartResult'].get('ChecksumSHA256')})
            pos = last + 1
        r = c.complete_multipart_upload(Bucket=dst_b, Key=dst_k, UploadId=uid, MultipartUpload={'Parts': parts})
    except Exception:
        try: c.abort_multipart_upload(Bucket=dst_b, Key=dst_k, UploadId=uid)
        except Exception: pass
        raise
    h, n = sha256_stream(dst_b, dst_k)            # composite checksum -> full digest by streaming (in-region)
    if n != size:
        raise ApplyError(f'size {n} != {size} after multipart copy')
    return h, r['ETag'].strip('"')


def _existing_ok(dst_b, dst_k, sha):
    h = head(dst_b, dst_k, checksum=True)
    if h and sha and b64_to_hex(h.get('ChecksumSHA256')) == sha and h.get('ChecksumType', 'FULL_OBJECT') == 'FULL_OBJECT':
        return h['ETag'].strip('"')
    return None


def build_zip(z, workdir):
    """download members (sha256-checked while streaming) into a stored zip; returns (path, sha256, size).
    (10-06) members are fetched concurrently into part files (PKG_ZIP_THREADS, default 32), then written into the zip in the same
    order with the same ZipInfo, so the zip is byte-identical to the sequential build; part files are removed as they are appended."""
    import shutil
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, hashlib.sha1(z['relpath'].encode()).hexdigest() + '.zip')
    parts = path + '.parts'; os.makedirs(parts, exist_ok=True)
    members = z['members']

    gone = {}

    def fetch(i):
        m = members[i]; fp = os.path.join(parts, str(i)); h = hashlib.sha256()
        try:
            with open(fp, 'wb') as f:
                if m['bytes'] > 0:
                    body = s3c().get_object(Bucket=m.get('src_bucket') or BUCKET, Key=m['src_key'])['Body']
                    for chunk in iter(lambda: body.read(1 << 22), b''):
                        h.update(chunk); f.write(chunk)
        except Exception as e:
            # (partial tier, 10-06) a resolved member whose stored object no longer exists is listed as missing, like any unresolved
            # non-model member; a converter input (main/mem/subm) that is gone still fails the zip (the STEP would have no source)
            if TIER == 'partial' and 'NoSuchKey' in f'{type(e).__name__} {e}' and m['p'].split('/', 1)[0].lower() not in ('main', 'mem', 'subm'):
                gone[i] = 'stored object no longer exists'; return i
            raise
        if h.hexdigest() != m['sha256']:
            # (partial tier, 10-06) a non-model member whose stored copy has other bytes than the manifest sha is never shipped: it is
            # left out and listed as missing (wrong content), like an unresolved member; a converter input still fails the zip
            if TIER == 'partial' and m['p'].split('/', 1)[0].lower() not in ('main', 'mem', 'subm'):
                gone[i] = f'stored copy has other content (sha {h.hexdigest()[:12]})'; return i
            raise ApplyError(f"zip member sha mismatch {m['p']} ({m.get('src_key')})")
        return i
    try:
        with ThreadPoolExecutor(int(os.environ.get('PKG_ZIP_THREADS', '32'))) as tp:
            list(tp.map(fetch, range(len(members))))
        if gone:                                      # the zip row describes what is really inside
            lost = [members[i]['p'] for i in sorted(gone)]
            lost_why = [{'p': members[i]['p'], 'why': gone[i]} for i in sorted(gone)]
            members = [m for i, m in enumerate(members) if i not in gone]
            for i in sorted(gone, reverse=True):
                fp = os.path.join(parts, str(i))
                if os.path.exists(fp): os.remove(fp)
            os.makedirs(parts + '.k', exist_ok=True)
            keep_idx = [i for i in range(len(z['members'])) if i not in gone]
            for j, i in enumerate(keep_idx):
                os.rename(os.path.join(parts, str(i)), os.path.join(parts + '.k', str(j)))
            shutil.rmtree(parts, ignore_errors=True); os.rename(parts + '.k', parts)
            z['members'] = members
            lines = ''.join(f"{m['p']}\t{m['bytes']}\t{m['sha256']}\n" for m in sorted(members, key=lambda m: m['p']))
            z['members_count'] = len(members); z['members_bytes'] = sum(m['bytes'] for m in members)
            z['members_digest'] = hashlib.sha256(lines.encode('utf-8', 'surrogateescape')).hexdigest()
            allm = list(z.get('members_missing_all') or z.get('members_missing') or []) + lost
            z['members_missing_all'] = allm; z['members_missing'] = allm[:200]; z['members_missing_count'] = len(allm)
            z['members_gone_at_apply'] = lost_why[:200]
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for i, m in enumerate(members):
                zi = zipfile.ZipInfo(z['job'] + '/' + m['p'], date_time=(1980, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_STORED; zi.external_attr = 0o644 << 16
                fp = os.path.join(parts, str(i))
                with zf.open(zi, 'w', force_zip64=m['bytes'] >= 2 ** 31) as w, open(fp, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 22), b''):
                        w.write(chunk)
                os.remove(fp)
    finally:
        shutil.rmtree(parts, ignore_errors=True)
    hz = hashlib.sha256(); n = 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            hz.update(chunk); n += len(chunk)
    return path, hz.hexdigest(), n


def apply_plan(plan: dict, workdir='/tmp/pkgwork', threads=48, log=print):
    """Execute one project plan.  Returns the apply record; raises nothing for per-file failures (they are recorded)."""
    B = plan['bucket']; base = plan['dest_prefix'].rstrip('/')
    rec = {'project_id': plan['project_id'], 'started': now(), 'copied': 0, 'skipped_existing': 0, 'failed': [], 'host': os.uname()[1]}
    rows = []
    existing = read_manifest(B, base) if plan['mode'] == 'update' else []
    present = {k[len(base) + 1:] for k, _, _ in list_keys(B, base + '/')}     # retry: only these need a HEAD
    lock = threading.Lock()

    rec['unresolved_sha'] = []; rec['removal_objects'] = []

    def one(it):
        dst = f"{base}/{it['relpath']}"
        try:
            et = _existing_ok(B, dst, it['sha256']) if it['kind'] == 'file' and it['relpath'] in present else None
            if et:
                sha = it['sha256']; rec_key = 'skipped_existing'
            else:
                if it['kind'] == 'file' and it.get('src_key') and it.get('sha256'):
                    # (c) a candidate with a recorded full-object SHA-256 that differs is never copied
                    hs = head(it.get('src_bucket') or BUCKET, it['src_key'], checksum=True)
                    cs = b64_to_hex(hs.get('ChecksumSHA256')) if hs and hs.get('ChecksumType', 'FULL_OBJECT') == 'FULL_OBJECT' else None
                    if cs and cs != it['sha256']:
                        with lock:
                            rec['unresolved_sha'].append(_unres_sha(it, cs, copied=False))
                        return
                sha, et = _copy(it, B, dst); rec_key = 'copied'
                if it['kind'] == 'file' and sha != it['sha256']:
                    # (c) no recorded sha: checked after the copy. The row is not shipped (unresolved:sha_mismatch) and the written
                    # object goes to the owner's removal queue (never deleted here)
                    with lock:
                        rec['unresolved_sha'].append(_unres_sha(it, sha, copied=True))
                        rec['removal_objects'].append({'relpath': it['relpath'], 'reason': 'sha_mismatch_orphan', 'sha256_written': sha,
                                                       'sha256_manifest': it['sha256'], 'source_key': it.get('src_key'), 'queued_at': now()})
                    return
            size = None
            if it['kind'] == 'step' and rec_key == 'copied':
                # (e) the size of what was actually copied: a STEP re-converted between plan and apply has another size (size_mismatch)
                hd_ = head(B, dst)
                size = int(hd_['ContentLength']) if hd_ else None
            row = make_row(plan, it, sha, et, size=size)
            with lock:
                rec[rec_key] += 1; rows.append(row)
        except Exception as e:
            with lock:
                rec['failed'].append({'relpath': it['relpath'], 'error': f'{type(e).__name__}: {str(e)[:300]}'})
    with ThreadPoolExecutor(threads) as tp:                # STEP first: a create with no STEP landed copies nothing else
        list(tp.map(one, plan['steps']))
    if plan['mode'] == 'create' and not any(r.get('modality') == 'step' for r in rows):
        rec['status'] = 'no_step_placed'; rec['finished'] = now()
        return rec
    def one_zip(z):
        try:
            dst = f"{base}/{z['relpath']}"
            if TIER == 'partial':
                # (10-06) a zip a stopped earlier run already uploaded with exactly this member list is reused, not rebuilt
                h0 = head(B, dst)
                md = (h0 or {}).get('Metadata') or {}
                if h0 and md.get('members-digest') == z['members_digest'] and md.get('sha256'):
                    row = make_row(plan, z, md['sha256'], h0['ETag'].strip('"'), size=int(h0['ContentLength']))
                    with lock:
                        rows.append(row); rec['skipped_existing'] += 1
                    return
            path, sha, n = build_zip(z, os.path.join(workdir, hashlib.sha1(z['relpath'].encode()).hexdigest()[:12]) if TIER == 'partial' else workdir)
            put_json(B, f"{PSTATE}/sds2_members/{plan['project_id']}/{z['relpath'].rsplit('/', 1)[-1]}.json.gz",
                     {'relpath': z['relpath'], 'job_root': z['job_root'], 'zip_sha256': sha, 'members': z['members'],
                      **({'members_missing': z['members_missing_all']} if z.get('members_missing_all') else {})}, gz=True)
            s3c().upload_file(path, B, dst, ExtraArgs={'ChecksumAlgorithm': 'SHA256', 'ContentType': 'application/zip',
                                                        'Metadata': {'sha256': sha, 'members-digest': z['members_digest']}})
            et = head(B, dst)['ETag'].strip('"')
            row = make_row(plan, z, sha, et, size=n)
            with lock:
                rows.append(row); rec['copied'] += 1
            os.remove(path)
        except Exception as e:
            with lock:
                rec['failed'].append({'relpath': z['relpath'], 'error': f'{type(e).__name__}: {str(e)[:300]}'})
    if TIER == 'partial':
        with ThreadPoolExecutor(int(os.environ.get('PKG_ZIP_PAR', '4'))) as tz:
            list(tz.map(one_zip, plan['sds2_zips']))
    else:
        for z in plan['sds2_zips']:
            one_zip(z)
    with ThreadPoolExecutor(threads) as tp:
        list(tp.map(one, plan['items']))
    # (c) earlier runs: duplicate model/step rows of identical content in the manifest -> one row (the first relpath) keeps them as
    # also_*; the other object goes to the owner's removal queue; wrong-content objects of earlier runs (verify_fail examples) too
    existing = _merge_dup_steps(existing, rec)
    if plan['mode'] == 'update':                     # (c) wrong-content objects an earlier run of this project wrote (sha mismatch)
        vf = get_json(B, f"{PSTATE}/verify_fail/{plan['project_id']}.json") or {}
        for f in (vf.get('apply') or {}).get('failed') or []:
            if 'sha256 mismatch' in str(f.get('error')) and f.get('relpath') not in {r['relpath'] for r in existing}:
                m_ = re.search(r'S3 computed ([0-9a-f]{64}), manifest ([0-9a-f]{64}) \(source (.*)', str(f['error']))
                rec['removal_objects'].append({'relpath': f['relpath'], 'reason': 'sha_mismatch_orphan', 'queued_at': now(),
                                               'sha256_written': m_ and m_.group(1), 'sha256_manifest': m_ and m_.group(2),
                                               'source_key': m_ and m_.group(3).rstrip(')')})
                rec['unresolved_sha'].append({'path': f['relpath'], 'relpath': f['relpath'], 'why': 'unresolved:sha_mismatch',
                                              'sha256': m_ and m_.group(2), 'candidate_sha256': m_ and m_.group(1),
                                              'candidate_key': m_ and m_.group(3).rstrip(')'), 'copied_then_queued_for_removal': True})
    for r in list(existing):
        if r['relpath'] in {u['relpath'] for u in rec['unresolved_sha']}:
            existing.remove(r)
    for a in plan.get('step_attach') or []:          # (c) models whose STEP content is already placed here: attach, no copy
        for r in existing:
            if r['relpath'] == a['relpath']:
                _attach(r, a['also'])
    for it in plan['steps']:
        for a in it.get('also') or []:
            for r in rows:
                if r['relpath'] == it['relpath']:
                    _attach(r, a)
    # STEP rows whose converted_from failed are dropped (never ship a STEP without its source)
    ok_rel = {r['relpath'] for r in rows} | {r['relpath'] for r in existing}
    for r in list(rows):
        if r.get('modality') == 'step' and r.get('converted_from') and r['converted_from'] not in ok_rel and not r.get('converted_from_package'):
            rows.remove(r); rec['failed'].append({'relpath': r['relpath'], 'error': 'converted_from missing'})
            if TIER == 'partial':
                rec['removal_objects'].append({'relpath': r['relpath'], 'reason': 'step_without_source', 'queued_at': now()})
    merged = {r['relpath']: r for r in existing}
    for r in rows:
        if r['relpath'] in merged and r.get('modality') == 'step':
            r['refreshed_at'] = now(); r['placed_at'] = merged[r['relpath']].get('placed_at') or r['placed_at']
        merged[r['relpath']] = r
    man = [merged[k] for k in sorted(merged)]
    # (e) final pass: one model/step file per STEP content in the whole manifest (a refresh can bring back a duplicate the earlier
    # merge removed); the other objects are queued for the owner (never deleted here)
    man = _merge_dup_steps(man, rec)
    if plan['mode'] == 'update':
        # (e) objects under the project that no manifest row lists (e.g. a wrong-content copy of an earlier run): queued, not deleted
        listed = {r['relpath'] for r in man} | {'project.json', 'manifest.jsonl'} | {o['relpath'] for o in rec['removal_objects']}
        for k in sorted(present - listed):
            rec['removal_objects'].append({'relpath': k, 'reason': 'orphan_unlisted', 'queued_at': now()})
    if not any(r.get('modality') == 'step' and r.get('step_source') in ('ifc', 'db1', 'sds2') for r in man):
        if TIER == 'partial' and rec['removal_objects']:
            prev_ro = get_json(B, f"{PSTATE}/removal_objects/{plan['project_id']}.json") or {}
            have_ro = {o['relpath'] for o in prev_ro.get('objects') or []}
            put_json(B, f"{PSTATE}/removal_objects/{plan['project_id']}.json",
                     {'project_id': plan['project_id'], 'updated': now(), 'objects': list(prev_ro.get('objects') or []) +
                      [o for o in rec['removal_objects'] if o['relpath'] not in have_ro]})
        rec['status'] = 'no_step_placed'; rec['finished'] = now()
        return rec                                  # nothing written beyond copied files; verify will report them
    if rec['unresolved_sha'] or rec['removal_objects']:
        plan['unresolved_files'] = list(plan.get('unresolved_files') or []) + [u for u in rec['unresolved_sha']
                                                                             if u['path'] not in {x.get('path') for x in plan.get('unresolved_files') or []}]
        prev_ro = get_json(B, f"{PSTATE}/removal_objects/{plan['project_id']}.json") or {}
        have_ro = {o['relpath'] for o in prev_ro.get('objects') or []}
        put_json(B, f"{PSTATE}/removal_objects/{plan['project_id']}.json",
                 {'project_id': plan['project_id'], 'updated': now(), 'objects': list(prev_ro.get('objects') or []) +
                  [o for o in rec['removal_objects'] if o['relpath'] not in have_ro]})
    body = ('\n'.join(json.dumps(r, ensure_ascii=False) for r in man) + '\n').encode('utf-8', 'surrogateescape')
    s3c().put_object(Bucket=B, Key=f'{base}/manifest.jsonl', Body=body, ContentType='application/x-ndjson')
    pj = project_json(plan, man, rec)
    s3c().put_object(Bucket=B, Key=f'{base}/project.json', Body=json.dumps(pj, indent=1, ensure_ascii=False).encode(),
                     ContentType='application/json')
    rec['status'] = 'ok' if not rec['failed'] else 'partial'; rec['files'] = len(man); rec['finished'] = now()
    return rec


def _unres_sha(it, sha_seen, copied):
    return {'path': it['source_path'], 'bytes': it['bytes'], 'sha256': it['sha256'], 'dedup': it.get('dedup'), 'raw_key': it.get('raw_key'),
            'why': 'unresolved:sha_mismatch', 'candidate_key': it.get('src_key'), 'candidate_sha256': sha_seen, 'relpath': it['relpath'],
            'copied_then_queued_for_removal': copied}


def _attach(row, also):
    if any(a.get('model_id') == also['model_id'] for a in row.get('also_models') or []):
        return
    row.setdefault('also_models', []).append(also)
    row['also_converted_from'] = sorted({a['converted_from'] for a in row['also_models'] if a.get('converted_from')})
    row['also_model_ids'] = [a['model_id'] for a in row['also_models']]


def _merge_dup_steps(existing, rec):
    """earlier runs wrote two model/step rows of identical content (two sources converting to the same bytes): keep the first
    relpath, move the other model to its also_*, queue the other object for the owner's removal decision (never deleted)"""
    first = {}; out = []
    for r in sorted(existing, key=lambda x: x['relpath']):
        if r.get('modality') == 'step' and r.get('step_source') in ('ifc', 'db1', 'sds2') and r.get('sha256'):
            f = first.get(r['sha256'])
            if f is not None and r['step_source'] in ('ifc', 'db1'):
                _attach(f, {'model_id': r.get('model_id'), 'model_key': None, 'converted_from': r.get('converted_from'),
                            'step_key': r.get('step_key'), 'step_source': r.get('step_source')})
                rec['removal_objects'].append({'relpath': r['relpath'], 'reason': 'dup_step_content', 'kept_as': f['relpath'],
                                               'sha256': r['sha256'], 'queued_at': now()})
                continue
            first[r['sha256']] = r
        out.append(r)
    return out


def make_row(plan, it, sha, etag, size=None):
    row = {'project_id': plan['project_id'], 'relpath': it['relpath'], 'modality': it['modality'], 'role': it['role'],
           'bytes': size if size is not None else it['bytes'], 'sha256': sha, 'parser_ok': True, 'units': 'mm',
           'supersedes': None, 'etag': etag,
           'source_key': it.get('src_key') if it['kind'] != 'sds2zip' else None,
           'pii_redacted': False, 'pii': dict(PII_EMPTY)}
    if it['kind'] == 'file':
        row.update(source_path=it['source_path'], source_bucket=it.get('src_bucket'), resolved_by=it.get('src_how'))
        if it.get('step_source') == 'native':
            row.update(step_source='native', graded=False)
        if it.get('component_library'):
            row['component_library'] = True
    elif it['kind'] == 'step':
        for k in ('step_source', 'converted_from', 'model_id', 'step_key', 'converter', 'class', 'grader', 'verify_verdict',
                  'verify_evidence', 'verify_codes', 'verify_held', 'sds2_primary', 'older_revision_of', 'source_paths_in_project',
                  'etag_source', 'partial', 'converted_from_package'):
            if it.get(k) is not None:
                row[k] = it[k]
        row['source_bucket'] = it.get('src_bucket'); row['placed_at'] = now()
    elif it['kind'] == 'sds2zip':
        row.update(job=it['job'], source_path=it['job_root'], fpc=it.get('fpc'), jsetup_sha256=it.get('jsetup_sha256'),
                   zip_store='stored (no compression), members byte-exact, names <job>/<path below the job folder>',
                   members_count=it['members_count'], members_bytes=it['members_bytes'], members_digest=it['members_digest'],
                   members_missing_count=it['members_missing_count'], members_missing=it['members_missing'][:50],
                   members_list_key=f"{PSTATE}/sds2_members/{plan['project_id']}/{it['relpath'].rsplit('/', 1)[-1]}.json.gz")
        if it['members_count'] <= plan['policy'].get('zip_inline_members_max', 1000):
            row['members'] = [{'p': m['p'], 'bytes': m['bytes'], 'sha256': m['sha256']} for m in it['members']]
    return row


def project_json(plan, man, rec=None):
    slots = collections.Counter(r['relpath'].rsplit('/', 1)[0] for r in man)
    got = {'model_step': slots.get('model/step', 0), 'model_ifc': slots.get('model/ifc', 0), 'model_db1': slots.get('model/db1', 0),
           'model_db2': slots.get('model/db2', 0), 'model_sds2': slots.get('model/sds2', 0),
           'drawings': sum(v for k, v in slots.items() if k.startswith('drawings/')), 'fab_nc1': slots.get('fab/nc1', 0),
           'bom': slots.get('tables/bom', 0), 'abm': slots.get('tables/abm', 0), 'kiss': slots.get('tables/kiss', 0),
           'drawing_index': slots.get('tables/drawing_index', 0)}
    mfmt = collections.Counter(r['modality'] for r in man if r['relpath'].startswith('model/'))
    dfmt = collections.Counter(r['modality'] for r in man if r['relpath'].startswith('drawings/'))
    steps = [r for r in man if r.get('modality') == 'step']
    by_src = collections.Counter(r.get('step_source') for r in steps)
    conv = {}
    for r in steps:
        if r.get('step_source') in ('ifc', 'db1', 'sds2'):
            c = conv.setdefault(r['step_source'], {'step_added': 0, 'converter': [], 'added_at': None})
            c['step_added'] += 1
            code = (r.get('converter') or {}).get('code')
            if code and code not in c['converter']: c['converter'].append(code)
            c['added_at'] = max(filter(None, [c['added_at'], r.get('refreshed_at') or r.get('placed_at')]), default=None)
    unres = plan.get('unresolved_files') or []
    warnings = ['drawing role (shop/ga) inferred from source path keywords',
                'only class-1 STEP (graded; verified where a verifier exists) ship in model/step; see steps_not_shipped'
                if TIER == 'perfect' else
                'PARTIAL TIER: only class-2 (partial) STEP ship in model/step here; every STEP row lists its shortfalls (partial.kind: '
                'complete_to_source = the STEP holds everything the source holds, approximated = some parts left out or stood in; '
                'partial.issues / missing / standins); class-1 STEP of the same project ship in the 3d (perfect) tier']
    if plan.get('native_steps_not_graded'):
        warnings.append(f"{len(plan['native_steps_not_graded'])} STEP file(s) from the archive are not graded: listed in "
                        "native_steps_not_graded, not shipped")
    if unres:
        warnings.append(f'{len(unres)} asset file(s) could not be resolved to a stored object: listed in unresolved_files, not shipped')
    if TIER == 'partial':
        inc = [r for r in man if r.get('modality') == 'sds2' and r.get('members_missing_count')]
        if inc:
            warnings.append(f"{len(inc)} SDS2 job zip(s) are missing {sum(r['members_missing_count'] for r in inc)} non-model member file(s) that "
                            "could not be resolved: listed per zip in members_missing (full list in the members_list_key sidecar)")
    failed = (rec or {}).get('failed') or []
    return {'id': plan['project_id'], 'source': plan['source'], 'units': 'mm', 'domain': 'structural_steel', 'year': None,
            'status': 'complete' if not unres and not failed else 'partial', 'route': ROUTE, 'slots': got,
            'model_formats': dict(mfmt), 'drawing_formats': dict(dfmt),
            'missing': [k for k in SLOTS if not got.get(k)], 'warnings': warnings, 'skipped_files': [f['relpath'] for f in failed][:200],
            'model_step_schemas': {}, 'files': len(man), 'bytes': sum(r['bytes'] for r in man),
            'excluded_non_asset_files': plan['excluded_non_asset_files'], 'duplicates_collapsed': plan['duplicates_collapsed'],
            'zero_byte_files': plan.get('zero_byte_files', 0),
            'packaged_at': now(), 'packaged_by': os.uname()[1],
            # --- general packager additions
            'disk': plan['disk'], 'source_archive': plan['source_archive'], 'source_kind': plan.get('kind'),
            'packager': VERSION, 'sha256': 'computed for every row (S3 SHA-256 checksum on copy; zips hashed at build)',
            'conversions': conv, 'model_step_by_source': dict(by_src),
            'steps_not_shipped': plan['steps_not_shipped'][:500], 'steps_not_shipped_count': len(plan['steps_not_shipped']),
            # (c, owner 00:15Z) each model is packaged once, in its primary project; the other archives holding it are listed here
            'also_in_archives': (plan.get('also_in_archives') or [])[:500], 'models_also_elsewhere': plan.get('models_also_elsewhere', 0),
            'native_steps_not_graded': plan['native_steps_not_graded'][:500],
            'native_steps_not_graded_count': len(plan['native_steps_not_graded']),
            'unresolved_files': unres[:200], 'unresolved_files_count': len(unres),
            'index_ref': plan.get('index_ref'), 'policy': plan.get('policy'), 'pii': pii_block(man),
            **({'tier': 'partial', 'addon_of': plan.get('addon_of'),
                'sources': ('in the perfect package (addon_of): only partial STEP files (and SDS2 job zips the perfect package lacks) are here'
                            if plan.get('addon_of') else 'in this package'),
                'partial_steps': dict(collections.Counter((r.get('partial') or {}).get('kind') for r in steps if r.get('step_source') in ('ifc', 'db1', 'sds2'))),
                'perfect_package': (f"{DATASET}/3d/{plan['project_id']}" if head(BUCKET, f"{DATASET}/3d/{plan['project_id']}/project.json") else None)}
               if TIER == 'partial' else {})}


def pii_block(man):
    n = sum(1 for r in man if r.get('pii_redacted'))
    return {'status': 'not_redacted' if n == 0 else 'partially_redacted', 'files_redacted': n}


def read_manifest(B, base):
    d = get_bytes(B, f'{base}/manifest.jsonl')
    if not d:
        return []
    # (10-05) split on '\n' only: str.splitlines() also breaks at U+2028 / U+0085 / \x1c-\x1e inside file names (valid JSON rows)
    return [json.loads(l) for l in d.decode('utf-8', 'surrogateescape').split('\n') if l.strip()]


# ---------------------------------------------------------------- VERIFY
def verify_project(B, pid, shipped_keys: dict = None, full_hash=False, threads=32):
    """Checks (all must be 0): missing_object, orphan_object, size_mismatch, etag_mismatch, sha_mismatch, sha_unverified,
    step_not_shipped, step_key_changed, converted_from_missing, dup_content, dup_relpath, pj_files, pj_bytes, pj_slots_step,
    pj_route_id.  shipped_keys = {model_id: step_key} of the shipped set (None = skip shipped checks)."""
    base = f'{DATASET}/{ROUTE}/{pid}'
    objs = {k[len(base) + 1:]: (sz, et) for k, sz, et in list_keys(B, base + '/')}
    man = read_manifest(B, base)
    pj = get_json(B, f'{base}/project.json') or {}
    chk = collections.Counter(); ex = collections.defaultdict(list); info = collections.Counter()

    def bad(c, x):
        chk[c] += 1
        if len(ex[c]) < 5: ex[c].append(x)
    rels = [r['relpath'] for r in man]
    for r in [x for x, n in collections.Counter(rels).items() if n > 1]:
        bad('dup_relpath', r)
    rowset = set(rels)
    queued = {o['relpath'] for o in ((get_json(B, f'{PSTATE}/removal_objects/{pid}.json') or {}).get('objects') or [])}
    for k in objs:
        if k not in rowset and k not in ('project.json', 'manifest.jsonl'):
            if k in queued:
                info['orphan_queued_for_removal'] += 1   # (c) in the owner's removal queue (wrong content / duplicate): still present
            else:
                bad('orphan_object', k)
    seen = {}

    def shacheck(r):
        k = f"{base}/{r['relpath']}"
        h = head(B, k, checksum=True)
        cs = b64_to_hex(h.get('ChecksumSHA256')) if h else None
        if h and cs and h.get('ChecksumType', 'FULL_OBJECT') == 'FULL_OBJECT':
            return r, ('ok' if cs == r['sha256'] else 'mismatch')
        if h and h.get('Metadata', {}).get('sha256') and not full_hash:
            return r, ('ok' if h['Metadata']['sha256'] == r['sha256'] else 'mismatch')
        if full_hash and h:
            return r, ('ok' if sha256_stream(B, k)[0] == r['sha256'] else 'mismatch')
        return r, ('deferred' if h else 'unverified')     # composite (multipart) checksum: run with full_hash
    present = []
    ext = {}                                           # partial-tier add-on: relpaths of the perfect package its STEP rows point to
    for r in man:
        cp_ = r.get('converted_from_package')
        if cp_ and cp_ not in ext:
            ext[cp_] = {x['relpath'] for x in read_manifest(B, cp_)}
    for r in man:
        o = objs.get(r['relpath'])
        if o is None:
            bad('missing_object', r['relpath']); continue
        if o[0] != r['bytes']: bad('size_mismatch', r['relpath'])
        if r.get('etag') and o[1] != r['etag']: bad('etag_mismatch', r['relpath'])
        if not r.get('sha256'): bad('sha_unverified', r['relpath'])
        if 'pii_redacted' not in r: bad('pii_fields_missing', r['relpath'])
        if not r.get('source_key') and r.get('modality') != 'sds2' and r['bytes'] > 0: bad('source_key_missing', r['relpath'])
        else: present.append(r)
        ck = (r['relpath'].rsplit('/', 1)[0], r.get('sha256'))
        if r.get('sha256') and ck in seen: bad('dup_content', r['relpath'])
        seen[ck] = r['relpath']
        if r.get('modality') == 'step' and r.get('step_source') in ('ifc', 'db1', 'sds2'):
            rs_ = rowset | ext.get(r.get('converted_from_package'), set())
            if not r.get('converted_from') or r['converted_from'] not in rs_: bad('converted_from_missing', r['relpath'])
            for cf_ in r.get('also_converted_from') or []:
                if cf_ not in rs_: bad('converted_from_missing', r['relpath'])
            if shipped_keys is not None:
                sk = shipped_keys.get(r.get('model_id'))
                if sk is None: bad('step_not_shipped', r['relpath'])
                elif sk != r.get('step_key'): bad('step_key_changed', r['relpath'])
                for a in r.get('also_models') or []:
                    ska = shipped_keys.get(a.get('model_id'))
                    if ska is None: bad('step_not_shipped', r['relpath'])
                    elif a.get('step_key') and ska != a['step_key']: bad('step_key_changed', r['relpath'])
        elif r.get('modality') == 'step' and r.get('step_source') == 'native' and shipped_keys is not None:
            pass                                       # native STEP only present when native_step_mode=ship (graded=false)
    with ThreadPoolExecutor(threads) as tp:
        for r, v in tp.map(shacheck, present):
            if v == 'mismatch': bad('sha_mismatch', r['relpath'])
            elif v == 'unverified': bad('sha_unverified', r['relpath'])
            elif v == 'deferred': info['sha_deferred_full_hash'] += 1
    if pj.get('files') != len(man): bad('pj_files', f"{pj.get('files')} vs {len(man)}")
    if pj.get('bytes') != sum(r['bytes'] for r in man): bad('pj_bytes', pj.get('bytes'))
    nstep = sum(1 for r in man if r['relpath'].startswith('model/step/'))
    if (pj.get('slots') or {}).get('model_step') != nstep: bad('pj_slots_step', f"{(pj.get('slots') or {}).get('model_step')} vs {nstep}")
    if pj.get('route') != ROUTE or pj.get('id') != pid: bad('pj_route_id', f"{pj.get('route')} {pj.get('id')}")
    if (pj.get('pii') or {}).get('files_redacted') != sum(1 for r in man if r.get('pii_redacted')): bad('pj_pii', pj.get('pii'))
    if not any(r.get('step_source') in ('ifc', 'db1', 'sds2') for r in man): bad('no_shipped_step', pid)
    return {'project_id': pid, 'checked_at': now(), 'rows': len(man), 'objects': len(objs), 'ok': sum(chk.values()) == 0,
            'checks': dict(chk), 'info': dict(info), 'examples': dict(ex)}


# ---------------------------------------------------------------- LEDGER / DELTA
def ledger_part(plan, man, verify):
    pl = {}
    for r in man:
        if r.get('modality') == 'step' and r.get('step_source') in ('ifc', 'db1', 'sds2'):
            mk = f"{plan['disk']}:{r['step_source']}:{r['model_id']}"
            pl[mk] = {'step_key': r['step_key'], 'step_etag': r.get('etag_source'), 'step_sha256': r['sha256'],
                      'relpath': r['relpath'], 'converted_from': r.get('converted_from'), 'placed_at': r.get('placed_at'),
                      'refreshed_at': r.get('refreshed_at'), **({'converted_from_package': r['converted_from_package']} if r.get('converted_from_package') else {}),
                      **({'partial_sig': hashlib.sha256(json.dumps(r['partial'], sort_keys=True, default=str).encode()).hexdigest()[:16]} if r.get('partial') else {})}
            for a in r.get('also_models') or []:     # (c) same STEP content, one file
                pl[f"{plan['disk']}:{a.get('step_source') or r['step_source']}:{a['model_id']}"] = dict(
                    pl[mk], step_key=a.get('step_key') or r['step_key'], converted_from=a.get('converted_from'), shared_with=r.get('model_id'))
    return {'project_id': plan['project_id'], 'disk': plan['disk'], 'updated': now(), 'verify_ok': verify['ok'],
            'packager': VERSION, 'placements': pl}


def compact_ledger(B, write=True):
    """merge ledger_parts/<pid>.json -> ledger.jsonl + ledger_index.json (single writer: the coordinator)."""
    parts = [k for k, _, _ in list_keys(B, f'{PSTATE}/ledger_parts/') if k.endswith('.json')]
    with ThreadPoolExecutor(32) as tp:
        docs = list(tp.map(lambda k: get_json(B, k), parts))
    rows = []; idx = {}
    for d in filter(None, docs):
        for mk, p in d['placements'].items():
            rows.append(dict(model_key=mk, project_id=d['project_id'], **p))
            e = idx.setdefault(mk, {'step_key': p['step_key'], 'step_etag': p['step_etag'], 'step_sha256': p['step_sha256'],
                                    'projects': [], 'first_placed': p.get('placed_at'), 'last': p.get('refreshed_at') or p.get('placed_at'),
                                    **({'partial_sig': p['partial_sig']} if p.get('partial_sig') else {}),
                                    **({'shared_with': p['shared_with']} if p.get('shared_with') and TIER == 'partial' else {})})
            e['projects'].append(d['project_id'])
    rows.sort(key=lambda r: (r['model_key'], r['project_id']))
    if write:
        s3c().put_object(Bucket=B, Key=f'{PSTATE}/ledger.jsonl', Body=('\n'.join(json.dumps(r) for r in rows) + '\n').encode(),
                         ContentType='application/x-ndjson')
        put_json(B, f'{PSTATE}/ledger_index.json', {'updated': now(), 'models': len(idx), 'placements': len(rows), 'index': idx})
    return rows, idx
