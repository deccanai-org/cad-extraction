#!/usr/bin/env python3
"""Zenitude-data-3 IFC / IFCZIP / ifcXML -> STEP worker (fleet kit; data-4 conversion ladder + data-3 grading signals).

Job list  _state/conv/ifc/jobs.json (bim)  one job per distinct sha256; input_key = a stored object in bim (data-3, data-4
          or Disk-1/2 copy, resolved and sha-proven by the scan)
Output    conversions/ifc-step/<sha256>.step (+ .stats.json, .check.json, .png)
Detail    _state/conv/ifc/detail/<sha256>.{census.json, src_parts.jsonl.gz, step_parts.jsonl.gz, join.json}
Result    _state/conv/ifc/results/<sha256>.json   {status ok|fail, reason, input_fix, step{...}, validate{...}, census{...}, join{...}}
Grading signals (class assigned by the index builder): source inventory (ifc_census: products with a body by class and
category, box stand-ins, quantities, analytic volumes), STEP check (step_check: OCC read-back per root, BRepCheck +
volume per solid, bbox, render + blank test), join (coverage members / connections / other by GlobalId, per-part volume
vs source +-5%).

Per job (lessons of the Disk-1/2 run, HANDOFF_CAD_STEP.md 5.3):
  1. unpack: .ifczip / zip saved as .ifc -> largest .ifc member; gzip -> raw; OLE2 / CIS/2 / stub -> fail with reason
  2. input repairs: legacy schema (IFC2X2_FINAL, IFC2X_FINAL...) declared IFC2X3; concatenated exports merged
     (ifc_concat_fix: renumber + one IfcProject); file cut mid-statement: strict tail repair (0 dangling refs)
  3. ifc2step5.py --mode hybrid --prec 2 (transcode faceted items, tessellate the rest; AP214 faceted B-rep, mm)
     on ifcopenshell 0.9.0; kernel crash / hang / timeout -> retry on 0.8.4.post1; still crashing -> bisect the
     crashing elements (ifc_crash_bisect) and leave out only those (<= max(50, 1%)), listed in the result;
     parse failure -> normalized header, then tess-only mode
  4. bbox check (|v| >= 1e10 mm = corrupt source coordinates) -> ifc2step5_guard (tessellates those elements)
  5. flavour markers + OpenCASCADE read-back (roots, solids, faces, bbox) -> status ok only if geometry reads back
"""
import os, sys, re, json, time, gzip, shutil, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf

CODE = 'z3-ifc-2026-10-01a'
# z3 a: data-4 code f + PRODUCT.id = GlobalId, ifc_census, step_check (validity/volume/render), grade_join, RB_MAX 1 GB
# f: runtime v5 - redo rules evaluated safely (requeued download_error results were hidden: 'attempts' is an int retry count
#    on transient-final results); redo() accepts a non-list attempts
# e: runtime v4: at most 3 jobs >= 100 MB per host (all processes), disk reserved 40x input per job (several 200 MB
#    Tekla CMC IFC filled a 400 GB root), redo entries by failure reason (download_error requeue after the extraction repair)
# d: runtime convfleet-v3 (redo list read from S3 every round instead of a watched file; hand-off without waiting)
# c: STEP writer encodes names safely (Revit feet-inch names 8'' were written as '''' which OpenCASCADE 8.0.1 cannot lex:
#    entities dropped -> segfault on read-back), drops zero-area POLY_LOOPs; read-back crashes -> readback_crash (STEP kept
#    under _readback_crash/); code a/b readback failures and the ids in redo_ids.json (published but unreadable) re-run
# b: parse errors retried on ifcopenshell 0.8.4 (0.9.0 rejects e.g. Windows '-1.#IND' NaN tokens of Tekla 16 exports; 0.8.4 was
#    the Disk-1/2 kernel); code-a failures that never tried 0.8.4 re-run; disk gating (runtime v2)
OUT = cf.ROOT + '/conversions/ifc-step'
W = os.environ.get('CONV_HOME', '/opt/conv')
PY = os.path.join(W, 'env/bin/python')                 # conda: ifcopenshell 0.9.0 + pythonocc-core
PY84 = os.path.join(W, 'ifc84/bin/python')             # venv: ifcopenshell 0.8.4.post1 (fallback kernel)
CONV = os.path.join(HERE, 'ifc2step5.py'); GUARD = os.path.join(HERE, 'ifc2step5_guard.py')
if os.path.exists(os.path.join(HERE, 'ifc2step6.py')):          # IFC improver's drop-in (same CLI): used when present in the kit
    CONV = os.path.join(HERE, 'ifc2step6.py')
    if os.path.exists(os.path.join(HERE, 'ifc2step6_guard.py')):
        GUARD = os.path.join(HERE, 'ifc2step6_guard.py')
    _m6 = re.search(r"^VERSION = 'ifc2step6 (\d+)\.(\d+)", open(CONV).read(), re.M)
    CODE = CODE + ('+s6' if not _m6 or (_m6.group(1), _m6.group(2)) == ('6', '0') else f'+s{_m6.group(1)}.{_m6.group(2)}')
# a re-run with another converter never overwrites the earlier STEP (best-of): 6.0.x -> .v6, 6.1.x -> .v61, ...
VSUF = '.v6' if CODE.endswith('+s6') else ('.v' + CODE.rsplit('+s', 1)[1].replace('.', '') if '+s' in CODE else '')
CHECK = os.path.join(HERE, 'step_check.py'); CENSUS = os.path.join(HERE, 'ifc_census.py')
DET = cf.ROOT + '/_state/conv/ifc/detail'
RB_MAX = int(os.environ.get('RB_MAX_MB', '1024')) << 20
TIMEOUT = int(os.environ.get('IFC_TIMEOUT_S', str(6 * 3600)))
STALL = 1800
THREADS = os.environ.get('IFC_THREADS', '2')
FILES = ('worker.py', 'convfleet.py', 'ifc2step5.py', 'ifc2step5_guard.py', 'ifc_concat_fix.py', 'ifc_crash_bisect.py',
         'ifc_exclude.py', 'step_check.py', 'ifc_census.py', 'grade_join.py', 'ifc2step6.py', 'ifc2step6_guard.py', 'ifcxml2spf.py')
XML2SPF = os.path.join(HERE, 'ifcxml2spf.py')          # ifcXML (ISO 10303-28 / IFC4 ifcXML) -> SPF, validated converter
if os.path.exists(XML2SPF):
    CODE = CODE + '+x1'
import grade_join
CRASH = (-11, 139, -6, 134, 124, 125)


def need_disk(job):
    # input + unpacked copy + STEP (large Tekla inputs expand 2-10x, small ones up to 80x)
    n = job.get('size') or 0
    if job.get('kind') == 'ifczip':
        n *= 6
    return max(2 << 30, n * 40)


def redo(r):
    """results of older code that this code can do better"""
    if r.get('status') == 'ok' or not str(r.get('code', '')).startswith('z3-'):
        return False
    if r.get('reason') == 'out_of_memory' and r.get('runtime') != cf.RUNTIME:
        return True                               # killed 5x under the old reservations: once more with measured reservations
    if any(m in json.dumps(r, default=str) for m in cf.ENOSPC_MARKS):
        return True
    att = r.get('attempts') if isinstance(r.get('attempts'), list) else []
    tried84 = any(isinstance(a, dict) and a.get('kernel') == '0.8.4.post1' for a in att)
    if r.get('reason') in ('readback_fail', 'readback_crash') and r.get('code') in ('z4-ifc-2026-09-30a', 'z4-ifc-2026-09-30b'):
        return True                               # written before the degenerate-loop fix of the STEP writer
    return r.get('reason') in ('parse_error', 'convert_error', 'empty_output', 'truncated_source') and not tried84


def need_bytes(job):
    # ifc2step6 (v6: kernel + per-part OCC read-back) measured on the data-3 fleet, 1.2 x p95 peak RSS per input-size bucket:
    # < 1 MB p95 1.0 GB, 1-5 MB 4.6, 5-20 MB 13.0, 20-50 MB 23.4, 50-100 MB 45.8 (max 58); larger inputs have few samples
    # (100-200 MB: 58 GB) -> extrapolated. The coordinator refreshes the table from new measurements (mem_buckets.json).
    n = job.get('size') or 0
    if job.get('kind') == 'ifczip':
        n *= 6                                    # zip ratio of SPF text is ~5-10x
    mb = n >> 20
    for hi, gb in ((1, 2), (5, 6), (20, 16), (50, 28), (100, 56), (200, 90), (500, 160)):
        if mb < hi:
            return gb << 30
    return 200 << 30


def unpack(src, dst, rec):
    """-> path of the SPF / ifcXML file to convert, or raises Fail"""
    with open(src, 'rb') as f:
        head = f.read(8)
    if head[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(src) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            rec['zip_members'] = [[i.filename, i.file_size] for i in infos][:50]
            ifcs = [i for i in infos if i.filename.lower().endswith(('.ifc', '.ifcxml'))] or infos
            if not ifcs:
                raise Fail('empty_zip')
            m = max(ifcs, key=lambda i: i.file_size)
            ext = '.ifcXML' if m.filename.lower().endswith('.ifcxml') else '.ifc'
            out = dst + ext
            try:
                with z.open(m) as a, open(out, 'wb') as b:
                    shutil.copyfileobj(a, b, 1 << 24)
            except RuntimeError as e:             # encrypted member
                raise Fail('zip_encrypted', str(e)[:200])
            except (zipfile.BadZipFile, NotImplementedError) as e:
                raise Fail('zip_unreadable', str(e)[:200])
            rec['unzipped'] = {'member': m.filename, 'bytes': m.file_size, 'members': len(infos),
                               'ifc_members': sum(1 for i in infos if i.filename.lower().endswith('.ifc'))}
            return unpack(out, dst + '.inner', rec) if open(out, 'rb').read(4) in (b'PK\x03\x04',) else out
    if head[:2] == b'\x1f\x8b':
        out = dst + '.ifc'
        with gzip.open(src) as a, open(out, 'wb') as b:
            shutil.copyfileobj(a, b, 1 << 24)
        rec['gunzipped'] = True
        return out
    if head[:8] == bytes.fromhex('D0CF11E0A1B11AE1'):
        raise Fail('not_ifc_ole2_document')
    return src


class Fail(Exception):
    def __init__(self, reason, detail=None):
        super().__init__(reason); self.reason = reason; self.detail = detail


def sniff(path, rec):
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        head = f.read(1 << 16)
        f.seek(max(0, size - 4096)); tail = f.read()
    if size < 200 or not head.strip(b'\x00 \r\n\t'):
        raise Fail('empty_or_stub_file', f'{size} bytes')
    h0 = head.lstrip(b'\xef\xbb\xbf \r\n\t')
    if h0[:1] == b'<' or head[:2] in (b'\xff\xfe', b'\xfe\xff') or b'<ifcXML' in head[:4096] or b'iso_10303_28' in head[:4096]:
        rec['format'] = 'ifcxml'; return 'ifcxml'
    if b'ISO-10303-21' not in head[:4096]:
        if not head.replace(b'\x00', b''):
            raise Fail('all_zero_file')
        raise Fail('not_step21', head[:60].decode('latin1'))
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", head)
    schema = m.group(1).decode('latin1').upper() if m else None
    rec['schema_in'] = schema
    if schema and schema.startswith('STRUCTURAL_FRAME'):
        raise Fail('not_ifc_cis2', schema)
    rec['terminated'] = tail.rstrip(b'\x00 \r\n\t').endswith(b'END-ISO-10303-21;')
    return schema


def fix_schema(src, dst, schema, rec):
    if schema in ('IFC2X2_FINAL', 'IFC2X_FINAL', 'IFC2X2', 'IFC2X', 'IFC2X2_PLATFORM', 'IFC2X_PLATFORM', 'IFC2X3_FINAL', 'IFC2X3_TC1'):
        data = open(src, 'rb').read()
        m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data[:1 << 16])
        data = data[:m.start(1)] + b'IFC2X3' + data[m.end(1):]
        open(dst, 'wb').write(data); rec.setdefault('input_fix', []).append(f'schema_{schema}_declared_IFC2X3')
        return dst
    if schema in ('IFC4X1', 'IFC4X2', 'IFC4X3_RC1', 'IFC4X3_RC2', 'IFC4X3_RC3', 'IFC4X3_RC4', 'IFC4X3_TC1', 'IFC4X3_ADD1', 'IFC4X3_ADD2'):
        data = open(src, 'rb').read()
        m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data[:1 << 16])
        data = data[:m.start(1)] + b'IFC4X3_ADD2' + data[m.end(1):]
        open(dst, 'wb').write(data); rec.setdefault('input_fix', []).append(f'schema_{schema}_declared_IFC4X3_ADD2')
        return dst
    return src


def normalize_header(src, dst, schema, rec):
    data = open(src, 'rb').read()
    h = re.search(rb'HEADER;(.*?)ENDSEC;', data, re.S)
    if not h:
        return None
    std = (b"HEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
           b"FILE_NAME('model.ifc','2000-01-01T00:00:00',(''),(''),'','','');\n"
           b"FILE_SCHEMA(('" + (schema or 'IFC2X3').encode() + b"'));\nENDSEC;")
    open(dst, 'wb').write(data[:h.start()] + std + data[h.end():])
    rec.setdefault('input_fix', []).append('header_normalized')
    return dst


def tail_repair(path, rec):
    """a file cut mid-statement is repaired ONLY if nothing but the unfinished tail is lost: cut at the last
    complete statement, terminate, and require 0 dangling #refs + IfcProject + IfcUnitAssignment"""
    data = open(path, 'rb').read()
    cut = max(data.rfind(b';\r\n'), data.rfind(b';\n'))
    if cut < 0:
        return {'refused': 'no complete statement'}
    body = data[:cut + 1]; dropped = len(data) - len(body)
    if body.rstrip().endswith(b'ENDSEC;'):
        body = body.rstrip()[:-len(b'ENDSEC;')]
    ids = set(int(m.group(1)) for m in re.finditer(rb'#(\d+)\s*=', body))
    refs = set(int(m.group(1)) for m in re.finditer(rb'#(\d+)', re.sub(rb"'[^']*'", b'', body)))
    dangling = len(refs - ids)
    proj = re.search(rb'=\s*IFCPROJECT\s*\(', body, re.I) is not None
    units = re.search(rb'=\s*IFCUNITASSIGNMENT\s*\(', body, re.I) is not None
    info = {'dropped_bytes': dropped, 'entities_kept': len(ids), 'dangling_refs': dangling, 'project': proj, 'units': units}
    if dangling or not proj or not units or dropped > 1 << 20:
        info['refused'] = f'{dangling} dangling refs, project={proj}, units={units}, cut {dropped} bytes'
        return info
    nl = b'\r\n' if b'\r\n' in body[-64:] else b'\n'
    with open(path, 'wb') as fh:
        fh.write(body.rstrip() + nl + b'ENDSEC;' + nl + b'END-ISO-10303-21;' + nl)
    info['repaired'] = True
    return info


def geometry_census(fl, path, logf):
    """what the model holds when a conversion writes no parts: products with a body vs grids/annotations only"""
    code = ("import ifcopenshell,json,sys\nf=ifcopenshell.open(sys.argv[1])\nskip={'IfcOpeningElement','IfcSpace','IfcGrid','IfcAnnotation','IfcVirtualElement','IfcOpeningStandardCase'}\n"
            "n=0;b=0;g=0\nfor p in f.by_type('IfcProduct'):\n  n+=1\n  if p.is_a() in ('IfcGrid','IfcAnnotation'): g+=1\n  elif p.is_a() not in skip and p.Representation: b+=1\n"
            "print(json.dumps({'products':n,'with_body':b,'grids_annotations':g}))")
    try:
        rc, out, err = fl.sh([PY, '-c', code, path], timeout=3600)
        return json.loads(out.strip().splitlines()[-1])
    except Exception as e:
        return {'error': f'{type(e).__name__}: {str(e)[:100]}'}


def convert(fl, jid, py, conv, src, stp, logf, mode='hybrid'):
    for f in (stp, stp + '.stats.json'):
        if os.path.exists(f): os.remove(f)
    t = time.time()
    rc = fl.run(jid, [py, conv, src, stp, '--mode', mode, '--prec', '2', '--threads', THREADS], logf, TIMEOUT, stall=STALL,
                env=dict(os.environ, DEFLECTION='0.005', ANG_DEFLECTION='0.6'))
    st = {}
    try:
        st = json.load(open(stp + '.stats.json'))
    except Exception:
        pass
    ok = rc == 0 and os.path.exists(stp) and (st.get('parts') or 0) > 0
    return {'rc': rc, 'ok': ok, 'sec': round(time.time() - t, 1), 'mode': mode, 'kernel': '0.8.4.post1' if py == PY84 else '0.9.0',
            'converter': os.path.basename(conv), 'parts': st.get('parts'), 'stats': st}


def tail_of(logf, n=1500):
    try:
        return open(logf, errors='replace').read()[-n:]
    except Exception:
        return ''


def process(fl, job, d):
    jid = job['id']; logf = os.path.join(d, 'log.txt')
    rec = {'sha256': job['sha256'], 'kind': job.get('kind'), 'input_key': job['input_key'], 'input_from': job.get('input_from'),
           'in_bytes': job.get('size'), 'n_paths': job.get('n_paths'), 'paths_sample': job.get('paths', [])[:3],
           'retry_of': job.get('retry_of'), 'out_key': f'{OUT}/{jid}{VSUF}.step', 'attempts': []}
    raw = os.path.join(d, 'in.bin')
    try:
        cf.s3.download_file(cf.B, job['input_key'], raw)
    except Exception as e:
        return dict(rec, status='fail', reason='download_error', transient=True, error=str(e)[:300])
    got = cf.sha256_file(raw)
    if got != job['sha256']:
        return dict(rec, status='fail', reason='input_sha_mismatch', transient=True, error=got)
    try:
        src = unpack(raw, os.path.join(d, 'unz'), rec)
        schema = sniff(src, rec)
    except Fail as e:
        return dict(rec, status='fail', reason=e.reason, detail=e.detail)
    except Exception as e:
        return dict(rec, status='fail', reason='unpack_error', detail=f'{type(e).__name__}: {str(e)[:200]}')
    if schema == 'ifcxml' and os.path.exists(XML2SPF):
        # ifcXML -> SPF (every instance / value from the XML; nothing invented), then the normal SPF path
        spf = os.path.join(d, 'from_ifcxml.ifc'); xrep = os.path.join(d, 'ifcxml2spf.json')
        rcx = fl.run(jid, [PY, XML2SPF, src, spf, '--report', xrep], os.path.join(d, 'ifcxml2spf.log'), 3 * 3600, mem_frac=0.85)
        try:
            xr = json.load(open(xrep))
        except Exception:
            xr = {'status': 'error', 'rc': rcx, 'log': tail_of(os.path.join(d, 'ifcxml2spf.log'), 400)}
        rec['ifcxml'] = {k: xr.get(k) for k in ('version', 'status', 'reason', 'schema', 'container', 'member', 'xml_bytes',
                                                 'xml_root', 'first_elements', 'instances', 'references',
                                                 'dangling_references', 'value_errors', 'unknown_xml_names', 'sec')}
        rec['ifcxml']['rc'] = rcx
        if rcx == 2:
            root = (xr.get('xml_root') or '')
            reason = 'not_ifc_xml_tekla_export_to_revit' if root in ('NewDataSet', 'DocumentElement') else 'not_ifc_xml'
            return dict(rec, status='fail', reason=reason, detail=(xr.get('reason') or '')[:200])
        if rcx not in (0, 4) or not os.path.exists(spf):
            return dict(rec, status='fail', reason={3: 'ifcxml_parse_error', 5: 'ifcxml_unsupported_schema'}.get(rcx, 'ifcxml_convert_error'),
                        detail=(xr.get('reason') or str(xr.get('value_errors') or '')[:200]), log_tail=tail_of(os.path.join(d, 'ifcxml2spf.log')))
        rec.setdefault('input_fix', []).append('ifcxml_converted_to_spf' if rcx == 0 else 'ifcxml_converted_to_spf_with_dangling_references')
        src = spf
        try:
            schema = sniff(src, rec)
        except Fail as e:
            return dict(rec, status='fail', reason=e.reason, detail=e.detail)
        rec['format'] = 'ifcxml'
    if schema == 'ifcxml':
        x = src if src.lower().endswith('.ifcxml') else src + '.ifcXML'
        if x != src: os.replace(src, x)
        src = x
    else:
        src = fix_schema(src, os.path.join(d, 'schema.ifc'), schema, rec)
        n_iso = 0
        with open(src, 'rb') as f:              # headers = 'ISO-10303-21;' not preceded by 'END-' (chunk overlap kept)
            prev = b''
            for chunk in iter(lambda: f.read(1 << 24), b''):
                buf = prev[-32:] + chunk
                n_iso += buf.count(b'ISO-10303-21;') - buf.count(b'END-ISO-10303-21;') - (prev[-32:].count(b'ISO-10303-21;') - prev[-32:].count(b'END-ISO-10303-21;'))
                prev = chunk
        rec['spf_headers'] = n_iso
        if n_iso > 1:
            rc, out, err = fl.sh([PY, os.path.join(HERE, 'ifc_concat_fix.py'), src, os.path.join(d, 'merged.ifc')], timeout=3600)
            try:
                rep = json.loads(out.strip().splitlines()[-1])
            except Exception:
                rep = {'result': 'error', 'err': err[-300:]}
            rec['concat'] = rep
            if rep.get('result') == 'merged':
                src = os.path.join(d, 'merged.ifc'); rec.setdefault('input_fix', []).append('concatenated_exports_merged')
        if not rec.get('terminated'):
            tr = tail_repair(src, rec); rec['tail'] = tr
            if tr.get('repaired'):
                rec.setdefault('input_fix', []).append('truncated_tail_repaired')
    stp = os.path.join(d, 'out.step')
    # ---- conversion ladder
    a = convert(fl, jid, PY, CONV, src, stp, logf); rec['attempts'].append(a)
    if not a['ok'] and a['rc'] == -9:
        raise MemoryError()
    if not a['ok'] and schema == 'ifcxml' and os.path.exists(PY84):
        a = convert(fl, jid, PY84, CONV, src, stp, logf); rec['attempts'].append(a)   # 0.9.0 dropped the ifcXML reader
        if not a['ok'] and a['rc'] == -9: raise MemoryError()
    if not a['ok'] and a['rc'] in CRASH and os.path.exists(PY84):
        a = convert(fl, jid, PY84, CONV, src, stp, logf); rec['attempts'].append(a)
        if not a['ok'] and a['rc'] == -9: raise MemoryError()
    soft = lambda a: not a['ok'] and a['rc'] not in CRASH and a['rc'] not in (0, -9)
    if soft(a) and schema != 'ifcxml':
        if os.path.exists(PY84):
            # 0.9.0 parses strictly (e.g. Windows '-1.#IND' NaN tokens of Tekla 16 exports); 0.8.4.post1 (the Disk-1/2 kernel) is lenient
            a = convert(fl, jid, PY84, CONV, src, stp, logf); rec['attempts'].append(a)
            if not a['ok'] and a['rc'] == -9: raise MemoryError()
        if soft(a):
            nh = normalize_header(src, os.path.join(d, 'hdr.ifc'), schema if schema and schema.startswith('IFC') else None, rec)
            if nh:
                src = nh
                for py in ([PY, PY84] if os.path.exists(PY84) else [PY]):
                    a = convert(fl, jid, py, CONV, src, stp, logf); rec['attempts'].append(a)
                    if not a['ok'] and a['rc'] == -9: raise MemoryError()
                    if not soft(a): break
        if soft(a):
            a = convert(fl, jid, PY84 if a['kernel'] == '0.8.4.post1' else PY, CONV, src, stp, logf, mode='tess'); rec['attempts'].append(a)
            if not a['ok'] and a['rc'] == -9: raise MemoryError()
    census_src = src                      # inventory of the model before any crash-element exclusion
    if not a['ok'] and a['rc'] in CRASH and schema != 'ifcxml':
        # geometry kernel crash / hang: bisect the culprit elements, leave out exactly those
        py = PY84 if os.path.exists(PY84) else PY
        info = {'at': cf.now()}
        try:
            rc = fl.run(jid, [py, os.path.join(HERE, 'ifc_crash_bisect.py'), src, CONV, THREADS if int(THREADS) > 2 else '4', '300'],
                        os.path.join(d, 'bisect.log'), 4 * 3600)
            lines = [l for l in tail_of(os.path.join(d, 'bisect.log'), 200000).splitlines() if l.startswith('{')]
            res = json.loads(lines[-1]) if lines else None
            if res is None:
                info['result'] = f'bisect produced no result (rc {rc})'
            else:
                culprits = res['culprits']; cap = max(50, res['tessellate_set'] // 100)
                info.update(tessellate_set=res['tessellate_set'], culprits=len(culprits), bisect_sec=res['secs'])
                if not culprits:
                    info['result'] = 'no crashing element isolated'
                elif len(culprits) > cap:
                    info['result'] = f'too many crashing elements ({len(culprits)} > {cap})'
                else:
                    fixed = os.path.join(d, 'excl.ifc')
                    rc2, out, err = fl.sh([py, os.path.join(HERE, 'ifc_exclude.py'), src, fixed] + [c['guid'] for c in culprits if c.get('guid')], timeout=3600)
                    rec['excluded_elements'] = json.loads(out.strip().splitlines()[-1])
                    a = convert(fl, jid, py, CONV, fixed, stp, logf); rec['attempts'].append(a)
                    info['result'] = f'converted without {len(culprits)} crashing element(s)' if a['ok'] else f"still fails (rc {a['rc']})"
                    if a['ok']:
                        src = fixed; rec.setdefault('input_fix', []).append('kernel_crash_elements_excluded')
        except Exception as e:
            info['result'] = f'rescue error: {type(e).__name__}: {str(e)[:200]}'
        rec['rescue'] = info
    if not a['ok']:
        if a['rc'] == 0 and (a['parts'] or 0) == 0:
            gc = geometry_census(fl, src, logf); rec['census'] = gc
            reason = 'no_geometry_grid_or_annotation_only' if gc.get('with_body') == 0 else 'empty_output'
        elif a['rc'] in (124,):
            reason = 'timeout'
        elif a['rc'] == 125:
            reason = 'kernel_hang'
        elif a['rc'] in (-11, 139, -6, 134):
            reason = 'kernel_crash'
        elif schema == 'ifcxml':
            reason = 'ifcxml_unsupported'
        elif not rec.get('terminated') and (rec.get('tail') or {}).get('refused'):
            reason = 'truncated_source'
        else:
            t = tail_of(logf, 4000)
            reason = 'parse_error' if re.search(r'(?i)unable to parse|syntax|parse|unexpected token|not a valid|schema', t) else 'convert_error'
        return dict(rec, status='fail', reason=reason, log_tail=tail_of(logf))
    st = a['stats']; bb = st.get('bbox')
    if not cf.bbox_sane(bb) and schema != 'ifcxml':
        # corrupt source coordinates (e.g. 2.6e266): the guard converter tessellates such elements
        g = convert(fl, jid, PY84 if a['kernel'] == '0.8.4.post1' else PY, GUARD, src, stp, logf); rec['attempts'].append(g)
        if g['ok'] and cf.bbox_sane(g['stats'].get('bbox')):
            a = g; st = g['stats']; rec.setdefault('input_fix', []).append('corrupt_coordinates_tessellated')
        else:
            return dict(rec, status='fail', reason='corrupt_coordinates', bbox=bb, guard_bbox=(g['stats'] or {}).get('bbox'))
    # ---- validation (STEP check + source census + join)
    nb = os.path.getsize(stp)
    mk = cf.count_markers(stp, cf.STEP_MARKERS)
    head = open(stp, errors='replace').read(3000)
    flavour = mk['ADVANCED_FACE'] == 0 and mk['TESSELLATED'] == 0 and mk['TRIANGULATED_FACE_SET'] == 0 and 'AUTOMOTIVE_DESIGN' in head
    png = stp + '.png'; chk = stp + '.check.json'; sparts = os.path.join(d, 'step_parts.jsonl.gz')
    v = {}
    if nb < RB_MAX:
        rc = fl.run(jid, [PY, CHECK, stp, chk, '--png', png, '--parts', sparts, '--title', f"{jid[:16]}  {(job.get('paths') or [''])[0][-90:]}"],
                    os.path.join(d, 'val.log'), 4 * 3600, mem_frac=0.85)
        try:
            v = json.load(open(chk))
        except Exception:
            v = {'error': f'read-back rc {rc}', 'rc': rc, 'log': tail_of(os.path.join(d, 'val.log'), 300)}
        if rc == -9:                              # memory kill: once more without the render (read-back only)
            rc = fl.run(jid, [PY, CHECK, stp, chk, '--parts', sparts], os.path.join(d, 'val.log'), 4 * 3600, mem_frac=0.85)
            try:
                v = json.load(open(chk)) if rc == 0 else {'error': f'read-back rc {rc}', 'rc': rc}
            except Exception:
                v = {'error': f'read-back rc {rc}', 'rc': rc}
    else:
        rc = fl.run(jid, [PY, CHECK, stp, chk, '--no-occ'], os.path.join(d, 'val.log'), 3600)
        try:
            v = json.load(open(chk))
        except Exception:
            v = {}
        v['skipped'] = f'STEP >= {RB_MAX >> 20} MB: text checks only (markers, products), no OCC read-back'
    v['flavour_ok'] = flavour; v['markers_kit'] = mk
    if v.get('read_status') == 'ok' and 'solids' in v:
        grade = 'ok_solid' if v.get('solids', 0) > 0 else ('ok_surface' if v.get('faces', 0) > 0 else 'empty')
        v['roots_match_parts'] = v.get('transferred') == st.get('parts')
        if v.get('bbox') and not cf.bbox_sane(v['bbox']):
            grade = 'bad_bbox'
    elif 'skipped' in v:
        grade = 'ok_solid' if mk['FACETED_BREP'] > 0 else ('ok_surface' if mk['POLY_LOOP'] > 0 else 'empty')
    else:
        grade = 'readback_fail'
    v['grade'] = grade; v['validated'] = v.get('read_status') == 'ok'
    rec['validate'] = {k: x for k, x in v.items() if k not in ('invalid_examples',)}
    rec['validate']['invalid_examples'] = (v.get('invalid_examples') or [])[:10]
    rec['step'] = {'key': rec['out_key'], 'bytes': nb, 'parts': st.get('parts'), 'faces': st.get('faces'), 'points': st.get('points'),
                   'bbox_mm': st.get('bbox'), 'schema_in': st.get('schema'), 'file_length_unit': st.get('file_length_unit'),
                   'transcode_products': st.get('transcode_products'), 'tess_products': st.get('tess_products'),
                   'transcode_no_body_rep': st.get('transcode_no_body_rep'),
                   'kernel': a['kernel'], 'converter': f"{a['converter']} --mode {a['mode']} --prec 2", 'sec': a['sec'],
                   'peak_rss_mb': st.get('peak_rss_mb'), 'degenerate_faces_dropped': st.get('degenerate_faces_dropped'),
                   'v6': {k: st.get(k) for k in ('levels', 'tags', 'repair', 'exact_parts', 'approx_parts', 'surface_fallback_parts') if st.get(k) is not None} or None}
    if grade == 'readback_fail' and v.get('rc') in (-11, 139, -6, 134):
        key = f'{OUT}/_readback_crash/{jid}.step'
        try:
            fl.upload(stp, key, 'application/step'); rec['unverified_key'] = key
        except Exception:
            pass
        return dict(rec, status='fail', reason='readback_crash')
    if grade not in ('ok_solid', 'ok_surface') or not flavour:
        return dict(rec, status='fail', reason={'empty': 'empty_output', 'bad_bbox': 'corrupt_coordinates', 'readback_fail': 'readback_fail'}.get(grade, 'bad_flavour'))
    # source inventory on the exact file that was converted
    cj = os.path.join(d, 'census.json'); cparts = os.path.join(d, 'src_parts.jsonl.gz')
    py_c = PY84 if a['kernel'] == '0.8.4.post1' and os.path.exists(PY84) else PY
    rcc = fl.run(jid, [py_c, CENSUS, census_src, cj, '--parts', cparts], os.path.join(d, 'census.log'), 3 * 3600, mem_frac=0.85)
    try:
        rec['census'] = json.load(open(cj))
    except Exception:
        rec['census'] = {'error': f'census rc {rcc}', 'log': tail_of(os.path.join(d, 'census.log'), 400)}
    vparts = stp + '.verify_parts.jsonl.gz'
    if not os.path.exists(sparts) and 'skipped' in v and os.path.exists(vparts):
        # STEP over the read-back cap: ifc2step6 (>= 6.1.0-dev3+vr) read every written part back from its own STEP
        # block with step_check's checks and wrote them in step_check's --parts format -> per-part join from those
        sparts = vparts
        rec['validate']['per_part_source'] = 'converter_readback'
        rec['validate']['converter_readback'] = (st.get('readback_parts') or {})
    if os.path.exists(cparts) and os.path.exists(sparts):
        try:
            rec['join'] = grade_join.join(grade_join.load(cparts), grade_join.load(sparts))
            if sparts.endswith('.verify_parts.jsonl.gz'):
                rec['join']['per_part_source'] = 'converter_readback'
        except Exception as e:
            rec['join'] = {'error': f'{type(e).__name__}: {str(e)[:200]}'}
    # uploads
    fl.upload(stp, rec['out_key'], 'application/step')
    if os.path.exists(stp + '.stats.json'):
        fl.upload(stp + '.stats.json', rec['out_key'] + '.stats.json', 'application/json')
    if os.path.exists(chk):
        fl.upload(chk, rec['out_key'] + '.check.json', 'application/json')
    if os.path.exists(png):
        fl.upload(png, f'{OUT}/{jid}{VSUF}.png', 'image/png'); rec['render_key'] = f'{OUT}/{jid}{VSUF}.png'
    for fpath, nm in ((cj, 'census.json'), (cparts, 'src_parts.jsonl.gz'), (sparts, 'step_parts.jsonl.gz')):
        if os.path.exists(fpath):
            fl.upload(fpath, f'{DET}/{jid}{VSUF}.{nm}')
    if os.path.exists(stp + '.parts.json'):
        fl.upload(stp + '.parts.json', rec['out_key'] + '.parts.json', 'application/json')
    rec['status'] = 'ok'
    if not rec.get('input_fix'): rec['input_fix'] = None
    return rec


def est(r):
    """best-of key (lower is better): failure, coverage, invalid / non-positive solids, solid-less parts, volume outliers, v6 fallbacks"""
    if not r or r.get('status') != 'ok':
        return (1, 0, 0, 0, 0, 0)
    v = r.get('validate') or {}; j = r.get('join') or {}; cov = (j.get('coverage') or {}).get('all')
    fb = sum(n for t, n in ((r.get('step') or {}).get('v6') or {}).get('tags', {}).items() if t in ('L3-partial-surface', 'L4-surface', 'unverified', 'L3', 'L4')) \
        if isinstance(((r.get('step') or {}).get('v6') or {}).get('tags'), dict) else 0
    return (0, -(cov if cov is not None else 0), (v.get('invalid_solids_est') or v.get('invalid') or 0) + (v.get('nonpos_vol') or 0),
            j.get('surface_parts') or 0, (j.get('volume') or {}).get('outside_5pct') or 0, fb)


_process_inner = process


def process(fl, job, d):
    prev = fl.getj(f'{fl.ST}/results/{job["id"]}.json')
    new = _process_inner(fl, job, d)
    if not prev or prev.get('code') == CODE or prev.get('status') != 'ok':
        return new
    if est(new) <= est(prev):
        new['alternatives'] = {prev.get('code'): {'status': prev.get('status'), 'step_key': (prev.get('step') or {}).get('key'), 'est': list(est(prev))}}
        return new
    keep = {k: v for k, v in prev.items() if k not in ('id', 'pipeline', 'code', 'runtime', 'host', 'started', 'sec', 'finished', 'size')}
    keep['alternatives'] = {CODE: {'status': new.get('status'), 'reason': new.get('reason'), 'step_key': (new.get('step') or {}).get('key'), 'est': list(est(new))}}
    keep['best_of_note'] = f'{CODE} graded worse than {prev.get("code")}: earlier STEP kept'
    return keep


if __name__ == '__main__':
    fl = cf.Fleet('ifc', CODE, process, need_bytes, FILES, need_disk=need_disk, redo=redo, redo_ids_key=f'{cf.CTLROOT}/ifc/redo_ids.json', big=(100 << 20, 3))
    sys.exit(fl.main())
