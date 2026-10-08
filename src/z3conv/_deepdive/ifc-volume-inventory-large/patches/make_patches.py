#!/usr/bin/env python3
"""Re-apply this deep dive's edits to the CURRENT kit files and write patched copies + unified diffs into ./out/.
The kit is edited concurrently by other agents, so the edits are expressed as anchored string replacements (each must
match exactly once; a failing anchor is reported, never guessed). Run from this directory:
    python3 make_patches.py [/Users/dhiren/Downloads/Deccan/z3conv]
Outputs out/<kitpath with / -> __>.patched + .diff; ifc_census.py and the new modules are whole files (copied)."""
import os, sys, difflib, shutil, hashlib

KIT = sys.argv[1] if len(sys.argv) > 1 else '/Users/dhiren/Downloads/Deccan/z3conv'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
report = []


def edit(rel, steps):
    src = os.path.join(KIT, rel)
    if not os.path.exists(src):
        report.append(f'SKIP {rel}: not in the kit'); return
    s0 = open(src).read(); s = s0; bad = []
    for name, old, new in steps:
        n = s.count(old)
        if n != 1:
            bad.append(f'{name} (anchor found {n}x)'); continue
        s = s.replace(old, new)
    tag = rel.replace('/', '__')
    open(os.path.join(OUT, tag + '.patched'), 'w').write(s)
    d = difflib.unified_diff(s0.splitlines(True), s.splitlines(True), f'a/{rel}', f'b/{rel}')
    open(os.path.join(OUT, tag + '.diff'), 'w').writelines(d)
    report.append(f"{'OK  ' if not bad else 'PART'} {rel} md5 {hashlib.md5(s0.encode()).hexdigest()[:12]}: {len(steps) - len(bad)}/{len(steps)} edits"
                  + (f"; FAILED: {', '.join(bad)}" if bad else ''))


def whole(rel, mine):
    src = os.path.join(KIT, rel); tag = rel.replace('/', '__')
    s1 = open(os.path.join(HERE, mine)).read()
    s0 = open(src).read() if os.path.exists(src) else ''
    open(os.path.join(OUT, tag + '.patched'), 'w').write(s1)
    open(os.path.join(OUT, tag + '.diff'), 'w').writelines(difflib.unified_diff(s0.splitlines(True), s1.splitlines(True), f'a/{rel}', f'b/{rel}'))
    report.append(f'FILE {rel} <- {mine} (kit md5 {hashlib.md5(s0.encode()).hexdigest()[:12] if s0 else "new"})')


# ------------------------------------------------------------------ STEP writer: full real precision
R5_OLD = '''    if v == 0.0:
        return "0."
    s = "%.9g" % v'''
R5_NEW = '''    if v == 0.0:
        return "0."
    # shortest round-trip repr: "%.9g" kept 9 significant digits = 10 mm steps beyond 1e9 mm from the origin (survey /
    # state-plane placements, data-3 1481043e at -1456 km / 3036 km: 39 invalid solids) and 0.01 mm steps beyond 1e7 mm
    s = repr(float(v))
    if s in ("nan", "inf", "-inf"):
        s = "%.9g" % v
    elif s.endswith(".0"):
        s = s[:-1]'''
TC_OLD = '''        rep = getattr(pr, "Representation", None)
        if rep is None:
            n_norep += 1
            continue
'''
TC_NEW = '''        rep = getattr(pr, "Representation", None)
        if rep is None:
            n_norep += 1
            continue
        if getattr(pr, "HasOpenings", None):
            # IfcRelVoidsElement openings (copes, bolt holes, wall openings) are cut by the geometry kernel only: a
            # transcoded faceted body would be written uncut -> leave the product to the tess path
            n_openings += 1
            skipped.append(pr.id())
            continue
'''
for rel in ('ifc/ifc2step5.py', 'ifc/ifc2step5_guard.py', 'db1/ifc2step5.py'):
    edit(rel, [('real precision', R5_OLD, R5_NEW), ('defer openings', TC_OLD, TC_NEW),
               ('counter', '''    n_norep = 0
    n_unsupported_items = 0''', '''    n_norep = 0
    n_openings = 0
    n_unsupported_items = 0'''),
               ('stat', '''    stats["transcode_no_body_rep"] = n_norep''', '''    stats["transcode_no_body_rep"] = n_norep
    stats["transcode_deferred_openings"] = n_openings''')])

edit('ifc_v6/ifc2step6.py', [
    # (its coordinates are written with '%.<prec>f' -> full precision already; _r only formats directions: no change)
    ('defer openings', '''        if a.mode == 'tess':
            rec.src = 'kernel'
            kernel_list.append(rec)
            continue
''', '''        if a.mode == 'tess':
            rec.src = 'kernel'
            kernel_list.append(rec)
            continue
        if getattr(pr, 'HasOpenings', None):
            # IfcRelVoidsElement openings (copes, bolt holes, wall openings) are cut by the kernel only: a transcoded
            # faceted body would be written uncut (data-3 0645b1a6: 49 faceted beams / plates, up to 20 % of the volume)
            n_open += 1
            rec.src = 'kernel'
            kernel_list.append(rec)
            continue
'''),
    ('counter', '''    n_norep = n_unsup = n_corrupt = 0''', '''    n_norep = n_unsup = n_corrupt = n_open = 0'''),
    ('stat', '''    stats["transcode_corrupt_coords_tessellated"] = n_corrupt''', '''    stats["transcode_corrupt_coords_tessellated"] = n_corrupt
    stats["transcode_deferred_openings"] = n_open'''),
])

# ------------------------------------------------------------------ census v3 (whole file) + join v3 (interval support)
for rel in ('ifc/ifc_census.py', 'grade/ifc_census.py', 'common/ifc_census.py', 'db1/ifc_census.py'):
    whole(rel, 'ifc_census.py')
JOIN = [
    ('expected_range', """    return an or p.get('q')
""", """    return an or p.get('q')


def expected_range(p):
    \"\"\"census v3: a part whose openings could only be bounded carries an_lo / an_hi (removed volume between 0 and the
    clipped opening prisms) instead of an exact `an` -> (lo, hi) in mm3, or None\"\"\"
    if p.get('an') or p.get('q') or not p.get('an_hi') or (p.get('cv') or 1) < 3:
        return None
    return (p.get('an_lo') or 0.0, p['an_hi'])


def sort_volume(p):
    \"\"\"key of the sorted (1-D assignment) pairing of repeated names: exact expectation, else the interval midpoint\"\"\"
    e = expected_volume(p)
    if e:
        return e
    r = expected_range(p)
    return (r[0] + r[1]) / 2 if r else 0.0
"""),
    ('sort key', """                ps = sorted((p for p, _ in lst), key=lambda p: expected_volume(p) or 0.0)""",
     """                ps = sorted((p for p, _ in lst), key=sort_volume)"""),
    ('interval check', """    ratios = []; curved_out = 0; curved_gross = 0; out_ = 0; worst = []; checked = 0
    for p, s in pairs:
        v = s.get('volume')
        e = expected_volume(p)
        if not v or not e or e <= 0 or (s.get('solids') or 0) == 0:
            continue
        checked += 1
        r = v / e
        ratios.append(r)
        if abs(r - 1) > tol:""", """    ratios = []; curved_out = 0; curved_gross = 0; out_ = 0; worst = []; checked = 0; n_iv = 0
    for p, s in pairs:
        v = s.get('volume')
        e = expected_volume(p)
        rg = None if e else expected_range(p)
        if not v or (s.get('solids') or 0) == 0 or not ((e and e > 0) or (rg and rg[1] > 0)):
            continue
        checked += 1
        if rg:                                          # interval: inside [lo (1-tol), hi (1+tol)]; ratio to the nearer bound
            n_iv += 1
            r = v / rg[1] if v > rg[1] else (v / rg[0] if rg[0] and v < rg[0] else 1.0)
            bad = v > rg[1] * (1 + tol) or v < rg[0] * (1 - tol)
        else:
            r = v / e
            ratios.append(r)
            bad = abs(r - 1) > tol
        if bad:"""),
    ('curved interval', """            if p.get('an') and p.get('pt') in CURVED:""", """            if (p.get('an') or rg) and p.get('pt') in CURVED:"""),
    ('worst kind', """            worst.append([round(r, 4), p.get('gid'), p['cls'], p.get('name'), 'analytic' if p.get('an') else p.get('qk')])""",
     """            worst.append([round(r, 4), p.get('gid'), p['cls'], p.get('name'), 'analytic' if p.get('an') else ('analytic_interval' if rg else p.get('qk'))])"""),
    ('stat', """           'within_5pct': checked - out_ - curved_out}""", """           'within_5pct': checked - out_ - curved_out, 'checked_interval': n_iv}"""),
]
for rel in ('ifc/grade_join.py', 'grade/grade_join.py', 'common/grade_join.py', 'coord/grade_join.py', 'db1/grade_join.py'):
    edit(rel, JOIN)

# ------------------------------------------------------------------ chunked read-back wiring
CHUNKED_BLOCK = """        # chunked read-back (step_check_chunked.py): the same per-part checks on self-contained ~RB_CHUNK_MB chunks,
        # bounded memory on any box; text-only checks only if that fails as well
        why = 'read-back ran out of memory' if {n} < RB_MAX else f'STEP >= {{RB_MAX >> 20}} MB'
        rc = fl.run(jid, [PY, CHECKC, stp, chk, '--parts', {parts}, '--chunk-mb', CHUNK_MB, '--jobs', CHUNK_JOBS, '--check', CHECK,
                          '--py', PY, '--workdir', os.path.join(d, 'chunks')], os.path.join(d, 'val.log'), 8 * 3600{mem})
        try:
            v = json.load(open(chk))
        except Exception:
            v = {{}}
        if v.get('read_status') == 'ok':
            v['readback_mode'] = f'chunked ({{why}})'
        else:
            err = v.get('read_status') or v.get('skipped') or f'rc {{rc}}'
            fl.run(jid, [PY, CHECK, stp, chk, '--no-occ'], os.path.join(d, 'val.log'), 3600)
            try:
                v = json.load(open(chk))
            except Exception:
                v = {{}}
            v['chunked_error'] = err
            v['skipped'] = f'{{why}}: chunked read-back failed ({{err}}); text checks only (markers, products)'
"""
CONSTS = """CHECKC = os.path.join(HERE, 'step_check_chunked.py')           # STEP >= RB_MAX: chunked OCC read-back (bounded memory)
CHUNK_MB = os.environ.get('RB_CHUNK_MB', '150'); CHUNK_JOBS = os.environ.get('RB_CHUNK_JOBS', '1')
"""
edit('ifc/worker.py', [
    ('constants', """CHECK = os.path.join(HERE, 'step_check.py'); CENSUS = os.path.join(HERE, 'ifc_census.py')
""", """CHECK = os.path.join(HERE, 'step_check.py'); CENSUS = os.path.join(HERE, 'ifc_census.py')
""" + CONSTS + """XML2SPF = os.path.join(HERE, 'ifcxml2spf.py')                  # ifcXML -> SPF (neither kernel reads ifcXML)
if os.path.exists(CHECKC):
    CODE = CODE + '+cr'
"""),
    ('FILES', """'grade_join.py', 'ifc2step6.py', 'ifc2step6_guard.py')""", """'grade_join.py', 'ifc2step6.py', 'ifc2step6_guard.py',
         'step_check_chunked.py', 'ifcxml2spf.py')"""),
    ('schema table', """def fix_schema(src, dst, schema, rec):
    if schema in ('IFC2X2_FINAL',""", """# FILE_SCHEMA names the kernels load natively (0.8.4.post1: IFC2X3 IFC4 IFC4X1 IFC4X2 IFC4X3 IFC4X3_TC1 IFC4X3_ADD1
# IFC4X3_ADD2; 0.9.0: IFC2X3 IFC4 IFC4X1 IFC4X3_ADD2 + plugins). Relabel only what the kernel cannot load; IFC4X1 is not
# relabelled any more (its alignment entities do not exist in IFC4X3_ADD2 -> parse errors after a relabel).
IFC4_ALIASES = ('IFC4_ADD1', 'IFC4_ADD2', 'IFC4_ADD2_TC1', 'IFC4RV', 'IFC4_RV', 'IFC4X0', 'IFC4RC4', 'IFC4_RC4')


def kernel_loads(schema):
    \"\"\"True if the 0.9.0 kernel (PY) parses a file declaring `schema` (an instance is read to force the schema lookup)\"\"\"
    code = ("import ifcopenshell,sys\\nh=\\"ISO-10303-21;\\\\nHEADER;\\\\nFILE_DESCRIPTION((''),'2;1');\\\\nFILE_NAME('','',(''),(''),'','','');\\\\n"
            "FILE_SCHEMA(('%s'));\\\\nENDSEC;\\\\nDATA;\\\\n#1=IFCCARTESIANPOINT((0.,0.,0.));\\\\nENDSEC;\\\\nEND-ISO-10303-21;\\\\n\\"%sys.argv[1]\\n"
            "f=ifcopenshell.file.from_string(h)\\nf.by_id(1).Coordinates")
    try:
        import subprocess
        return subprocess.run([PY, '-c', code, schema], capture_output=True, timeout=120).returncode == 0
    except Exception:
        return False


def fix_schema(src, dst, schema, rec):
    if schema in IFC4_ALIASES:
        data = open(src, 'rb').read()
        m = re.search(rb"FILE_SCHEMA\\s*\\(\\s*\\(\\s*'([^']+)'", data[:1 << 16])
        data = data[:m.start(1)] + b'IFC4' + data[m.end(1):]
        open(dst, 'wb').write(data); rec.setdefault('input_fix', []).append(f'schema_{schema}_declared_IFC4')
        return dst
    if schema in ('IFC2X2_FINAL',"""),
    ('4x3 relabel', """    if schema in ('IFC4X1', 'IFC4X2', 'IFC4X3_RC1', 'IFC4X3_RC2', 'IFC4X3_RC3', 'IFC4X3_RC4', 'IFC4X3_TC1', 'IFC4X3_ADD1', 'IFC4X3_ADD2'):""",
     """    if schema in ('IFC4X3_RC1', 'IFC4X3_RC2', 'IFC4X3_RC3', 'IFC4X3_RC4') or (schema in ('IFC4X2', 'IFC4X3', 'IFC4X3_TC1', 'IFC4X3_ADD1') and not kernel_loads(schema)):"""),
    ('redo', """    return r.get('reason') in ('parse_error', 'convert_error', 'empty_output', 'truncated_source') and not tried84
""", """    if r.get('reason') == 'parse_error' and str(r.get('schema_in') or '').startswith(('IFC4_', 'IFC4RV', 'IFC4X0', 'IFC4RC', 'IFC4X1')):
        return True                               # schema names the old relabel table missed (IFC4 aliases) or broke (IFC4X1)
    if r.get('reason') == 'ifcxml_unsupported':
        return True                               # ifcXML is translated to SPF now (ifcxml2spf.py)
    return r.get('reason') in ('parse_error', 'convert_error', 'empty_output', 'truncated_source') and not tried84
"""),
    ('ifcxml', """    if schema == 'ifcxml':
        x = src if src.lower().endswith('.ifcxml') else src + '.ifcXML'
        if x != src: os.replace(src, x)
        src = x
    else:""", """    if schema == 'ifcxml':
        x = src if src.lower().endswith('.ifcxml') else src + '.ifcXML'
        if x != src: os.replace(src, x)
        src = x
        # neither kernel reads ifcXML: translate to SPF (ifcxml2spf.py: IFC2X3 / IFC4 / IFC4X3 dialects), then the SPF path
        spf = os.path.join(d, 'fromxml.ifc')
        rc, out, err = fl.sh([PY, XML2SPF, src, spf], timeout=3 * 3600)
        try:
            rec['ifcxml'] = json.loads(out.strip().splitlines()[-1])
        except Exception:
            rec['ifcxml'] = {'rc': rc, 'error': (err or '')[-300:]}
        if rc == 0 and os.path.exists(spf) and os.path.getsize(spf) > 200:
            src = spf; rec.setdefault('input_fix', []).append('ifcxml_translated_to_spf')
            schema = sniff(src, rec)
    if schema != 'ifcxml':"""),
    ('chunked read-back', """    else:
        rc = fl.run(jid, [PY, CHECK, stp, chk, '--no-occ'], os.path.join(d, 'val.log'), 3600)
        try:
            v = json.load(open(chk))
        except Exception:
            v = {}
        v['skipped'] = f'STEP >= {RB_MAX >> 20} MB: text checks only (markers, products), no OCC read-back'
""", """    if nb >= RB_MAX or v.get('rc') == -9:
""" + CHUNKED_BLOCK.format(n='nb', parts='sparts', mem=', mem_frac=0.85')),
])
edit('grade/worker.py', [
    ('constants', """CHECK = os.path.join(HERE, 'step_check.py'); CENSUS = os.path.join(HERE, 'ifc_census.py')
""", """CHECK = os.path.join(HERE, 'step_check.py'); CENSUS = os.path.join(HERE, 'ifc_census.py')
""" + CONSTS + """if os.path.exists(CHECKC):
    CODE = CODE + '+cr'
"""),
    ('FILES', """         'convert_one.py', 'layouts.json')""", """         'convert_one.py', 'layouts.json', 'step_check_chunked.py')"""),
    ('need_bytes', """def need_bytes(job):
    return max(4 << 30, (job.get('size') or 0) * 16, (job.get('step_bytes') or 0) * 40)""", """def need_bytes(job):
    # a STEP above RB_MAX is read back in chunks: its memory need is that of one RB_MAX read, not 40x the whole file
    return max(4 << 30, (job.get('size') or 0) * 16, min(job.get('step_bytes') or 0, RB_MAX) * 40)"""),
    ('chunked read-back', """    else:
        fl.run(jid, [PY, CHECK, stp, chk, '--no-occ'], os.path.join(d, 'val.log'), 3600)
        try:
            v = json.load(open(chk))
        except Exception:
            v = {}
        v['skipped'] = f'STEP >= {RB_MAX >> 20} MB: text checks only (markers, products), no OCC read-back'
    v['step_bytes'] = n""", """    if n >= RB_MAX or v.get('rc') == -9:
""" + CHUNKED_BLOCK.format(n='n', parts='parts', mem='') + """    v['step_bytes'] = n"""),
    ('final need_bytes', """(j.get('step_bytes') or 0) * 60, (j.get('size') or 0) * 20), FILES,""",
     """min(j.get('step_bytes') or 0, RB_MAX) * 60, (j.get('size') or 0) * 20), FILES,"""),
    ('redo', """        fl = cf.Fleet('grade', CODE, process, need_bytes, FILES, need_disk=need_disk, redo=lambda r: str(r.get('id', '')).startswith('db1-') and r.get('code') in ('z3-grade-2026-10-01a', 'z3-grade-2026-10-01b'))""",
     """        def redo(r):
            if str(r.get('id', '')).startswith('db1-') and r.get('code') in ('z3-grade-2026-10-01a', 'z3-grade-2026-10-01b'):
                return True
            # graded text-only (STEP >= RB_MAX, or read-back OOM): the chunked read-back verifies it now
            v = r.get('validate') or {}
            return r.get('status') == 'ok' and ('skipped' in v or v.get('rc') == -9) and 'chunked_error' not in v
        fl = cf.Fleet('grade', CODE, process, need_bytes, FILES, need_disk=need_disk, redo=redo)"""),
])
edit('coord/build_index.py', [
    ('graded_by', """        row['graded_by'] = 'occ_readback' + ('_sampled' if v.get('sampled') else '')""",
     """        row['graded_by'] = 'occ_readback' + ('_chunked' if v.get('chunked') else '') + ('_sampled' if v.get('sampled') else '')"""),
    ('weight_ratio keys', """'outside_curved', 'outside_curved_gross', 'median', 'p5', 'p95')} if vol else None""",
     """'outside_curved', 'outside_curved_gross', 'checked_interval', 'median', 'p5', 'p95')} if vol else None"""),
])
for mine in ('step_check_chunked.py', 'ifcxml2spf.py'):
    whole(f'ifc/{mine}', mine)
    whole(f'grade/{mine}', mine) if mine == 'step_check_chunked.py' else None
open(os.path.join(OUT, 'REPORT.txt'), 'w').write('\n'.join(report) + '\n')
print('\n'.join(report))
