"""package stage: the scripts/ tree of one model exactly as it is published into its package, its scripts_manifest rows,
the deterministic tar.gz bundle, and the bundle upload through a pre-signed PUT URL.

Layout (package root = dataset/packages/3d_partial/<pid>/):

  scripts/README.md               shared  app/templates/scripts_README.md (identical for every model and package)
  scripts/requirements.txt        shared  app/templates/requirements.txt (pinned)
  scripts/steelbuild.py           shared  code/<variant>/kit/steelbuild.py
  scripts/issues_lib.py           shared  issues/issues_lib.py
  scripts/scripts_manifest.jsonl  written by the publisher (rows of every bundle merged into the package)
  scripts/<model_folder>/
    build_model.py                code/<variant>/kit/build_model.py
    build_issues_model.py         issues/build_issues_model.py
    model_info.json               ids, verdict, source, counts, fingerprint, partial record, issues summary, files
    schedules/                    the pipeline's schedules + views (+ issues.json, missing_parts.json from the issue maker)
    verification/                 verification.csv + summaries + e2e results (+ issues_e2e.json: the issues script's own runs)
    issues/                       <model>_ISSUES_highlighted.step, <model>_MISSING_parts_only.step (written by
                                  build_issues_model.py run from this tree), WHERE_TO_LOOK.md (issue maker)
    source/                       provenance.json (+ the regenerated / emitted IFC of a DB1 / SDS/2 model)

Bundle = publish/bundle_lib.py's "pmp-bundle/1" (the contract shared with the publisher): bundle.json +
scripts_manifest_rows.jsonl (one row per file: path, bytes, sha256, model_id, source, code_version) + the scripts/ files
above; deterministic (sorted, mtime 0, uid/gid 0, mode 0644, gzip mtime 0). scripts/scripts_manifest.jsonl is not in a
bundle: the publisher regenerates it from the merged package tree.
"""
import collections, csv, hashlib, json, os, re, shutil, time

from . import common as C

csv.field_size_limit(10 ** 9)

SHARED = ('README.md', 'requirements.txt', 'steelbuild.py', 'issues_lib.py')
# the schedules the build reads (steelbuild.Schedules), in this order for the fingerprint (stagelib.BUILD_FILES)
BUILD_FILES = ['parts.csv', 'profiles.csv', 'profile_outlines.json', 'solids.csv', 'cuts.csv', 'cut_boundaries.json',
               'openings.csv', 'paths.json', 'exact_geometry.jsonl']
BUILD_REQUIRED = [f for f in BUILD_FILES if f != 'paths.json']
VIEW_FILES = ['members.csv', 'plates.csv', 'bolts.csv', 'welds.csv', 'assemblies.csv']
SCHED = BUILD_FILES + ['part_properties.jsonl'] + VIEW_FILES + ['exact_sources.csv']
VERIF_FILES = ('verification.csv', 'verification_summary.json', 'assemblies_verification.csv', 'assembly_marks_verification.csv',
               'piece_marks_verification.csv', 'levels_summary.json', 'e2e_results.csv', 'e2e_summary.json', 'tekla_summary.json',
               'tekla_parts.csv', 'tekla_assemblies.csv', 'reference_defects.csv', 'reference_defects_summary.json',
               'source_kernel_log.jsonl', 'pmx_summary.json', 'step_times.tsv')
FILE_STEP = {'verification.csv': 'verify', 'verification_summary.json': 'verify', 'source_kernel_log.jsonl': 'verify',
             'assemblies_verification.csv': 'verify_levels', 'assembly_marks_verification.csv': 'verify_levels',
             'piece_marks_verification.csv': 'verify_levels', 'levels_summary.json': 'verify_levels',
             'e2e_results.csv': 'e2e', 'e2e_summary.json': 'e2e', 'tekla_summary.json': 'tekla_checks', 'tekla_parts.csv': 'tekla_checks',
             'tekla_assemblies.csv': 'tekla_checks', 'reference_defects.csv': 'reference_defects',
             'reference_defects_summary.json': 'reference_defects'}
MAKER_REQUIRED = ('schedules/issues.json', 'schedules/missing_parts.json', 'issues/WHERE_TO_LOOK.md')
SOURCE_SHIP = {'regenerated_from_db1': True, 'emitted_from_sds2': True, 'package_ifc': False}


class PackageError(RuntimeError):
    pass


def _rows(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def fingerprint(sdir):
    """schedule fingerprint (stagelib.fingerprint): sha256 of the `sha256sum` listing of the build's schedule files that
    exist, in BUILD_FILES order (reproduce: cd schedules && sha256sum <files> | sha256sum); + parts.csv rows sorted"""
    lines, files = [], {}
    for f in BUILD_FILES:
        p = os.path.join(sdir, f)
        if os.path.exists(p):
            files[f] = C.file_sha256(p)
            lines.append(f'{files[f]}  {f}\n')
    fp = hashlib.sha256(''.join(lines).encode()).hexdigest()
    raw = open(os.path.join(sdir, 'parts.csv'), 'rb').read().splitlines()
    srt = hashlib.sha256(b'\n'.join(raw[:1] + sorted(x for x in raw[1:] if x.strip())) + b'\n').hexdigest()
    return dict(schedules_sha256=fp, files=files, files_in_fingerprint=[f for f in BUILD_FILES if f in files], parts_sorted_sha256=srt)


def code_versions(job, issues_dir):
    """the code version strings recorded in model_info.json and every manifest row"""
    code_dir = os.path.join(C.CODE_ROOT, job['code_version'])
    md5 = hashlib.sha256(open(os.path.join(code_dir, 'MD5SUMS'), 'rb').read()).hexdigest()[:12]
    h = hashlib.sha256()
    for f in sorted(os.listdir(issues_dir)) if os.path.isdir(issues_dir) else []:
        p = os.path.join(issues_dir, f)
        if os.path.isfile(p) and f.endswith('.py'):
            h.update(f.encode() + b'\0' + C.file_sha256(p).encode() + b'\n')
    return {'app': C.PMP_APP_VERSION, 'pipeline': f'{job["code_version"]}@{md5}', 'issues': f'issues@{h.hexdigest()[:12]}',
            'string': f'{C.PMP_APP_VERSION}; pipeline {job["code_version"]}@{md5}; issues@{h.hexdigest()[:12]}'}


def count_missing(missing_json):
    """number of parts a missing_parts.json lists (a list, or a dict holding the list under parts / missing / items)"""
    d = C.read_json(missing_json)
    if isinstance(d, list):
        return len(d)
    if isinstance(d, dict):
        for k in ('parts', 'missing', 'missing_parts', 'items'):
            if isinstance(d.get(k), list):
                return len(d[k])
        if isinstance(d.get('count'), int):
            return d['count']
    return None


# ------------------------------------------------------------------------------------------------------- assemble
def assemble(job, T, pipeline_out, source_dir, maker_out, pipe_summary, e2e_inputs, log, issues_code='/pmp/issues',
             issues_counts=None):
    """build the package-shaped tree T/scripts/... (everything except the issues STEP files, which the shipped
    build_issues_model.py writes when it is run from this tree). Returns {'model_dir', 'files': {relpath: source},
    'checks': {...}}. Raises PackageError on any contradiction (never ships a half tree)."""
    mf = job['model_folder']
    S = os.path.join(T, 'scripts')
    M = os.path.join(S, mf)
    shutil.rmtree(S, ignore_errors=True)
    for d in ('schedules', 'verification', 'issues', 'source'):
        os.makedirs(os.path.join(M, d))
    code_dir = os.path.join(C.CODE_ROOT, job['code_version'])
    cv = code_versions(job, issues_code)
    prov = {}

    def put(src, rel, why):
        dst = os.path.join(S, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        prov[rel] = why

    # shared files
    for f, src, why in (('README.md', os.path.join(C.TEMPLATES, 'scripts_README.md'), f'app {C.PMP_APP_VERSION}: templates/scripts_README.md'),
                        ('requirements.txt', os.path.join(C.TEMPLATES, 'requirements.txt'), f'app {C.PMP_APP_VERSION}: templates/requirements.txt'),
                        ('steelbuild.py', os.path.join(code_dir, 'kit', 'steelbuild.py'), f'code {cv["pipeline"]}: kit/steelbuild.py'),
                        ('issues_lib.py', os.path.join(issues_code, 'issues_lib.py'), f'{cv["issues"]}: issues/issues_lib.py')):
        if not os.path.isfile(src):
            raise PackageError(f'shared file source missing: {src}')
        put(src, f, why)
    # the model's scripts
    put(os.path.join(code_dir, 'kit', 'build_model.py'), f'{mf}/build_model.py', f'code {cv["pipeline"]}: kit/build_model.py')
    bim = os.path.join(issues_code, 'build_issues_model.py')
    if not os.path.isfile(bim):
        raise PackageError(f'{bim} missing (issues component)')
    put(bim, f'{mf}/build_issues_model.py', f'{cv["issues"]}: issues/build_issues_model.py')
    # schedules + verification from the pipeline's flat out folder
    lack = [f for f in BUILD_REQUIRED + ['verification.csv', 'verification_summary.json'] if not os.path.exists(os.path.join(pipeline_out, f))]
    if lack:
        raise PackageError(f'pipeline out lacks {lack} (steps {pipe_summary.get("steps")})')
    for f in SCHED:
        if os.path.exists(os.path.join(pipeline_out, f)):
            put(os.path.join(pipeline_out, f), f'{mf}/schedules/{f}', f'pipeline {cv["pipeline"]}: out/{f}')
    for f in VERIF_FILES:
        if os.path.exists(os.path.join(pipeline_out, f)):
            put(os.path.join(pipeline_out, f), f'{mf}/verification/{f}', f'pipeline {cv["pipeline"]}: out/{f}')
    # the issue maker's outputs (model-folder relative); ref/ is a reference only, never shipped
    lack = [f for f in MAKER_REQUIRED if not os.path.isfile(os.path.join(maker_out, f))]
    if lack:
        raise PackageError(f'issue maker did not write {lack}')
    for dp, _, fs in os.walk(maker_out):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, maker_out)
            if rel.split(os.sep)[0] == 'ref':
                continue
            if rel.split(os.sep)[0] not in ('schedules', 'issues', 'verification', 'source'):
                raise PackageError(f'issue maker wrote {rel} outside schedules/ issues/ verification/ source/')
            if rel.startswith('schedules' + os.sep) and f in SCHED:
                raise PackageError(f'issue maker would overwrite the pipeline schedule {rel}')
            put(p, f'{mf}/{rel}', f'{cv["issues"]}: make_issues -> {rel}')
    # source
    if not os.path.isfile(os.path.join(source_dir, 'provenance.json')):
        raise PackageError('source/provenance.json missing')
    put(os.path.join(source_dir, 'provenance.json'), f'{mf}/source/provenance.json', f'source stage ({job["source_kind"]})')
    if SOURCE_SHIP[job['source_kind']]:
        ifc = job.get('ifc')
        p = os.path.join(source_dir, os.path.basename(ifc or ''))
        if not ifc or not os.path.isfile(p):
            raise PackageError(f'source IFC {ifc!r} not in the source stage output')
        put(p, f'{mf}/source/{os.path.basename(ifc)}', f'source stage ({job["source_kind"]}): regenerated/emitted IFC')
    # the shipped build inputs are byte for byte what the pipeline's e2e step ran
    e2e_map = {'steelbuild.py': 'steelbuild.py', 'model/build_model.py': f'{mf}/build_model.py',
               'model/verification.csv': f'{mf}/verification/verification.csv'}
    same, differ = 0, []
    for rel, h in sorted(((e2e_inputs or {}).get('files') or {}).items()):
        tgt = e2e_map.get(rel) or (f'{mf}/schedules/{rel[len("model/schedules/"):]}' if rel.startswith('model/schedules/') else None)
        if tgt is None or not os.path.exists(os.path.join(S, tgt)) or C.file_sha256(os.path.join(S, tgt)) != h:
            differ.append(rel)
        else:
            same += 1
    if not e2e_inputs or not e2e_inputs.get('files'):
        e2e_check = {'ok': False, 'note': 'the pipeline e2e step did not run (no e2e inputs recorded)'}
    else:
        e2e_check = {'ok': not differ, 'files_equal': same, 'differ': differ}
        if differ:
            raise PackageError(f'shipped build inputs differ from what e2e tested: {differ[:5]}')
    # model_info.json (written BEFORE the scripts run: a script may read it)
    info = model_info(job, M, pipeline_out, source_dir, pipe_summary, cv, e2e_check, issues_counts)
    C.write_json(os.path.join(M, 'model_info.json'), info)
    prov[f'{mf}/model_info.json'] = f'app {C.PMP_APP_VERSION}: model_info'
    log(f'assembled scripts/{mf}: {len(prov)} files')
    return {'model_dir': M, 'prov': prov, 'code_versions': cv, 'e2e_inputs_check': e2e_check}


def model_info(job, M, pipeline_out, source_dir, summ, cv, e2e_check, issues_counts):
    sd = os.path.join(M, 'schedules')
    parts = _rows(os.path.join(sd, 'parts.csv'))
    ext = C.read_json(os.path.join(pipeline_out, 'extract_info.json'), {}) or {}
    ver = C.read_json(os.path.join(pipeline_out, 'verification_summary.json'), {}) or {}
    prov = C.read_json(os.path.join(source_dir, 'provenance.json'), {}) or {}
    steps = summ.get('steps') or {}
    absent = {f: dict(step=FILE_STEP[f], step_exit_code=steps.get(FILE_STEP[f])) for f in FILE_STEP
              if not os.path.exists(os.path.join(pipeline_out, f))}
    mf = job['model_folder']
    return dict(
        model=mf, model_id=job['id'], package=job['pid'],
        package_location=f'dataset/packages/3d_partial/{job["pid"]}/ (model/... and scripts/... paths are relative to it)',
        delivered_step=job['step'], delivered_step_bytes=job['bytes'], delivered_step_sha256=job.get('step_sha256'),
        partial=job.get('partial'), converter=job.get('converter'),
        source=dict(kind=job['source_kind'], ifc=job.get('ifc'), converted_from=job.get('converted_from'),
                    converted_from_package=job.get('converted_from_package'),
                    shipped_in=(f'scripts/{mf}/source/' if SOURCE_SHIP[job['source_kind']] else
                                ('the add-on package ' + str(job.get('converted_from_package')) if job.get('converted_from_package')
                                 else 'model/ifc/ of this package')),
                    sha256=prov.get('sha256') or prov.get('ifc_sha256'), verdict=prov.get('verdict'),
                    provenance=f'scripts/{mf}/source/provenance.json',
                    independence=('the package IFC the delivered STEP was converted from' if job['source_kind'] == 'package_ifc' else
                                  'our converter\'s own intermediate IFC (regenerated / emitted with the version that wrote the '
                                  'delivered STEP): the source check against it is a consistency check, not an independent reference')),
        source_schema=ext.get('schema'), authoring_tool=ext.get('originating_system'),
        units=dict(length='mm (source length unit x %g)' % ext.get('length_unit_to_mm', 1.0), coordinates='source model world coordinates'),
        parts=len(parts), parts_by_role=dict(sorted(collections.Counter(p.get('role', '') for p in parts).items())),
        parts_by_geometry=dict(sorted(collections.Counter(p.get('geometry', '') for p in parts).items())),
        verdict=dict(perfect=summ.get('perfect'), reasons=summ.get('reasons'), steps=steps, code=summ.get('code'), size_class=summ.get('cls'),
                     definition='job.py verdict: every step exit code 0, every part match, no delivered part left unbuilt, '
                                'levels_summary.json model.geometry_ok, every end-to-end run ok'),
        checks_absent=absent,
        verification=dict(status=ver.get('status'), source_check=ver.get('source_check'), delivered_check=ver.get('delivered_check'),
                          tolerances=ver.get('tolerances'), source_coverage=ver.get('source_coverage')),
        levels=summ.get('levels'), end_to_end=summ.get('e2e'),
        shipped_build_inputs_equal_e2e_tested=e2e_check,
        fingerprint=fingerprint(sd),
        issues=dict(counts=issues_counts, files=dict(highlighted=f'issues/{mf}_ISSUES_highlighted.step',
                                                     missing_only=f'issues/{mf}_MISSING_parts_only.step (only when a part is missing)',
                                                     where_to_look='issues/WHERE_TO_LOOK.md', machine_readable='schedules/issues.json',
                                                     missing_parts='schedules/missing_parts.json'),
                    script_runs='verification/issues_e2e.json'),
        code=cv,
        run=dict(model='python build_model.py', issues='python build_issues_model.py  (or --from-delivered ../../' + job['step'] + ')',
                 readme='../README.md'))


# ------------------------------------------------------------------------------------------------- manifest + bundle
def bundle_lib():
    """the publish contract (publish/bundle_lib.py, shared with the publisher on the EC2 box): /pmp/publish in the
    image, ../publish next to app/ when run locally"""
    import importlib, sys
    for d in ('/pmp/publish', os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'publish')):
        if os.path.isfile(os.path.join(d, 'bundle_lib.py')):
            if d not in sys.path:
                sys.path.insert(0, d)
            return importlib.import_module('bundle_lib')
    raise PackageError('publish/bundle_lib.py (the bundle contract) is not available')


STEP_SOURCE_OF_KIND = {v: k for k, v in C.STEP_SOURCE_TO_KIND.items()}


def make_bundle(job, T, prov, cv, run_name, dest):
    """the bundle (publish/bundle_lib.py contract "pmp-bundle/1": bundle.json + scripts_manifest_rows.jsonl + scripts/...)
    of the tree T/scripts -> dest. bundle_lib verifies it before returning (layout, rows, sha256s); raises on refusal.
    Returns {sha256, bytes, n_files, md5_b64, header, warnings, rows}"""
    BL = bundle_lib()
    S = os.path.join(T, 'scripts')

    def source(rel):
        if rel in prov:
            return prov[rel]
        if rel.startswith(job['model_folder'] + '/issues/') and rel.lower().endswith('.step'):
            return f'{cv["issues"]}: build_issues_model.py run from this scripts/ tree (default mode)'
        if rel == job['model_folder'] + '/verification/issues_e2e.json':
            return f'app {C.PMP_APP_VERSION}: build_issues_model.py end-to-end runs'
        raise PackageError(f'no provenance for scripts/{rel}')

    header = dict(run=run_name, model_id=job['id'], pid=job['pid'], model_folder=job['model_folder'], step_relpath=job['step'],
                  step_source=STEP_SOURCE_OF_KIND[job['source_kind']], code_version=cv['string'], source_kind=job['source_kind'],
                  app_version=C.PMP_APP_VERSION)
    b = BL.make_bundle(S, dest, header, source)
    v = BL.verify_bundle(dest)
    b['rows'] = v.rows
    b['md5_hex'] = hashlib.md5(open(dest, 'rb').read()).hexdigest()
    return b


def upload(path, put_url, md5_hex, log=print):
    """PUT the bundle to its pre-signed URL (bundle_lib.upload_bundle: Content-MD5, retries, 403 not retried). Returns a
    record; never raises, never logs the URL."""
    BL = bundle_lib()
    obj = C.url_object(put_url)
    exp = C.url_expiry(put_url)
    rec = {'object': obj, 'expires': exp, 'ok': False}
    if exp and exp < time.time() + 120:
        rec['error'] = 'put_url_expired (get fresh PUT URLs from the EC2 box: publish/presign_put.py)'
        return rec
    t0 = time.time()
    try:
        r = BL.upload_bundle(path, put_url)
        etag = r.get('etag') or ''
        rec.update(ok=r.get('status') == 200, http=r.get('status'), etag=etag, bytes=r.get('bytes'), sha256=r.get('sha256'),
                   attempts=r.get('attempts'), seconds=round(time.time() - t0, 1),
                   etag_is_md5=bool(re.fullmatch(r'[0-9a-f]{32}', etag)))
        if rec['etag_is_md5'] and etag != md5_hex:
            rec.update(ok=False, error=f'etag {etag} != md5 {md5_hex}')
        log(f'uploaded bundle -> {obj} {rec["bytes"]} B http {rec["http"]} etag {etag[:12]}')
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {str(e)[:400]}'
        log(f'upload failed -> {obj}: {rec["error"]}')
    return rec
