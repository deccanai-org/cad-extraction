#!/usr/bin/env python3
"""conv_batch.py - ifcXML inputs -> SPF (ifcxml2spf.py) -> validation (validate_spf.py, ifcopenshell 0.9.0 + 0.8.4 open)
-> kit STEP pipeline exactly as the fleet worker runs it (ifc_census.py, ifc2step6.py --mode hybrid --prec 2,
step_check.py OCC read-back, grade_join.py coverage + per-part volume), plus a comparison run of ifc2step6 on the raw
ifcXML (its built-in reader) joined against the same census.

    conv_batch.py JOBS.json [--procs N] [--no-raw] [--tag NAME]
JOBS.json: [{"sha256":..., "key":..., "name":..., "ds":..., "paths":[...]}, ...]   (key = bim object key)
Per job: work/conv/<sha12>/ ; uploads to s3://bim/<OUT>/conv/<sha256>/ (reports, census, check, join, png, SPF.gz,
STEP.gz) and a one-line summary to <OUT>/conv/<sha256>/summary.json; batch table <OUT>/conv_<tag>.json.
"""
import os, sys, json, time, gzip, shutil, hashlib, subprocess, argparse, traceback
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'
OUT = os.environ.get('CONV_OUT', 'cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml')
HERE = os.path.dirname(os.path.abspath(__file__))
PY = '/opt/conv/env/bin/python'
PY84 = '/opt/conv/ifc84/bin/python'
KIT = os.path.join(HERE, 'kit')
ENV = dict(os.environ, DEFLECTION='0.005', ANG_DEFLECTION='0.6', PYTHONDONTWRITEBYTECODE='1')
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'}))


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def run(cmd, logf, timeout):
    t = time.time()
    with open(logf, 'w') as lf:
        try:
            p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout, env=ENV)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    return rc, round(time.time() - t, 1)


def jload(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return None


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 22), b''):
            h.update(blk)
    return h.hexdigest()


def data_sha(p):
    """sha256 of the DATA section (everything after the HEADER), to compare SPF content across converter versions"""
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        buf = f.read(1 << 20)
        i = buf.find(b'\nDATA;\n')
        h.update(buf[i:] if i >= 0 else buf)
        for blk in iter(lambda: f.read(1 << 22), b''):
            h.update(blk)
    return h.hexdigest()


def up(path, name, sha):
    if os.path.exists(path):
        s3.upload_file(path, B, f'{OUT}/conv/{sha}/{name}')


def gz(path):
    with open(path, 'rb') as a, gzip.open(path + '.gz', 'wb', compresslevel=6) as b:
        shutil.copyfileobj(a, b, 1 << 24)
    return path + '.gz'


def step_chain(d, spf_or_src, tag, census_parts, title, threads):
    """ifc2step6 -> step_check -> grade_join; returns dict"""
    stp = os.path.join(d, f'{tag}.step')
    r = {}
    rc, sec = run([PY, os.path.join(KIT, 'ifc2step6.py'), spf_or_src, stp, '--mode', 'hybrid', '--prec', '2',
                   '--threads', str(threads)], os.path.join(d, f'{tag}.convert.log'), 4 * 3600)
    st = jload(stp + '.stats.json') or {}
    r['convert'] = {'rc': rc, 'sec': sec, 'parts': st.get('parts'), 'faces': st.get('faces'), 'bbox': st.get('bbox'),
                    'exact_parts': st.get('exact_parts'), 'approx_parts': st.get('approx_parts'),
                    'surface_fallback_parts': st.get('surface_fallback_parts'), 'levels': st.get('levels'),
                    'tags': st.get('tags'), 'input_fix': st.get('input_fix'), 'transcode_products': st.get('transcode_products'),
                    'tess_products': st.get('tess_products'), 'schema': st.get('schema')}
    if rc != 0 or not os.path.exists(stp):
        try:
            r['convert']['log_tail'] = open(os.path.join(d, f'{tag}.convert.log'), errors='replace').read()[-1500:]
        except Exception:
            pass
        return r
    r['step_bytes'] = os.path.getsize(stp)
    chk = os.path.join(d, f'{tag}.check.json')
    sparts = os.path.join(d, f'{tag}.step_parts.jsonl.gz')
    rc, sec = run([PY, os.path.join(KIT, 'step_check.py'), stp, chk, '--png', os.path.join(d, f'{tag}.png'), '--parts', sparts,
                   '--title', title[:100]], os.path.join(d, f'{tag}.check.log'), 3 * 3600)
    ck = jload(chk) or {'error': 'rc %s' % rc}
    r['check'] = {k: ck.get(k) for k in ('read_status', 'roots', 'transferred', 'solids', 'invalid', 'invalid_solids',
                                          'invalid_solids_est', 'nonpos_vol', 'nonpositive_volume', 'faces', 'bbox', 'blank',
                                          'error', 'shells', 'parts') if k in ck}
    r['check']['rc'] = rc
    r['check']['sec'] = sec
    if census_parts and os.path.exists(census_parts) and os.path.exists(sparts):
        jn = os.path.join(d, f'{tag}.join.json')
        rc, sec = run([PY, os.path.join(KIT, 'grade_join.py'), census_parts, sparts, jn], os.path.join(d, f'{tag}.join.log'), 3600)
        j = jload(jn) or {'error': 'rc %s' % rc}
        r['join'] = {k: j.get(k) for k in ('mode', 'expected', 'matched', 'coverage', 'volume', 'step_parts_unmatched',
                                            'error') if k in j}
        if isinstance(r['join'].get('volume'), dict):
            r['join']['volume'] = {k: v for k, v in r['join']['volume'].items() if k != 'worst'}
            r['join']['volume_worst5'] = (j.get('volume') or {}).get('worst', [])[:5]
    return r


def one(job, a):
    sha = job['sha256']
    s = sha[:12]
    d = os.path.join(HERE, a.workdir, s)
    os.makedirs(d, exist_ok=True)
    name = job.get('name') or job['key'].rsplit('/', 1)[-1]
    ext = os.path.splitext(name)[1].lower() or '.xml'
    src = os.path.join(d, 'in' + ext)
    res = {'sha256': sha, 'key': job['key'], 'name': name, 'ds': job.get('ds'), 'paths': (job.get('paths') or [])[:4],
           'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    t0 = time.time()
    try:
        if not os.path.exists(src) or sha256_file(src) != sha:
            s3.download_file(B, job['key'], src)
        got = sha256_file(src)
        res['in_bytes'] = os.path.getsize(src)
        res['sha_ok'] = got == sha
        if got != sha:
            res['status'] = 'input_sha_mismatch'
            return res
        spf = os.path.join(d, f'{s}.ifc')
        crep = os.path.join(d, 'conv.report.json')
        rc, sec = run([PY, os.path.join(HERE, 'ifcxml2spf.py'), src, spf, '--report', crep], os.path.join(d, 'conv.log'), 3 * 3600)
        cr = jload(crep) or {}
        res['ifcxml2spf'] = {'rc': rc, 'sec': sec, 'status': cr.get('status'), 'reason': cr.get('reason'),
                             'schema': cr.get('schema'), 'container': cr.get('container'), 'member': cr.get('member'),
                             'xml_bytes': cr.get('xml_bytes'), 'instances': cr.get('instances'),
                             'xml_top_level_elements': cr.get('xml_top_level_elements'),
                             'nested_instances': cr.get('nested_instances'), 'references': cr.get('references'),
                             'dangling_references': cr.get('dangling_references'), 'unknown_xml_names': cr.get('unknown_xml_names'),
                             'value_errors': (cr.get('value_errors') or [])[:5], 'notes': list((cr.get('notes') or {}).keys()),
                             'counters': cr.get('counters'), 'output_bytes': cr.get('output_bytes'),
                             'output_sha256': cr.get('output_sha256'), 'xml_root': cr.get('xml_root'),
                             'first_elements': cr.get('first_elements')}
        up(crep, 'conv.report.json', sha)
        if rc not in (0, 4) or not os.path.exists(spf):
            res['status'] = 'not_converted:%s' % (cr.get('status') or rc)
            return res
        # validation: independent XML census + round trip + schema validation
        vrep = os.path.join(d, 'validate.json')
        rc, sec = run([PY, os.path.join(HERE, 'validate_spf.py'), src, spf, '--conv-report', crep, '--report', vrep],
                      os.path.join(d, 'validate.log'), 3 * 3600)
        v = jload(vrep) or {}
        sv = v.get('schema_validate') or {}
        res['validate'] = {'rc': rc, 'sec': sec, 'verdict': v.get('verdict'), 'spf_instances': v.get('spf_instances'),
                           'xml_instances_with_id': v.get('xml_instances_with_id'), 'xml_instance_elements': v.get('xml_instance_elements'),
                           'per_type_equal': v.get('per_type_equal'), 'per_type_covered': v.get('per_type_covered'),
                           'instance_count_equal': v.get('instance_count_equal'),
                           'converter_instances_by_type_equal_spf': v.get('converter_instances_by_type_equal_spf'),
                           'roundtrip_counts': (v.get('roundtrip') or {}).get('counts'),
                           'roundtrip_failures': (v.get('roundtrip') or {}).get('failures'),
                           'schema_issues': sv.get('issues'), 'schema_issue_kinds': sv.get('by_kind'),
                           'duplicate_globalids_in_source': v.get('duplicate_globalids'),
                           'unit_scale_m': v.get('unit_scale_m'), 'products': v.get('products'),
                           'products_with_representation': v.get('products_with_representation'),
                           'products_with_representation_by_class': v.get('products_with_representation_by_class')}
        up(vrep, 'validate.json', sha)
        # ifcopenshell 0.8.4 (fleet fallback kernel) must open it too
        rc84, _ = run([PY84, '-c', 'import sys, ifcopenshell; f = ifcopenshell.open(sys.argv[1]); '
                       'print(ifcopenshell.version, f.schema, len(list(f)))', spf], os.path.join(d, 'open84.log'), 1800)
        res['open_ifcopenshell_084'] = {'rc': rc84, 'out': open(os.path.join(d, 'open84.log'), errors='replace').read()[-300:].strip()}
        # kit census of the converted SPF (expected parts by GlobalId)
        cj = os.path.join(d, 'census.json')
        cparts = os.path.join(d, 'src_parts.jsonl.gz')
        rc, sec = run([PY, os.path.join(KIT, 'ifc_census.py'), spf, cj, '--parts', cparts], os.path.join(d, 'census.log'), 3 * 3600)
        c = jload(cj) or {}
        res['census'] = {'rc': rc, 'sec': sec, **{k: c.get(k) for k in ('schema', 'products', 'with_body', 'by_category',
                                                                         'by_class', 'standins', 'unit', 'length_unit') if k in c}}
        res['spf_data_sha256'] = data_sha(spf)
        title = '%s %s' % (s, (job.get('paths') or [name])[0][-80:])
        if not a.no_step:
            res['v6'] = step_chain(d, spf, 'v6', cparts, title + ' v6', a.threads)
        if not a.no_raw and not a.no_step:
            res['v6raw'] = step_chain(d, src, 'v6raw', cparts, title + ' v6 raw-xml', a.threads)
        # uploads
        for nm in ('census.json', 'src_parts.jsonl.gz', 'conv.log', 'validate.log', 'census.log', 'open84.log'):
            up(os.path.join(d, nm), nm, sha)
        for tag in ('v6', 'v6raw'):
            for suf in ('.check.json', '.join.json', '.png', '.step_parts.jsonl.gz', '.convert.log', '.check.log', '.step.stats.json',
                        '.step.parts.json'):
                up(os.path.join(d, tag + suf), tag + suf, sha)
        up(gz(spf), f'{s}.ifc.gz', sha)
        if os.path.exists(os.path.join(d, 'v6.step')):
            up(gz(os.path.join(d, 'v6.step')), 'v6.step.gz', sha)
        res['status'] = 'done'
    except Exception as e:
        res['status'] = 'error'
        res['error'] = traceback.format_exc()[-1500:]
    finally:
        res['sec'] = round(time.time() - t0, 1)
        p = os.path.join(d, 'summary.json')
        with open(p, 'w') as f:
            json.dump(res, f, indent=1, default=str)
        try:
            up(p, 'summary.json', sha)
        except Exception:
            pass
        log('done', s, res.get('status'), res['sec'], 's')
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('jobs')
    ap.add_argument('--procs', type=int, default=4)
    ap.add_argument('--threads', type=int, default=2)
    ap.add_argument('--no-raw', action='store_true')
    ap.add_argument('--tag', default='batch')
    ap.add_argument('--no-step', action='store_true', help='conversion + validation + census only')
    ap.add_argument('--workdir', default='work/conv')
    a = ap.parse_args()
    jobs = json.load(open(a.jobs))
    log('jobs', len(jobs), 'procs', a.procs)
    out = []
    with ThreadPoolExecutor(a.procs) as ex:
        for r in ex.map(lambda j: one(j, a), jobs):
            out.append(r)
            p = os.path.join(HERE, f'conv_{a.tag}.json')
            with open(p, 'w') as f:
                json.dump(out, f, indent=1, default=str)
            s3.upload_file(p, B, f'{OUT}/conv_{a.tag}.json')
    log('CONV_ALLDONE', a.tag)


if __name__ == '__main__':
    main()
