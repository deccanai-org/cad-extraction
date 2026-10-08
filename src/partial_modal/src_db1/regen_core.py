#!/usr/bin/env python3
"""regen_core.py JOB.json WORK_DIR OUT_DIR   (container side; runs in the decoder env /opt/conv/env/bin/python)

DB1 -> IFC source stage of the partial-tier pipeline: regenerate the decoder IFC of one DB1-sourced model with the kit that
produced its shipped STEP, give it the shipped STEP's GlobalIds and PROVE the IFC reproduces the shipped STEP.
This is db1_regen/scripts/regen.py (171/171 bench models reproduced) packaged for Modal: same commands, same kits, same envs;
inputs are local files (the Modal wrapper downloads them from pre-signed URLs), no S3 / boto3, nothing else is fetched.

JOB.json  {model_id, pid, step_relpath, converter_code,
           files: {db1: path, step: path, census: path|null, result: path|null, decoded_parts: path|null},
           keys: {db1, step, census, result, decoded_parts} (S3 keys, provenance only), step_bytes, db1_bytes}
           (census = the fleet's <id>.u.src_parts.jsonl.gz, result = results/<id>.json, decoded_parts = <id>.decoded_parts.json.gz)
Attempts = (kit, CPU numeric profile) pairs, in order (kit = /opt/kits/kit_v | kit_u; chosen from the shipped STEP's FILE_NAME,
the other kit is tried when the first does not reproduce; anything else = a lost kit -> refused):
  CPU numeric profiles (the decoder's and the STEP stage's numbers depend on the CPU kernels numpy / OpenBLAS dispatch: on
  Modal, an AVX2-only host writes n1's STEP with 9,603 different lines, an AVX-512 host reproduces it exactly -
  tests/results/diag_cpu_repro.json). The host must have AVX-512 (checked first; otherwise verdict host_unsuitable, the
  caller retries on another container). Each profile pins the kernels so the result does not depend on the host model:
    x86-64-v4  OPENBLAS_CORETYPE=SkylakeX, numpy AVX-512 dispatch on (AVX512_SPR off)  = an AVX-512 fleet host (tried first)
    x86-64-v3  OPENBLAS_CORETYPE=Haswell, numpy X86_V4 / AVX512_* off                  = an AVX2-only fleet host
  order: (pinned kit, v4), (pinned kit, v3), (other kit, v4), (other kit, v3); stops at the first reproduction or when the
  stage deadline leaves no time for another attempt.
Steps per attempt:
  1. in.db1 sha256 must equal the model id; Tekla engine banner -> the kit's approved record layout (+ all layouts as variants)
  2. ifc84 venv: convert_one.py in.db1 model.ifc tekla_profiles.json layout.json convert.json variants.json
     (re-run with DB1_FULL_DISCOVERY=1 when the fast path defers, exactly as the conversion worker did)
  3. ifc84 venv: ifc2step6.py model.ifc model.stp --mode hybrid --prec 2 --threads 4 (OCC read-back verifier = /opt/conv/env)
  4. stepcmp regenerated STEP vs shipped STEP: every line equal modulo #numbering / FILE_NAME; PRODUCT.id aligned -> GlobalId map
  5. restore: product GlobalIds replaced by the shipped ones (text substitution on IfcRoot lines only); IfcRoot entities with no
     STEP product get ifcopenshell.guid.compress(sha256("<model id>:<entity id>")[:32])
  6. time normalisation (determinism): the IFC header FILE_NAME time_stamp and IfcOwnerHistory.CreationDate (the decoder writes
     the wall clock) are set to the shipped STEP's FILE_NAME time (the original conversion's STEP write time); text substitution
  7. the final IFC (restored + normalised) is converted again; its STEP must equal the shipped STEP line for line INCLUDING every
     PRODUCT.id -> verdict 'reproduced', OUT_DIR/source/model.ifc written
  8. census cross-check vs the conversion fleet's own census of its IFC (gid, class, name per product), when given
Outputs (OUT_DIR = the model's folder):
  source/model.ifc            only when reproduced (byte-deterministic for the same inputs)
  source/provenance.json      always (deterministic: no wall times, no run paths)
  source/skipped_records.json the decoder's skipped records with their source geometry + bolt groups / cut bodies / fittings
                              (db1_facts.py; deterministic) - whenever the pinned kit decodes the DB1
  logs/src_db1.log            decoder / STEP stage output;  logs/src_db1_run.json  timings + raw comparison outputs
  logs/db1_decoder_stats.json, logs/db1_decoded_parts.json.gz   the decoder's own stats / part list (when produced)
Prints one JSON line (the stage result) and exits 0 unless the script itself breaks."""
import calendar, gzip, hashlib, json, os, re, shutil, subprocess, sys, time, uuid, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cpu_facts  # noqa: E402  (standard library only)

CONV = os.environ.get('PMP_CONV_HOME', '/opt/conv')
PY84 = f'{CONV}/ifc84/bin/python'        # ifcopenshell 0.8.4.post1 venv: decoder IFC writer + STEP stage (as in production)
PYE = f'{CONV}/env/bin/python'           # conda env: ifcopenshell 0.9.0 + pythonocc-core 8.0.1 (read-back verifier, stepcmp)
KITS = os.environ.get('PMP_KITS', '/opt/kits')
HERE = os.path.dirname(os.path.abspath(__file__))
DEC_TIMEOUT = 7200       # worker.py DEC_TIMEOUT
STEP_TIMEOUT = 21600     # worker.py STEP_TIMEOUT
STEP_WRITER = 'ifc2step6 6.1.7'                 # the STEP stage of both packaged kits (u and v: ifc2step6.py md5 d0e8fcc1...)
V_DEPLOY = '2026-10-05T22:46:00'                # code v deployed to the conversion fleet (UTC)
U_EVIDENCED_FROM = '2026-10-02T21:45:54'        # earliest STEP whose live kit is evidenced byte-equal to kit_u (decoder + STEP files)
KIT_CODE = {'kit_v': 'z3-db1-2026-10-01v', 'kit_u': 'z3-db1-2026-10-01u'}
RESULT_STEP_FALLBACKS = ('rescue', 'unholed_elements', 'excluded_elements')
FN_RE = re.compile(rb"FILE_NAME\('(?:[^']|'')*','([^']*)',.*?,'(ifc2step6 [0-9.]+)'", re.S)
# CPU numeric profiles (see the docstring). env = what is set for the decoder, the STEP stage and db1_facts.py
PROFILES = {
    'x86-64-v4': {'env': {'OPENBLAS_CORETYPE': 'SkylakeX', 'NPY_DISABLE_CPU_FEATURES': 'AVX512_SPR'},
                  'means': 'an AVX-512 host: OpenBLAS SkylakeX kernels (what OpenBLAS selects on Skylake-SP / Cascade Lake / '
                           'Ice Lake Xeons and AMD Zen 4), numpy X86_V3 + X86_V4 (+ AVX512_ICL where the host has it) dispatch'},
    'x86-64-v3': {'env': {'OPENBLAS_CORETYPE': 'Haswell', 'NPY_DISABLE_CPU_FEATURES': 'X86_V4 AVX512_ICL AVX512_SPR'},
                  'means': 'an AVX2-only host (e.g. AMD Zen 3): OpenBLAS Haswell kernels, numpy X86_V3 dispatch only'},
}
PROFILE_ORDER = ('x86-64-v4', 'x86-64-v3')
CONVERSION_OVERLAY_MD5 = None     # catalog overlay md5 the conversion result JSON records (set in main)


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def engine_of(path):
    raw = open(path, 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    m = re.search(rb'(\d+\.\d+)', data[:16])
    return m.group(1).decode() if m else None


def step_file_name(path):
    """shipped STEP header -> (FILE_NAME time_stamp, 'ifc2step6 X.Y.Z', the whole FILE_NAME line)"""
    head = open(path, 'rb').read(1 << 16)
    m = FN_RE.search(head)
    line = re.search(rb'FILE_NAME\(.*?\);', head, re.S)
    return (m.group(1).decode() if m else None, m.group(2).decode() if m else None,
            line.group(0).decode('latin-1') if line else None)


def run(cmd, log, timeout, env, cwd):
    t = time.time()
    with open(log, 'a') as lf:
        lf.write(f'\n$ {" ".join(cmd)}\n')
        lf.flush()
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=cwd, start_new_session=True)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, 9)
            p.wait()
            rc = 124
    return rc, round(time.time() - t, 1)


def stepcmp(a, b, mp=None):
    cmd = [PYE, os.path.join(HERE, 'stepcmp.py'), a, b] + (['--map', mp] if mp else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {'error': (r.stdout + r.stderr)[-1500:]}


def ifc_guid(mid, eid):
    import ifcopenshell.guid
    return ifcopenshell.guid.compress(uuid.UUID(hashlib.sha256(f'{mid}:{eid}'.encode()).hexdigest()[:32]).hex)


def restore(mid, src, dst, gmap, map_out=None):
    """GlobalId substitution on IfcRoot entity lines (#id=IFCTYPE('<22 chars>',...); every other byte unchanged (regen.py).
    map_out: JSON {regenerated GlobalId: final GlobalId} of every substituted IfcRoot entity (db1_facts.py maps the
    reproducing run's parts list through it)"""
    import ifcopenshell
    f = ifcopenshell.open(src)
    roots = {e.id(): e.GlobalId for e in f.by_type('IfcRoot')}
    del f
    pat = re.compile(rb"^#(\d+)=([A-Z0-9]+)\('([0-9A-Za-z_$]{22})'")
    n_prod = n_other = 0
    seen = set()
    other = []
    full = {}
    with open(src, 'rb') as fi, open(dst + '.tmp', 'wb') as fo:
        for line in fi:
            m = pat.match(line)
            if m and int(m.group(1)) in roots and roots[int(m.group(1))] == m.group(3).decode():
                old = m.group(3).decode()
                eid = int(m.group(1))
                if old in gmap:
                    new = gmap[old]
                    n_prod += 1
                    seen.add(old)
                else:
                    new = ifc_guid(mid, eid)
                    n_other += 1
                    other.append([eid, m.group(2).decode(), new])
                full[old] = new
                line = line[:m.start(3)] + new.encode() + line[m.end(3):]
            fo.write(line)
    os.replace(dst + '.tmp', dst)
    if map_out:
        json.dump(full, open(map_out, 'w'))
    missing = sorted(set(gmap) - seen)
    return {'ifcroot_entities': len(roots), 'product_guids_restored': n_prod, 'other_guids_derived': n_other,
            'derived': other[:200], 'derived_total': len(other), 'map_entries_not_found_in_ifc': len(missing)}


def normalise_times(src, dst, stamp):
    """header FILE_NAME time_stamp -> stamp; every IfcOwnerHistory CreationDate -> epoch(stamp, UTC). Text substitution on those
    lines only; the substituted values have the same lengths as the clock values they replace (ISO-19 / 10-digit epoch)."""
    epoch = calendar.timegm(time.strptime(stamp, '%Y-%m-%dT%H:%M:%S'))
    fn = re.compile(rb"^(FILE_NAME\('(?:[^']|'')*',')([^']*)(')")
    oh = re.compile(rb'^(#\d+=IFCOWNERHISTORY\(.*,)(\d+)(\);\s*)$', re.S)
    n_fn = n_oh = 0
    old_fn = None
    in_header = True
    with open(src, 'rb') as fi, open(dst + '.tmp', 'wb') as fo:
        for line in fi:
            if in_header:
                if line.startswith(b'DATA;'):
                    in_header = False
                else:
                    m = fn.match(line)
                    if m:
                        old_fn = m.group(2).decode()
                        line = m.group(1) + stamp.encode() + m.group(3) + line[m.end(3):]
                        n_fn += 1
            elif line.startswith(b'#') and b'=IFCOWNERHISTORY(' in line[:24]:
                m = oh.match(line)
                if m:
                    line = m.group(1) + str(epoch).encode() + m.group(3)
                    n_oh += 1
            fo.write(line)
    os.replace(dst + '.tmp', dst)
    return {'stamp': stamp, 'creation_date_epoch': epoch, 'file_name_lines': n_fn, 'owner_history_lines': n_oh,
            'replaced_file_name_time_was_regeneration_time': old_fn is not None}


def census_check(ifc, census_gz):
    """restored IFC products vs the conversion fleet's census of ITS IFC (gid, class, name per product with a body); products
    whose GlobalId had to be derived (no STEP product) are listed with the census entries of the same class + name that no
    restored product claims (= the original GlobalId candidates; reported, not applied)"""
    import ifcopenshell
    if not census_gz or not os.path.exists(census_gz):
        return {'available': False}
    cen = {}
    for l in gzip.open(census_gz, 'rt'):
        r = json.loads(l)
        cen[r['gid']] = (r.get('cls'), r.get('name'))
    f = ifcopenshell.open(ifc)
    mine = {}
    for p in f.by_type('IfcProduct'):
        if p.Representation is None:
            continue
        mine[p.GlobalId] = (p.is_a(), p.Name, p.id())
    both = set(cen) & set(mine)
    same = sum(1 for g in both if cen[g][0] == mine[g][0] and (cen[g][1] or '') == (mine[g][1] or ''))
    only_c = sorted(set(cen) - set(mine))
    only_i = sorted(set(mine) - set(cen), key=lambda g: mine[g][2])
    unmapped = []
    for g in only_i[:200]:
        cls, name, eid = mine[g]
        cands = [c for c in only_c if cen[c][0] == cls and (cen[c][1] or '') == (name or '')]
        unmapped.append({'entity': eid, 'class': cls, 'name': name, 'gid_in_ifc': g, 'census_candidates': cands[:5],
                         'unambiguous': len(cands) == 1})
    return {'available': True, 'census_products': len(cen), 'ifc_products_with_body': len(mine), 'common_gids': len(both),
            'common_same_class_and_name': same, 'only_census': len(only_c), 'only_ifc': len(only_i),
            'all_match': len(both) == len(cen) == len(mine) == same, 'ifc_products_not_in_census': unmapped}


def cmp_summary(c):
    keep = ('entities_a', 'entities_b', 'lines', 'products', 'diff_lines', 'identical_modulo_ids', 'ids_identical', 'samples', 'error')
    return {k: c.get(k) for k in keep if k in c}


def kit_plan(stamp, writer, codes):
    """-> (ordered kits to try, reason) | ([], refusal reason)"""
    if writer != STEP_WRITER:
        return [], f'kit_lost: shipped STEP written by {writer!r}; only {STEP_WRITER} (codes u, v) is packaged (code q = 6.1.5 is not)'
    if not stamp:
        return [], 'kit_lost: shipped STEP has no FILE_NAME time stamp'
    bad = [c for c in codes if c and c not in KIT_CODE.values()]
    if stamp >= V_DEPLOY:
        return ['kit_v', 'kit_u'], f'STEP written {stamp} >= code v deploy {V_DEPLOY} -> kit_v (kit_u tried if v does not reproduce)'
    if stamp >= U_EVIDENCED_FROM:
        return ['kit_u', 'kit_v'], f'STEP written {stamp} before the code v deploy -> kit_u (kit_v tried if u does not reproduce)'
    if bad:
        return [], f'kit_lost: STEP written {stamp} (before any evidenced u/v kit) and converter code {bad}'
    return ['kit_u', 'kit_v'], f'STEP written {stamp}, before {U_EVIDENCED_FROM}: no kit pinned by time; reproduction decides'


def profile_env(prof):
    env = dict(os.environ, V6_FAR_VERIFY='0', PYTHONHASHSEED='0')
    for k in [k for k in env if k.startswith(('DB1_', 'V6_', 'OPENBLAS_', 'NPY_', 'GOTO', 'OMP_', 'MKL_'))]:
        if k != 'V6_FAR_VERIFY':
            env.pop(k)
    env.update(PROFILES[prof]['env'])
    return env


def attempt(kit, prof, mid, job, db1, shipped, wd, log, stamp, run_info):
    """one regeneration with one kit under one CPU numeric profile -> dict (verdict reproduced | mismatch | fail, ...).
    Mirrors regen.py main()."""
    kd = os.path.join(KITS, kit)
    kw = os.path.join(wd, f'{kit}.{prof}')
    shutil.rmtree(kw, ignore_errors=True)
    for s in ('tmp', 'regen', 'restored'):
        os.makedirs(os.path.join(kw, s))
    kj = json.load(open(os.path.join(kd, 'KIT.json')))
    bad = {fn: m for fn, m in kj['files'].items() if md5(os.path.join(kd, fn)) != m}
    res = {'kit': kit, 'profile': prof, 'code': kj['code'], 'kit_manifest': kj['manifest'],
           'kit_snapshot_as_of': kj['snapshot_as_of'], 'kit_files_md5': kj['files']}
    rt = run_info.setdefault(f'{kit}.{prof}', {})
    t_att = time.time()
    if bad:
        return dict(res, verdict='fail', reason=f'kit files differ from the manifest: {sorted(bad)}')
    if CONVERSION_OVERLAY_MD5:
        km = kj['files'].get('tekla_profiles_overlay.json')
        res['catalog_overlay_check'] = {'kit_md5': km, 'conversion_md5': CONVERSION_OVERLAY_MD5,
                                        'equal': km == CONVERSION_OVERLAY_MD5}
    LAYOUTS = json.load(open(os.path.join(kd, 'layouts.json')))
    eng = engine_of(db1)
    res['engine'] = eng
    if not (LAYOUTS.get(eng) or {}).get('approved'):
        return dict(res, verdict='fail', reason=f'unapproved_engine {eng}')
    lp = os.path.join(kw, 'layout.json')
    json.dump(LAYOUTS[eng].get('layout'), open(lp, 'w'))
    vp = os.path.join(kw, 'variants.json')
    json.dump([v['layout'] for v in LAYOUTS.values() if v.get('layout')], open(vp, 'w'))
    tmp = os.path.join(kw, 'tmp')
    env = dict(profile_env(prof), TMPDIR=tmp, TMP=tmp, TEMP=tmp)
    res['_env'] = env
    # the decoder names the IfcProject after the input file: keep production's 'in.db1'
    indb = os.path.join(kw, 'in.db1')
    os.link(db1, indb) if not os.path.exists(indb) else None
    ifc = os.path.join(kw, 'regen', 'model.ifc')
    stats = os.path.join(kw, 'convert.json')
    cmd = [PY84, os.path.join(kd, 'convert_one.py'), indb, ifc, os.path.join(kd, 'tekla_profiles.json'), lp, stats, vp]
    rc, sec = run(cmd, log, DEC_TIMEOUT, env, kw)
    cs = json.load(open(stats)) if os.path.exists(stats) else {}
    if rc == 0 and cs.get('status') == 'deferred_layout':
        res['full_discovery'] = True
        rc, sec2 = run(cmd, log, DEC_TIMEOUT, dict(env, DB1_FULL_DISCOVERY='1'), kw)
        sec += sec2
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
    rt['convert_sec'] = sec
    res['convert'] = {'rc': rc, 'status': cs.get('status'), 'written': cs.get('written'), 'sources': cs.get('sources'),
                      'skipped': cs.get('skipped'), 'members': cs.get('members')}
    res['_stats_path'] = stats
    res['_kw'] = kw
    res['_layout'] = lp
    res['_variants'] = vp
    res['_indb'] = indb
    res['full_discovery'] = bool(res.get('full_discovery'))
    if rc != 0 or cs.get('status') != 'ok':
        return dict(res, verdict='fail', reason='convert_' + str(cs.get('status') or rc), trace=str(cs.get('trace'))[-1500:])
    stp = os.path.join(kw, 'regen', 'model.stp')
    step_cmd = ['--mode', 'hybrid', '--prec', '2', '--threads', '4']
    rc, sec = run([PY84, os.path.join(kd, 'ifc2step6.py'), ifc, stp] + step_cmd, log, STEP_TIMEOUT, env, kw)
    rt['regen_step_sec'] = sec
    res['regen_step'] = {'rc': rc, 'bytes': os.path.getsize(stp) if os.path.exists(stp) else None}
    res['_debug'] = [stp + '.stats.json', stp + '.parts.json', stp]
    if rc != 0 or not os.path.exists(stp):
        return dict(res, verdict='fail', reason=f'step_rc_{rc}' + (' (the conversion worker would have entered its crash rescue; '
                                                                  'not replicated in v1)' if rc in (-11, 139, -6, 134, 124, 125) else ''))
    gm = os.path.join(kw, 'gmap.json')
    c1 = stepcmp(stp, shipped, gm)
    rt['cmp_regen_vs_shipped_raw'] = c1
    res['cmp_regen_vs_shipped'] = cmp_summary(c1)
    if not c1.get('identical_modulo_ids'):
        return dict(res, verdict='mismatch', reason='regenerated STEP differs from the shipped STEP')
    gmap = json.load(open(gm))
    rifc0 = os.path.join(kw, 'restored', 'model.restored.ifc')
    res['_gid_map_full'] = os.path.join(kw, 'gid_map_full.json')
    res['restore'] = restore(mid, ifc, rifc0, gmap, res['_gid_map_full'])
    if res['restore']['product_guids_restored'] != len(gmap) or res['restore']['map_entries_not_found_in_ifc']:
        return dict(res, verdict='mismatch', reason='GlobalId map does not cover the IFC products one to one')
    rifc = os.path.join(kw, 'restored', 'model.ifc')
    res['time_normalisation'] = normalise_times(rifc0, rifc, stamp)
    os.remove(rifc0)
    if res['time_normalisation']['file_name_lines'] != 1 or res['time_normalisation']['owner_history_lines'] < 1:
        return dict(res, verdict='fail', reason='IFC header / owner history time not found for normalisation')
    rstp = os.path.join(kw, 'restored', 'model.stp')
    rc, sec = run([PY84, os.path.join(kd, 'ifc2step6.py'), rifc, rstp] + step_cmd, log, STEP_TIMEOUT, env, kw)
    rt['restored_step_sec'] = sec
    res['restored_step'] = {'rc': rc, 'bytes': os.path.getsize(rstp) if os.path.exists(rstp) else None}
    if rc != 0 or not os.path.exists(rstp):
        return dict(res, verdict='fail', reason=f'restored_step_rc_{rc}')
    c2 = stepcmp(rstp, shipped)
    rt['cmp_restored_vs_shipped_raw'] = c2
    res['cmp_restored_vs_shipped'] = cmp_summary(c2)
    if not (c2.get('identical_modulo_ids') and c2.get('ids_identical')):
        return dict(res, verdict='mismatch', reason='restored IFC -> STEP differs from the shipped STEP')
    res['census_check'] = census_check(rifc, job['files'].get('census'))
    res['_ifc_path'] = rifc
    rt['attempt_sec'] = round(time.time() - t_att, 1)
    return dict(res, verdict='reproduced')


def run_facts(mid, job, a, shipped, out, log, run_info, reproduced):
    """db1_facts.py with the attempt's kit / layout / variants -> OUT/source/skipped_records.json; summary for provenance"""
    path = os.path.join(out, 'source', 'skipped_records.json')
    cfg = {'kit_dir': os.path.join(KITS, a['kit']), 'kit': a['kit'], 'code': a.get('code'), 'model_id': mid, 'engine': a.get('engine'),
           'db1': a['_indb'], 'layout': a['_layout'], 'variants': a['_variants'], 'full_discovery': bool(a.get('full_discovery')),
           'repro_parts': (a['_stats_path'] + '.parts.json.gz') if reproduced else None,
           'gid_map': a.get('_gid_map_full') if reproduced else None, 'shipped_step': shipped,
           'fleet_decoded_parts': job['files'].get('decoded_parts'), 'out': path}
    cf = os.path.join(a['_kw'], 'facts.json')
    json.dump(cfg, open(cf, 'w'))
    tmp = os.path.join(a['_kw'], 'tmp')
    os.makedirs(tmp, exist_ok=True)
    env = dict(profile_env(a['profile']), TMPDIR=tmp, TMP=tmp, TEMP=tmp)
    rc, sec = run([PY84, os.path.join(HERE, 'db1_facts.py'), cf], log, DEC_TIMEOUT, env, a['_kw'])
    run_info['facts_sec'] = sec
    if rc != 0 or not os.path.exists(path):
        return {'status': 'failed', 'reason': f'db1_facts.py rc {rc}', 'usable_for_red_parts': False}
    r = json.load(open(path))
    return {'path': 'source/skipped_records.json', 'sha256': sha256(path), 'bytes': os.path.getsize(path), 'schema': r.get('schema'),
            'status': r.get('status'), 'usable_for_red_parts': r.get('usable_for_red_parts'), 'decoder_path': r.get('decoder_path'),
            'proof': r.get('proof'), 'counts': r.get('counts'), 'error': r.get('error'),
            'kit': a['kit'], 'profile': a['profile'], 'from_reproducing_attempt': bool(reproduced)}


def main():
    jobf, wd, out = sys.argv[1], sys.argv[2], sys.argv[3]
    t0 = time.time()
    job = json.load(open(jobf))
    mid = job['model_id']
    os.makedirs(wd, exist_ok=True)
    os.makedirs(os.path.join(out, 'source'), exist_ok=True)
    os.makedirs(os.path.join(out, 'logs'), exist_ok=True)
    log = os.path.join(wd, 'src_db1.log')
    run_info = {'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    prov = {'stage': 'src_db1', 'model_id': mid, 'pid': job.get('pid'), 'step_relpath': job.get('step_relpath'),
            'source_kind': 'regenerated_from_db1',
            'note': 'IFC regenerated by our own Tekla DB1 decoder with the kit that produced the shipped STEP and proven to '
                    'reproduce it; checks of the pipeline against this IFC are consistency checks, not an independent reference',
            'inputs': {k: {'key': (job.get('keys') or {}).get(k)} for k in ('db1', 'step', 'census', 'result', 'decoded_parts')},
            'env': {'decoder_and_step': 'venv /opt/conv/ifc84: ifcopenshell 0.8.4.post1, numpy 2.4.6 (python 3.11.17 from the conda env)',
                    'step_verifier_and_tools': 'conda env /opt/conv/env: pythonocc-core 8.0.1 (OCC 8.0.1), ifcopenshell 0.9.0, numpy 2.4.6',
                    'locks': 'src_db1/env/conda_env.lock.txt + ifc84.requirements.txt (= the bench envs of the 171/171 regeneration)',
                    'decoder_cmd': 'convert_one.py in.db1 model.ifc tekla_profiles.json layout.json convert.json variants.json',
                    'step_cmd': 'ifc2step6.py model.ifc model.stp --mode hybrid --prec 2 --threads 4',
                    'env_vars': 'DB1_* / V6_* / OPENBLAS_* / NPY_* / OMP_* / MKL_* cleared, V6_FAR_VERIFY=0 (worker.py '
                                'default), PYTHONHASHSEED=0, + the CPU numeric profile of the attempt (cpu_profile)',
                    'host_requirement': 'x86-64 with AVX-512 (F, CD, BW, DQ, VL); the kernels are pinned per profile, so '
                                        'any such host gives the same bytes'}}
    rpath = os.path.join(out, 'source', 'provenance.json')
    ifc_out = os.path.join(out, 'source', 'model.ifc')

    def finish(verdict, reason=None, attempts=(), best=None):
        prov['verdict'] = verdict
        if reason:
            prov['reason'] = reason
        # deterministic summary only: STEP byte sizes vary with ifc2step6's thread-order #numbering (logs keep them)
        prov['attempts'] = [{k: ({'rc': v.get('rc')} if k in ('regen_step', 'restored_step') and isinstance(v, dict) else v)
                             for k, v in a.items() if not k.startswith('_') and k not in ('kit_files_md5', 'census_check',
                             'restore', 'time_normalisation', 'cmp_regen_vs_shipped', 'cmp_restored_vs_shipped')}
                            for a in attempts]
        run_info['attempts_full'] = [{k: v for k, v in a.items() if not k.startswith('_') and k != 'kit_files_md5'} for a in attempts]
        if best is not None:
            prov['kit'] = {'dir': best['kit'], 'code': best['code'], 'manifest': best['kit_manifest'],
                           'snapshot_as_of': best['kit_snapshot_as_of'], 'files_md5': best['kit_files_md5'],
                           's3_prefix': 's3://annotationprod/cad-disk-extract/_control/z3conv/db1/ (object version history)'}
            prov['engine'] = best.get('engine')
            prov['cpu_profile'] = {'name': best['profile'], 'env': PROFILES[best['profile']]['env'],
                                   'means': PROFILES[best['profile']]['means'],
                                   'why': 'the numeric kernels (OpenBLAS core, numpy SIMD dispatch) the conversion host used '
                                          'are part of what is reproduced; this profile is the one whose regenerated STEP '
                                          'equals the shipped STEP'}
            prov['convert'] = best.get('convert')
            prov['proof'] = {'regenerated_vs_shipped': best.get('cmp_regen_vs_shipped'),
                             'restored_vs_shipped': best.get('cmp_restored_vs_shipped'),
                             'method': 'stepcmp.py: every STEP line byte-equal after replacing each #n by the line number that '
                                       'defines it (ifc2step6 numbers entities in thread-completion order); FILE_NAME (write '
                                       'time) not compared; restored_vs_shipped also requires every PRODUCT.id to be equal'}
            prov['guids'] = dict(best.get('restore') or {}, derived_rule='GlobalId of IfcRoot entities with no STEP product '
                                 '(IfcProject, IfcSite, relationships, parts the STEP stage dropped) = ifcopenshell.guid.compress('
                                 'sha256("<model id>:<entity id>")[:32]) - not recoverable from the STEP')
            prov['time_normalisation'] = dict(best.get('time_normalisation') or {}, rule='IFC FILE_NAME time_stamp and '
                                              'IfcOwnerHistory.CreationDate = the shipped STEP FILE_NAME time (original conversion '
                                              'STEP write time; the original IFC was never shipped, its own write time is unknown)')
            prov['census'] = best.get('census_check')
        if verdict == 'reproduced':
            shutil.copyfile(best['_ifc_path'], ifc_out + '.tmp')
            os.replace(ifc_out + '.tmp', ifc_out)
            prov['ifc'] = {'path': 'source/model.ifc', 'bytes': os.path.getsize(ifc_out), 'sha256': sha256(ifc_out)}
        elif os.path.exists(ifc_out):
            os.remove(ifc_out)        # never leave an IFC from an earlier run next to a failed verdict
        json.dump(prov, open(rpath + '.tmp', 'w'), indent=1, sort_keys=True)
        os.replace(rpath + '.tmp', rpath)
        # logs (not deterministic: wall times, run paths)
        for a in attempts:
            sp = a.get('_stats_path')
            if a is best or (best is None and sp):
                if sp and os.path.exists(sp):
                    shutil.copyfile(sp, os.path.join(out, 'logs', 'db1_decoder_stats.json'))
                if sp and os.path.exists(sp + '.parts.json.gz'):
                    shutil.copyfile(sp + '.parts.json.gz', os.path.join(out, 'logs', 'db1_decoded_parts.json.gz'))
        if os.path.exists(log):
            shutil.copyfile(log, os.path.join(out, 'logs', 'src_db1.log'))
        # diagnosis material per attempt (logs only): the STEP stage's stats + per-part sidecar; the regenerated STEP
        # itself (gzip) when the attempt did not reproduce and it is small
        import gzip as _gz
        for a in attempts:
            for p in a.get('_debug') or []:
                if not os.path.exists(p):
                    continue
                dst = os.path.join(out, 'logs', f"{a['kit']}.{a.get('profile')}_regen_" + os.path.basename(p))
                if p.endswith('.stp'):
                    if a['verdict'] == 'reproduced' or os.path.getsize(p) > 200 << 20:
                        continue
                    with open(p, 'rb') as fi, _gz.open(dst + '.gz', 'wb', compresslevel=6) as fo:
                        shutil.copyfileobj(fi, fo)
                else:
                    shutil.copyfile(p, dst)
        run_info.update(finished=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), seconds=round(time.time() - t0, 1))
        json.dump(run_info, open(os.path.join(out, 'logs', 'src_db1_run.json'), 'w'), indent=1, default=str)
        r = {'model_id': mid, 'stage': 'src_db1', 'verdict': verdict, 'reason': reason, 'kit': best['kit'] if best else None,
             'profile': best['profile'] if best else None, 'ifc': prov.get('ifc'), 'seconds': run_info['seconds'],
             'attempts': [(a['kit'], a.get('profile'), a['verdict']) for a in attempts]}
        print(json.dumps(r), flush=True)
        sys.exit(0)

    db1 = job['files']['db1']
    shipped = job['files']['step']
    prov['inputs']['db1'].update(sha256=sha256(db1), bytes=os.path.getsize(db1))
    prov['inputs']['step'].update(sha256=sha256(shipped), bytes=os.path.getsize(shipped))
    for k in ('census', 'result', 'decoded_parts'):
        p = job['files'].get(k)
        if p and os.path.exists(p):
            prov['inputs'][k].update(sha256=sha256(p), bytes=os.path.getsize(p))
    if prov['inputs']['db1']['sha256'] != mid:
        finish('fail', 'db1_sha256_is_not_the_model_id')
    if job.get('step_bytes') and prov['inputs']['step']['bytes'] != job['step_bytes']:
        finish('fail', f"shipped STEP is {prov['inputs']['step']['bytes']} bytes, the manifest says {job['step_bytes']}")
    stamp, writer, fnline = step_file_name(shipped)
    prov['shipped_step_file_name'] = fnline
    result = {}
    if job['files'].get('result') and os.path.exists(job['files']['result']):
        result = json.load(open(job['files']['result']))
        prov['conversion_result'] = {k: result.get(k) for k in ('code', 'runtime', 'started', 'engine', 'status', 'out_key')}
        if result.get('id') not in (None, mid):
            finish('fail', 'conversion result JSON belongs to another model')
        global CONVERSION_OVERLAY_MD5
        CONVERSION_OVERLAY_MD5 = (result.get('catalog_overlay') or {}).get('md5')
        fb = [k for k in RESULT_STEP_FALLBACKS if result.get(k)]
        if fb:
            finish('refused', f'the conversion worker produced this STEP through its crash rescue ({fb}): not replicated in v1')
    kits, why = kit_plan(stamp, writer, [job.get('converter_code'), result.get('code')])
    prov['kit_selection'] = why
    if not kits:
        finish('refused', why)
    host = cpu_facts.facts(PY84, profile_env(PROFILE_ORDER[0]))
    run_info['host_cpu'] = host
    if not host.get('avx512'):
        finish('host_unsuitable', f"host CPU {host.get('vendor')} family {host.get('family')} model {host.get('model')} has no "
                                  f"AVX-512: the x86-64-v4 profile cannot run here (retry on another container)")
    plan = [(k, p) for k in kits for p in PROFILE_ORDER]
    prov['attempt_plan'] = [f'{k}/{p}' for k, p in plan]
    deadline = job.get('deadline')
    attempts = []
    longest = 0.0
    for kit, prof in plan:
        if deadline and attempts and time.time() + 1.5 * longest > deadline:
            prov['attempts_not_run'] = {'reason': 'stage deadline: no time for another attempt',
                                        'not_run': [f'{k}/{p}' for k, p in plan[len(attempts):]]}
            break
        t_a = time.time()
        a = attempt(kit, prof, mid, job, db1, shipped, wd, log, stamp, run_info)
        longest = max(longest, time.time() - t_a)
        attempts.append(a)
        if a['verdict'] == 'reproduced':
            if len(attempts) > 1:
                prov['kit_selection'] += (f'; reproduced by {kit}/{prof} after ' +
                                          ', '.join(f"{x['kit']}/{x['profile']} ({x['verdict']})" for x in attempts[:-1]))
            prov['skipped_records'] = run_facts(mid, job, a, shipped, out, log, run_info, True)
            finish('reproduced', None, attempts, a)
    # nothing reproduced: report the first (pinned) kit's outcome, both attempts listed. The decoder facts are still
    # exported from the pinned kit when its engine layout was approved; they are usable only when the decode equals the
    # conversion fleet's own decoded parts list (checked inside db1_facts.py)
    first = attempts[0]
    if first.get('_layout'):
        prov['skipped_records'] = run_facts(mid, job, first, shipped, out, log, run_info, False)
    finish(first['verdict'] if first['verdict'] in ('mismatch', 'fail') else 'fail',
           '; '.join(f"{a['kit']}/{a['profile']}: {a['verdict']} ({a.get('reason')})" for a in attempts), attempts, None)


if __name__ == '__main__':
    main()
