"""complete stage (pmp-completion, complete/INTERFACES.md): the baseline scripts tree of a model + the tracks' work ->
the COMPLETED model, its shipped scripts, its checks and its bundle.

  source_pipeline(job, track, cls, deadline)       Form B: the baseline pipeline (same code variant, same delivered STEP)
                                                    on a track's completed source /vol/<id>/complete_<track>/model_completed.ifc
                                                    -> /vol/<id>/complete_integrate/source_<track>/pipeline/out/ (schedules)
  run(job, cls, deadline, run_name, patches, opts)  baseline tree (/vol/<id>/scripts_tree, or a track-supplied one) +
                                                    Form B patches (from_ifc) + the tracks' patch.json files -> merge ->
                                                    shipped scripts -> verify_completed -> build_completed_coloured (twice:
                                                    determinism; --verify read-back) -> CHANGES.md -> volume + bundle
     outputs: /vol/<id>/complete_integrate/<run>/{scripts/ (the tree), bundle/<id>.tar.gz, bundle_facts.json, result.json}
"""
import hashlib, json, os, re, shutil, subprocess, sys, time

from . import common as C

INTEG = '/pmp/complete/integrate'
PY = sys.executable
TRACKS = ('db1', 'sds2_ifc', 'standards', 'estimate')
FIXED_TIME = '2000-01-01T00:00:00'

HEADER_FIX = '''

def _fixed_header(path, stamp='2000-01-01T00:00:00'):
    """FILE_NAME name + time stamp set to fixed values (the only bytes OpenCASCADE writes differently run to run):
    the same schedules always give a byte-identical STEP"""
    import re
    raw = open(path, 'rb').read()
    i = raw.find(b'DATA;')
    hdr = raw[:i].decode('latin-1')
    m = re.search(r"FILE_NAME\\s*\\(\\s*'(?:[^']|'')*'\\s*,\\s*'[^']*'", hdr)
    if m:
        name = os.path.basename(path).replace("'", "''")
        hdr = hdr[:m.start()] + f"FILE_NAME('{name}','{stamp}'" + hdr[m.end():]
        with open(path + '.part', 'wb') as f:
            f.write(hdr.encode('latin-1'))
            f.write(raw[i:])
        os.replace(path + '.part', path)
'''


def _integ():
    if INTEG not in sys.path:
        sys.path.insert(0, INTEG)
    import completion_core, from_ifc, changes_md      # noqa: F401
    return completion_core, from_ifc, changes_md


def source_pipeline(job, track, cls, deadline):
    from . import pipeline
    ifc = f"{C.VOL}/{job['id']}/complete_{track}/model_completed.ifc"
    if not os.path.exists(ifc):
        return {'ok': False, 'stage': 'complete_source', 'error': f'no completed source for track {track} ({ifc})'}
    r = pipeline.run(job, {'mode': 'volume', 'path': ifc}, cls, deadline,
                     publish_rel=f'complete_integrate/source_{track}/pipeline')
    r['stage'] = 'complete_source'
    r['track'] = track
    return r


def _run(cmd, cwd, logf, timeout=4 * 3600):
    t0 = time.time()
    with open(logf, 'a') as lf:
        lf.write(f'\n$ {" ".join(cmd)}\n')
        lf.flush()
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
        lf.write(p.stdout)
    return p.returncode, p.stdout, round(time.time() - t0, 1)


def _sha(p):
    return C.file_sha256(p) if os.path.exists(p) else None


def ship_scripts(M):
    """the shipped scripts of the completed model folder M"""
    shutil.copy(os.path.join(INTEG, 'shipped', 'build_completed_coloured.py'), os.path.join(M, 'build_completed_coloured.py'))
    bm = os.path.join(M, 'build_model.py')
    s = open(bm).read()
    if '_fixed_header' not in s:
        s = s.replace('\n\ndef _build_chunk(args):', HEADER_FIX + '\n\ndef _build_chunk(args):', 1)
        s = s.replace("    bad = steelbuild.write_step(items, a.out, name=os.path.basename(HERE))\n",
                      "    bad = steelbuild.write_step(items, a.out, name=os.path.basename(HERE))\n    _fixed_header(a.out)\n", 1)
        s = s.replace('"""Rebuild this model from its schedules with build123d.',
                      '"""Rebuild this model from its schedules with build123d: the COMPLETED model (schedules/completion.json says,\n'
                      'per part, what was restored / added and on what basis; schedules_original/ = the original rebuild).', 1)
        assert '_fixed_header(a.out)' in s, 'build_model.py: write_step line not found'
        open(bm, 'w').write(s)
    bi = os.path.join(M, 'build_issues_model.py')
    if os.path.exists(bi):
        s = open(bi).read()
        old = "ap.add_argument('--schedules', default=os.path.join(HERE, 'schedules'))"
        new = ("ap.add_argument('--schedules', default=os.path.join(HERE, 'schedules_original') if os.path.isdir(\n"
               "        os.path.join(HERE, 'schedules_original')) else os.path.join(HERE, 'schedules'))   "
               "# the ORIGINAL rebuild (schedules/ = COMPLETED)")
        if old in s:
            open(bi, 'w').write(s.replace(old, new, 1))


def run(job, cls, deadline, run_name, patches=None, opts=None):
    t_start = time.time()
    opts = opts or {}
    cc, FB, CM = _integ()
    ID, MF, tag = job['id'], job['model_folder'], job.get('tag') or job['id'][:12]
    MD = os.path.join(C.VOL, ID)
    J = max(1, int(opts.get('jobs') or os.cpu_count() or 1))
    W = os.path.join('/tmp/pmpc', ID[:16])
    shutil.rmtree(W, ignore_errors=True)
    S = os.path.join(W, 'scripts')
    os.makedirs(W)
    logf = os.path.join(W, 'complete.log')
    res = {'stage': 'complete', 'tag': tag, 'model_id': ID, 'model_folder': MF, 'run': run_name, 'ok': False, 'J': J}

    def log(m):
        line = time.strftime('%H:%M:%S ') + str(m)
        print(f'[{ID[:12]} complete] {line}', flush=True)
        with open(logf, 'a') as f:
            f.write(line + '\n')
    try:
        # ---- baseline tree
        base = opts.get('baseline_tree') or os.path.join(MD, 'scripts_tree')
        if not os.path.isdir(os.path.join(base, MF, 'schedules')):
            raise RuntimeError(f'no baseline scripts tree with {MF}/schedules at {base}')
        shutil.copytree(base, S)
        M = os.path.join(S, MF)
        for junk in ('completed', 'schedules_original'):
            shutil.rmtree(os.path.join(M, junk), ignore_errors=True)
        # ---- patches: Form B (completed sources run through the pipeline), then the tracks' patch.json
        plist, formb = [], {}
        PD = os.path.join(W, 'patches')
        os.makedirs(PD)
        for tr in TRACKS:
            pout = os.path.join(MD, 'complete_integrate', f'source_{tr}', 'pipeline', 'out')
            rl = os.path.join(MD, f'complete_{tr}', 'restoration_log.json')
            if opts.get('form_b', True) and os.path.exists(os.path.join(pout, 'parts.csv')):
                sc = os.path.join(W, 'formb', tr, 'schedules')
                os.makedirs(sc)
                for f in ('parts.csv', 'profiles.csv', 'profile_outlines.json', 'solids.csv', 'cuts.csv',
                          'cut_boundaries.json', 'openings.csv', 'paths.json', 'exact_geometry.jsonl', 'assemblies.csv'):
                    if os.path.exists(os.path.join(pout, f)):
                        shutil.copy(os.path.join(pout, f), sc)
                lg = json.load(open(rl)) if os.path.exists(rl) else {}
                p = FB.make_patch(os.path.join(M, 'schedules'), sc, lg, tr, tag, ID,
                                  {'db1': 'DB1', 'sds2_ifc': 'SDS/2' if job['source_kind'] == 'emitted_from_sds2' else 'IFC'}
                                  .get(tr, 'source'))
                p['inputs'] = {'model_completed.ifc': _sha(os.path.join(MD, f'complete_{tr}', 'model_completed.ifc')),
                               'restoration_log.json': _sha(rl)}
                fp = os.path.join(PD, f'{tr}.formb.patch.json')
                json.dump(p, open(fp, 'w'), indent=1)
                plist.append((fp, p))
                formb[tr] = p.get('stats')
                log(f'Form B {tr}: {p.get("stats")}')
            if tr in (patches or {}):
                fp = os.path.join(PD, f'{tr}.patch.json')
                json.dump(patches[tr], open(fp, 'w'), indent=1)
                plist.append((fp, patches[tr]))
                log(f'patch {tr}: {len(patches[tr].get("ops") or [])} ops')
        res['form_b'] = formb
        res['patches'] = {os.path.basename(f): len(p.get('ops') or []) for f, p in plist}
        # ---- merge (in place: schedules/ -> COMPLETED, schedules_original/ = baseline)
        comp = cc.merge(M, plist, M, tag, ID, log=log)
        res['merge'] = {'counts': comp['counts'], 'unresolved': len(comp['unresolved']), 'warnings': comp['warnings'][:20],
                        'untouched': comp['untouched']}
        ship_scripts(M)
        # ---- verify (build every part of both schedules) -> MAGENTA folded into completion.json
        rc, out, sec = _run([PY, os.path.join(INTEG, 'verify_completed.py'), '--tree', M, '--jobs', str(J)], W, logf)
        res['verify'] = {'rc': rc, 'seconds': sec, 'tail': out[-1500:]}
        if rc != 0:
            raise RuntimeError(f'verify_completed rc {rc}: {out[-800:]}')
        # ---- the shipped coloured + plain build, twice (determinism), --verify read-back on the first
        rc1, o1, s1 = _run([PY, os.path.join(M, 'build_completed_coloured.py'), '--jobs', str(J), '--verify'], M, logf)
        D = os.path.join(W, 'det')
        os.makedirs(D)
        name = comp['model_name']
        rc2, o2, s2 = _run([PY, os.path.join(M, 'build_completed_coloured.py'), '--jobs', str(J),
                            '--out', os.path.join(D, f'{name}_COMPLETED.step'),
                            '--plain-out', os.path.join(D, f'{name}_COMPLETED_plain.step')], M, logf)
        cd = os.path.join(M, 'completed')
        shas = {k: _sha(os.path.join(cd, f'{name}_COMPLETED{k}.step')) for k in ('', '_plain')}
        shas2 = {k: _sha(os.path.join(D, f'{name}_COMPLETED{k}.step')) for k in ('', '_plain')}
        rb = None
        m = re.search(r'^read back: (\{.*\})$', o1, re.M)
        if m:
            rb = json.loads(m.group(1))
        comp = json.load(open(os.path.join(M, 'schedules', 'completion.json')))
        ver = {'schema': 'pmp-completion-verification/1', 'tag': tag, 'model_id': ID, 'model_name': name,
               'counts': comp['counts'], 'build': comp.get('build'), 'untouched': comp.get('untouched'),
               'runs': {'first': {'rc': rc1, 'seconds': s1, 'tail': o1[-2500:]},
                        'second': {'rc': rc2, 'seconds': s2, 'tail': o2[-1200:]}},
               'determinism': {'coloured_identical': shas[''] is not None and shas[''] == shas2[''],
                               'plain_identical': shas['_plain'] is not None and shas['_plain'] == shas2['_plain'],
                               'sha256': shas},
               'readback': rb,
               'files': {f: {'bytes': os.path.getsize(os.path.join(cd, f)), 'sha256': _sha(os.path.join(cd, f))}
                         for f in sorted(os.listdir(cd)) if f.endswith('.step')}}
        ver['ok'] = bool(rc1 == 0 and rc2 == 0 and ver['determinism']['coloured_identical'] and
                         ver['determinism']['plain_identical'] and rb and not rb.get('label_prefix_mismatch'))
        C.write_json(os.path.join(cd, 'verification.json'), ver)
        open(os.path.join(cd, 'CHANGES.md'), 'w', encoding='utf-8').write(CM.render(comp, ver))
        log(f"verification ok={ver['ok']} counts {comp['counts']} determinism {ver['determinism']['coloured_identical']}"
            f"/{ver['determinism']['plain_identical']} readback {rb and rb.get('counts')}")
        res.update(ok=ver['ok'], counts=comp['counts'], determinism=ver['determinism'], readback=rb,
                   checks=(comp.get('build') or {}).get('checks'), build_rc=[rc1, rc2])
        # ---- the patches shipped for the record (not part of the scripts tree): keep on the volume
        res['tree'] = f'{MD}/complete_integrate/{run_name}/scripts'
    except Exception as e:                              # noqa: BLE001 - recorded, never hidden
        import traceback
        res['error'] = f'{type(e).__name__}: {e}'
        res['trace'] = traceback.format_exc()[-3000:]
        log('FAILED ' + res['error'])
    res['seconds'] = round(time.time() - t_start, 1)
    # ---- publish to the volume (also on failure: what exists, for diagnosis)
    P = os.path.join(W, 'publish')
    os.makedirs(P)
    if os.path.isdir(S):
        shutil.copytree(S, os.path.join(P, 'scripts'))
    if os.path.isdir(os.path.join(W, 'patches')):
        shutil.copytree(os.path.join(W, 'patches'), os.path.join(P, 'patches'))
    shutil.copy(logf, os.path.join(P, 'complete.log'))
    C.write_json(os.path.join(P, 'result.json'), res)
    C.publish(P, os.path.join(MD, 'complete_integrate', run_name))
    shutil.rmtree(W, ignore_errors=True)
    return res


def bundle(job, run_name, code_version='pmp-completion 1.0'):
    """the bundle of /vol/<id>/complete_integrate/<run>/scripts (publish_v2 bundle_lib: the completed layout allowed;
    the box publisher needs --lenient-layout for the 3 new top-level entries) -> .../bundle/<id>.tar.gz + facts"""
    sys.path.insert(0, '/pmp/publish_v2')
    import bundle_lib as BL
    ID, MF = job['id'], job['model_folder']
    T = os.path.join(C.VOL, ID, 'complete_integrate', run_name)
    S = os.path.join(T, 'scripts')
    if not os.path.isdir(S):
        return {'ok': False, 'error': 'no completed scripts tree on the volume'}
    tmp = f'/tmp/pmpb/{ID[:16]}'
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(S, os.path.join(tmp, 'scripts'))
    for dp, dn, fn in os.walk(os.path.join(tmp, 'scripts')):
        for d in list(dn):
            if d == '__pycache__':
                shutil.rmtree(os.path.join(dp, d))
                dn.remove(d)
        for f in fn:
            if f.endswith(('.pyc', '.tmp', '.part')):
                os.remove(os.path.join(dp, f))
    prev = {}

    def source(rel):
        if rel.startswith(MF + '/completed/'):
            return f'{code_version}: build_completed_coloured.py / verify_completed.py / changes_md.py run from this tree'
        if rel.startswith(MF + '/schedules_original/'):
            return 'the original rebuild\'s schedules (baseline pipeline run), unchanged'
        if rel == MF + '/schedules/completion.json':
            return f'{code_version}: merge of the completion tracks (complete/INTERFACES.md) + build checks'
        if rel.startswith(MF + '/schedules/'):
            return f'{code_version}: COMPLETED schedules = baseline schedules + the tracks\' patches (completion.json)'
        if rel in (MF + '/build_completed_coloured.py', MF + '/build_model.py', MF + '/build_issues_model.py'):
            return f'{code_version}: shipped script'
        return prev.get(rel) or 'baseline scripts tree (pmp-partial run), unchanged'
    dest = os.path.join(tmp, f'{ID}.tar.gz')
    header = dict(run=run_name, model_id=ID, pid=job['pid'], model_folder=MF, step_relpath=job['step'],
                  step_source={'package_ifc': 'ifc', 'regenerated_from_db1': 'db1', 'emitted_from_sds2': 'sds2'}[job['source_kind']],
                  code_version=code_version, source_kind=job['source_kind'], completion=True)
    b = BL.make_bundle(os.path.join(tmp, 'scripts'), dest, header, source)
    b['md5_hex'] = hashlib.md5(open(dest, 'rb').read()).hexdigest()
    bd = os.path.join(T, 'bundle')
    os.makedirs(bd, exist_ok=True)
    shutil.copy(dest, os.path.join(bd, f'{ID}.tar.gz'))
    facts = {k: b[k] for k in ('sha256', 'bytes', 'n_files', 'md5_b64', 'md5_hex', 'warnings')}
    C.write_json(os.path.join(bd, 'bundle_facts.json'), facts)
    shutil.rmtree(tmp, ignore_errors=True)
    return dict(ok=True, **facts)
