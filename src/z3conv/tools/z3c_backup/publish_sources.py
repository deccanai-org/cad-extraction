"""publish_sources.py - live stats for the new source disks -> dhigdec/cad-extract-status/sources.json (public, anonymous).

Reads S3 state with the `bim` profile every INTERVAL seconds, writes sources.json into the local status-site clone and
commits + pushes when it changed. Numbers only: no archive, project or client names, no internal hostnames.
Run: caffeinate -i venv/bin/python publish_sources.py [interval_s]
     python3 publish_sources.py 0 --out /tmp/sources.json     # one round, write elsewhere, no git (local test)
"""
import calendar, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

INTERVAL = 120
REPO = os.environ.get('PUB_REPO', '/Users/dhiren/Downloads/Deccan/cad-extract-status')   # on the coordinator: /opt/status/cad-extract-status
# One bucket constant per section. Z4 is being moved to bim-proprietary-data with identical keys: switch Z4_B then.
Z4_B = 'bim-proprietary-data'      # moved from annotationprod 2026-09-30 (identical keys)
Z2_B = 'bim-proprietary-data'      # moved from annotationprod 2026-09-30 (identical keys)
Z3_B = 'bim-proprietary-data'            # Z3 output: results, manifests, heartbeats, stats
Z3_CTL_B = 'annotationprod'              # Z3 control files: jobs.json, report_archives.json, prior index
MOVE_B = 'bim-proprietary-data'          # annotationprod -> bim-proprietary-data move status
Z4 = 'cad-disk-extract/zentitude-data-4'
Z2 = 'cad-disk-extract/zenitude-data-2'
Z3 = 'cad-disk-extract/zenitude-data-3'
Z3_CTL = 'cad-disk-extract/_control/move/z3'
RETRY = {'max_attempts': 20, 'mode': 'standard'}      # the bim bucket throttles (SlowDown) under the extraction load
sess = boto3.Session(profile_name=os.environ.get('PUB_PROFILE', 'bim') or None)   # PUB_PROFILE='' -> instance role (coordinator)
s3 = sess.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries=RETRY))
ec2 = sess.client('ec2', region_name='ap-south-1', config=Config(retries=RETRY))
cache = {}   # results cache: key -> (etag, obj)
PRIVATE = {}  # names for the local-only page
PRIVATE_HTML = os.environ.get('PUB_PRIVATE_HTML', '/Users/dhiren/Downloads/Deccan/zen2/live/private.html')


def get_text(key, bucket):
    try:
        return s3.get_object(Bucket=bucket, Key=key)['Body'].read().decode('utf-8', 'replace')
    except Exception:
        return None


def get_json(key, bucket):
    t = get_text(key, bucket)
    try:
        return json.loads(t) if t else None
    except Exception:
        return None


def list_objs(prefix, bucket):
    out, tok = [], None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += r.get('Contents', [])
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


_jc = {}


def get_json_cached(key, bucket, transform=None):
    """JSON (optionally reduced by `transform`), downloaded again only when its ETag changed (jobs.json is large). None if missing."""
    old = _jc.get((bucket, key))
    try:
        r = s3.get_object(Bucket=bucket, Key=key, **({'IfNoneMatch': old[0]} if old else {}))
    except ClientError as e:
        code = str(e.response.get('Error', {}).get('Code'))
        if code in ('304', 'NotModified') and old:
            return old[1]
        if code in ('NoSuchKey', '404', 'NotFound'):
            return None
        raise
    obj = json.loads(r['Body'].read())
    obj = transform(obj) if transform else obj
    _jc[(bucket, key)] = (r['ETag'], obj)
    return obj


def ts(s):
    return calendar.timegm(time.strptime(s, '%Y-%m-%dT%H:%M:%SZ')) if s else None



# ---- file-kind buckets shared by both disks (same lists as the page) ----
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stats_agg.py')).read()
_ns = {'re': re}
exec(_src[_src.index('CATS = {'):_src.index('def list_keys')], _ns)
cat_of = _ns['cat_of']
G3D = set('stp step ifc ifczip ifcxml db1 db2 nwd nwc nwf rvt rfa dgn sat sab igs iges stl obj fbx 3ds skp 3dm sldprt sldasm ipt iam x_t x_b jt glb gltf vue zvf tbp tsep tczip sdnf cis std'.split())
G2D = set('dwg dxf dg dpm dwf dwfx plt sha sym igr'.split())
GFAB = set('nc1 nc dstv kss xsr abm bom nc2'.split())
KIND_ORDER = ['3D model files', '2D drawing files', 'CAD PDFs (drawings)', 'Non-CAD PDFs (documents)', 'PDFs not yet classified / unreadable',
              'Fabrication / CNC', 'Tekla model files', 'Office / text', 'Images / video', 'Archives', 'Scripts / executables', 'Other']


def kind_of(ext):
    if ext in G3D: return '3D model files'
    if ext in G2D: return '2D drawing files'
    if ext in GFAB: return 'Fabrication / CNC'
    c = cat_of(ext)
    return c if c in KIND_ORDER else 'Other'


def at_a_glance(types, pdf_classes=None):
    """types: [{type, files, bytes, stored_files?, stored_bytes?, in_disk12_files?}] -> rows per kind + total.
    PDFs are split into CAD / non-CAD / unknown by the classifier counts (raw and unique), bytes shared pro rata."""
    rows = {k: {'kind': k, 'files': 0, 'bytes': 0, 'unique_files': 0, 'unique_bytes': 0, 'in_disk12_files': 0} for k in KIND_ORDER}
    pdf = None
    for t in types or []:
        if t['type'] == 'pdf':
            pdf = t; continue
        r = rows[kind_of(t['type'])]
        r['files'] += t.get('files', 0); r['bytes'] += t.get('bytes', 0)
        r['unique_files'] += t.get('stored_files') or 0; r['unique_bytes'] += t.get('stored_bytes') or 0
        r['in_disk12_files'] += t.get('in_disk12_files') or 0
    if pdf:
        cl = (pdf_classes or {}).get('classes') or {}
        g = lambda k, f: (cl.get(k) or {}).get(f, 0)
        raw = {'cad': g('cad', 'raw'), 'doc': g('document', 'raw'), 'unk': g('unknown', 'raw')}
        uni = {'cad': g('cad', 'unique'), 'doc': g('document', 'unique'), 'unk': g('unknown', 'unique')}
        tot_raw, tot_uni = pdf.get('files', 0), pdf.get('stored_files') or 0
        raw['unk'] += max(0, tot_raw - sum(raw.values()))       # not yet classified (classifier lags extraction)
        uni['unk'] += max(0, tot_uni - sum(uni.values()))
        for name, k in (('CAD PDFs (drawings)', 'cad'), ('Non-CAD PDFs (documents)', 'doc'), ('PDFs not yet classified / unreadable', 'unk')):
            share = raw[k] / tot_raw if tot_raw else 0
            ushare = uni[k] / tot_uni if tot_uni else 0
            r = rows[name]; r['files'] += raw[k]; r['unique_files'] += uni[k]
            r['bytes'] += int(pdf.get('bytes', 0) * share); r['unique_bytes'] += int((pdf.get('stored_bytes') or 0) * ushare)
            r['in_disk12_files'] += int((pdf.get('in_disk12_files') or 0) * share)
    out = [rows[k] for k in KIND_ORDER if rows[k]['files']]
    tot = {'kind': 'All files', **{f: sum(r[f] for r in out) for f in ('files', 'bytes', 'unique_files', 'unique_bytes', 'in_disk12_files')}}
    return out + [tot]



COMPARE_ROWS = [('3D', ['stp', 'step', 'ifc', 'ifczip', 'db1', 'db2', 'nwd', 'nwc', 'rvt', 'rfa', 'dgn', 'sat', 'igs', 'iges', 'stl', 'obj', 'skp', 'tbp', 'tsep', 'sldprt', '3dm']),
                ('2D', ['dwg', 'dxf', 'dg', 'dpm', 'dwf', 'plt']),
                ('Fabrication', ['nc1', 'nc', 'kss', 'xsr', 'abm'])]


def comparison(by_ext, d12, pdfc):
    """Disk-1 / Disk-2 / combined vs data-4 (total and NEW = content not already stored by Disk-1/2), per type."""
    ext = {t['type']: t for t in by_ext or []}
    dt = (d12 or {}).get('by_type', {})
    rows = []

    def mk(label, group, e_list, d_keys):
        r = {'type': label, 'group': group, 'disk1_raw': 0, 'disk2_raw': 0, 'disk1_unique': 0, 'disk2_unique': 0, 'combined_unique': 0,
             'd4_raw': 0, 'd4_unique': 0, 'd4_new_raw': 0, 'd4_new_unique': 0}
        for k in d_keys:
            x = dt.get(k) or {}
            for f in ('disk1_raw', 'disk2_raw', 'disk1_unique', 'disk2_unique', 'combined_unique'):
                r[f] += x.get(f, 0)
        for e in e_list:
            t = ext.get(e) or {}
            r['d4_raw'] += t.get('files', 0); r['d4_unique'] += t.get('stored_files') or 0
            r['d4_new_raw'] += max(0, t.get('files', 0) - (t.get('in_disk12_files') or 0))
            r['d4_new_unique'] += max(0, (t.get('stored_files') or 0) - (t.get('in_disk12_unique') or 0))
        return r

    for group, exts in COMPARE_ROWS:
        g = []
        for e in exts:
            if (ext.get(e) or {}).get('files') or (dt.get(e) or {}).get('combined_unique'):
                g.append(mk('.' + e, group, [e], [e]))
        rows += g
        if g:
            tot = {'type': f'All {group} (listed types)', 'group': group, 'total': True}
            for f in ('disk1_raw', 'disk2_raw', 'disk1_unique', 'disk2_unique', 'combined_unique', 'd4_raw', 'd4_unique', 'd4_new_raw', 'd4_new_unique'):
                tot[f] = sum(r[f] for r in g)
            rows.append(tot)
    # PDFs: CAD vs non-CAD (data-4: our classifier; Disk-1/2: that run's classifier)
    cl = (pdfc or {}).get('classes') or {}
    pdf_all = ext.get('pdf') or {}
    for label, dkey, ckeys in (('CAD PDFs (drawings)', 'cad_pdf', ['cad']), ('Non-CAD PDFs (documents)', 'other_pdf', ['document']),
                               ('PDFs not yet classified / unreadable', None, ['unknown', 'pending'])):
        x = dt.get(dkey) or {} if dkey else {}
        r = {'type': label, 'group': 'PDF', 'disk1_raw': x.get('disk1_raw', 0), 'disk2_raw': x.get('disk2_raw', 0),
             'disk1_unique': x.get('disk1_unique', 0), 'disk2_unique': x.get('disk2_unique', 0), 'combined_unique': x.get('combined_unique', 0),
             'd4_raw': sum((cl.get(k) or {}).get('raw', 0) for k in ckeys), 'd4_unique': sum((cl.get(k) or {}).get('unique', 0) for k in ckeys),
             'd4_new_raw': sum((cl.get(k) or {}).get('new_raw', 0) for k in ckeys), 'd4_new_unique': sum((cl.get(k) or {}).get('new_unique', 0) for k in ckeys)}
        rows.append(r)
    classified_raw = sum(r['d4_raw'] for r in rows if r['group'] == 'PDF')
    if pdf_all.get('files', 0) > classified_raw:     # PDFs extracted after the classifier's last round
        last = rows[-1]; last['d4_raw'] += pdf_all['files'] - classified_raw
        last['d4_unique'] += max(0, (pdf_all.get('stored_files') or 0) - sum(r['d4_unique'] for r in rows if r['group'] == 'PDF'))
    # everything data-4 has that Disk-1/2 never extracted (non-CAD types): all new
    listed = {e for _, es in COMPARE_ROWS for e in es} | {'pdf'}
    others = [t for t in by_ext or [] if t['type'] not in listed]
    rows.append({'type': 'All other file types (Disk-1/2 did not extract these)', 'group': 'Other', 'disk1_raw': 0, 'disk2_raw': 0,
                 'disk1_unique': 0, 'disk2_unique': 0, 'combined_unique': 0,
                 'd4_raw': sum(t['files'] for t in others), 'd4_unique': sum(t.get('stored_files') or 0 for t in others),
                 'd4_new_raw': sum(max(0, t['files'] - (t.get('in_disk12_files') or 0)) for t in others),
                 'd4_new_unique': sum(max(0, (t.get('stored_files') or 0) - (t.get('in_disk12_unique') or 0)) for t in others)})
    return {'rows': rows, 'disk12_note': (d12 or {}).get('note'), 'disk12_updated': (d12 or {}).get('updated')}


def z4_stats():
    jobs = get_json(f'{Z4}/_control/jobs.json', Z4_B) or []
    total_bytes = sum(j['size'] for j in jobs)
    objs = [o for o in list_objs(f'{Z4}/_state/results/', Z4_B) if o['Key'].endswith('.json')]
    todo = [o for o in objs if cache.get(o['Key'], (None,))[0] != o['ETag']]
    with ThreadPoolExecutor(32) as ex:
        for o, r in zip(todo, ex.map(lambda o: get_json(o['Key'], Z4_B), todo)):
            if r:
                cache[o['Key']] = (o['ETag'], r)
    rs = [cache[o['Key']][1] for o in objs if o['Key'] in cache]
    agg = {k: sum(r.get(k, 0) or 0 for r in rs) for k in
           ('files', 'bytes', 'stored_files', 'stored_bytes', 'dedup_files', 'dedup_bytes', 'nested_count',
            'encrypted_nested', 'ransomware_files', 'zero_byte_files', 'upload_error_count')}
    status = {}
    for r in rs:
        status[r['status']] = status.get(r['status'], 0) + 1
    done_src = sum(r.get('size') or 0 for r in rs)
    # throughput over the last 20 minutes of finished archives
    now = time.time() + time.timezone * 0
    fin = sorted((ts(r['finished']), r.get('size') or 0) for r in rs if r.get('finished'))
    recent = [s for t, s in fin if t and t > time.time() - 1200]
    rate = sum(recent) / 1200 if recent else 0
    eta = (total_bytes - done_src) / rate if rate and total_bytes and done_src / total_bytes >= 0.2 else None  # early rates only see small archives
    hosts, running, running_named = [], [], []
    import datetime
    fresh = [o for o in list_objs(f'{Z4}/_state/hosts/', Z4_B)
             if (datetime.datetime.now(datetime.timezone.utc) - o['LastModified']).total_seconds() < 900]
    with ThreadPoolExecutor(48) as ex:
        hbs = list(ex.map(lambda o: (o, get_json(o['Key'], Z4_B)), fresh))
    for o, h in hbs:
        if not h:
            continue
        age = time.time() - ts(h['updated'])
        h['_age'] = age
        hosts.append({'alive': age < 180, 'host': h.get('host', o['Key']), 'done': h.get('done', 0), 'failed': h.get('failed', 0)})
        if age < 180:
            for v in h.get('running', {}).values():
                running.append({'phase': v.get('phase'), 'size': v.get('size'), 'files_total': v.get('files_total'),
                                'files_uploaded': v.get('files_uploaded')})
                running_named.append(dict(v, box=h.get('host', '')[:15]))
    bands = {}
    done_ids = {r['id'] for r in rs}
    phases = {}
    for j in jobs:
        x = phases.setdefault(j.get('phase', 'A'), {'archives': 0, 'bytes': 0, 'done': 0, 'done_bytes': 0})
        x['archives'] += 1; x['bytes'] += j['size']
        if j['id'] in done_ids:
            x['done'] += 1; x['done_bytes'] += j['size']
    for j in jobs:
        b = '>=20 GB' if j['size'] >= 20e9 else '1-20 GB' if j['size'] >= 1e9 else '<1 GB'
        x = bands.setdefault(b, {'archives': 0, 'done': 0, 'bytes': 0, 'done_bytes': 0})
        x['archives'] += 1; x['bytes'] += j['size']
        if j['id'] in done_ids:
            x['done'] += 1; x['done_bytes'] += j['size']
    c1 = get_json(f'{Z4}/_state/copy_source.json', Z4_B) or {}
    c2 = get_json(f'{Z4}/_state/copy_source_rest.json', Z4_B) or {}
    copy = {k: (c1.get(k) or 0) + (c2.get(k) or 0) for k in ('total_objects', 'done_objects', 'skipped_objects', 'done_bytes', 'total_bytes')}
    copy.update(updated=max(c1.get('updated') or '', c2.get('updated') or ''), final=bool(c1.get('final')) and bool(c2.get('final')))
    loose = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'z4_loose_types.json')))
    ext = get_json(f'{Z4}/_state/stats/ext_summary.json', Z4_B) or {}
    pdfc = get_json(f'{Z4}/_state/stats/pdf_classes.json', Z4_B) or {}
    fv = get_json(f'{Z4}/_state/final_verify.json', Z4_B) or {}
    ma = get_json(f'{Z4}/_state/audit/marker_missing.json', Z4_B) or {}
    marker_audit = None
    if ma:
        rjobs = get_json(f'{Z4}/_control/repair_jobs.json', Z4_B) or []
        rres = [get_json(o['Key'], Z4_B) or {} for o in list_objs(f'{Z4}/_state/repair_results/', Z4_B)]
        marker_audit = {'checked_at': ma.get('updated'), 'checked': ma.get('candidates'), 'missing': len(ma.get('missing', {})),
                        'missing_bytes': sum(t[1] for j in rjobs for t in j['targets'].values()),
                        'archives': len(rjobs), 'archives_done': len(rres),
                        'restored': sum((r.get('uploaded') or 0) + (r.get('already_present') or 0) for r in rres),
                        'not_found': sum(r.get('not_found_count') or 0 for r in rres)}
        after = get_json(f'{Z4}/_state/audit/marker_missing_after_repair.json', Z4_B)
        if after:
            marker_audit.update(recheck_at=after.get('updated'), recheck_checked=after.get('candidates'), recheck_missing=len(after.get('missing', {})))
    d12 = get_json(f'{Z4}/_state/stats/disk12_by_type.json', Z4_B) or {}
    conv = get_json(f'{Z4}/_state/conv_status.json', Z4_B) or {}
    PRIVATE['z4_running'] = [dict(r) for r in running_named]
    PRIVATE['z4_archives'] = (get_json(f'{Z4}/_state/stats/archives.json', Z4_B) or {}).get('archives', [])
    return {
        'label': 'Disk Z4 (Tekla office backup SSD)',
        'source_objects': 53443, 'source_bytes': 7899025193627, 'source_archives': 1499,
        'new_archives': len(jobs), 'new_archive_bytes': total_bytes, 'phases': phases,
        'loose_files': sum(t['files'] for t in loose), 'loose_bytes': sum(t['bytes'] for t in loose), 'loose_file_types': loose,
        'duplicate_archives_of_disk1': 1154, 'duplicate_archive_bytes': 6124000000000,
        'archives_done': len(rs), 'archives_status': status, 'source_bytes_done': done_src,
        **agg, 'rate_source_bytes_per_s_20min': rate, 'eta_s': eta,
        'size_bands': bands, 'running': running, 'boxes_alive': len({h['host'] for h in hosts if h['alive']}), 'worker_processes_alive': sum(h['alive'] for h in hosts), 'boxes_seen': len({h['host'] for h in hosts}),
        'file_types': {'updated': ext.get('updated'), 'archives_counted': ext.get('archives_counted'),
                       'distinct_extensions': ext.get('distinct_extensions'), 'max_nested_depth': ext.get('max_nested_depth'),
                       'by_category': ext.get('by_category', []), 'by_extension': ext.get('by_extension', []),
                       'unique_rule': ext.get('unique_rule'), 'totals': ext.get('totals'),
                       'verify': ext.get('verify'), 'verify_rule': ext.get('verify_rule')},
        'pdf_classes': {k: pdfc.get(k) for k in ('updated', 'pdf_paths', 'pdf_unique', 'classes', 'rule')},
        'at_a_glance': at_a_glance(ext.get('by_extension', []), pdfc),
        'comparison': comparison(ext.get('by_extension', []), d12, pdfc),
        'source_identity': get_json(f'{Z4}/_state/audit/src_identity_summary.json', Z4_B),
        'conversions': conv,
        'state': 'complete' if len(rs) >= len(jobs) and jobs else 'extracting',
        'final_verify': {k: fv.get(k) for k in ('checked_at', 'jobs', 'results', 'status', 'completeness_vs_drive_report', 'source_objects_on_drive',
                                                'source_objects_copied', 'source_missing_count', 'error_records', 'totals', 'max_nested_depth',
                                                'distinct_extensions')} | {'marker_audit': marker_audit} if fv else None,
        'loose_at_a_glance': at_a_glance(loose, None),
        'raw_copy': {k: copy.get(k) for k in ('total_objects', 'done_objects', 'skipped_objects', 'done_bytes', 'total_bytes', 'updated', 'final')},
    }


# ---------------------------------------------- Z3: Zenitude-data-3 ----------------------------------------------
Z3_LABEL = 'Disk Z3 (steel-detailing job archive SSD: SDS2 + Tekla)'
Z3_SOURCE = {   # totals from the drive report of Zenitude-data-3 (numbers only)
    'files_on_drive': 770652, 'bytes_on_drive': 4233237175352, 'archives': 2980, 'archive_bytes': 3980433507353,
    'files_in_archives': 251295857, 'uncompressed_bytes': 10679524187696, 'loose_files': 767672, 'extensions': 1369,
    'nested_archives': 54620, 'nested_bytes': 1212777124221, 'sds2_jobs': 3631, 'sds2_distinct': 1932, 'sds2_files': 245644490,
    'sds2_bytes': 6349685713483, 'sds2_members': 19680207, 'tekla_models': 77, 'encrypted_archives': 25}
Z3_KEEP = ('id', 'type', 'status', 'size', 'files', 'bytes', 'stored_files', 'stored_bytes', 'dedup_files', 'dedup_bytes',
           'already_in_disk12_files', 'already_in_disk12_bytes', 'nested_count', 'encrypted_nested', 'ransomware_files',
           'zero_byte_files', 'upload_error_count', 'source_files', 'finished')
Z3_RATE_WINDOW, Z3_ETA_MIN = 1800, 0.15
_KNOWN_EXT = set(_ns['EXT2CAT']) | G3D | G2D | GFAB | {'(none)', '(other)', 'j###', 'm###', 'p_*'}
LAST = {}


def z3_jobs_compact(jobs):
    out = {}
    for j in jobs or []:
        if j.get('type') == 'loose':
            ks = j.get('keys') or []
            out[j['id']] = {'loose': True, 'bytes': j.get('size') or sum(k[1] or 0 for k in ks),
                            'files': j['files'] if j.get('files') is not None else len(ks)}
        else:
            out[j['id']] = {'loose': False, 'bytes': j.get('size') or 0}
    return out


def z3_slim(r):
    s = {k: r.get(k) for k in Z3_KEEP if k in r}
    s['max_depth'] = max([int(x.get('depth') or 0) for x in r.get('nested') or []] or [0])
    return s


def z3_progress(jobs, rs):
    arch = [(i, j) for i, j in jobs.items() if not j['loose']]
    loose = [(i, j) for i, j in jobs.items() if j['loose']]
    p = {'jobs_total': len(jobs), 'jobs_done': len(rs),
         'archive_jobs_total': len(arch), 'archive_jobs_done': sum(1 for i, _ in arch if i in rs),
         'archive_bytes_total': sum(j['bytes'] for _, j in arch), 'archive_bytes_done': sum(j['bytes'] for i, j in arch if i in rs),
         'loose_jobs_total': len(loose), 'loose_jobs_done': sum(1 for i, _ in loose if i in rs),
         'loose_files_total': sum(j['files'] for _, j in loose), 'loose_files_done': sum(rs[i].get('files') or 0 for i, _ in loose if i in rs),
         'loose_bytes_total': sum(j['bytes'] for _, j in loose), 'loose_bytes_done': sum(j['bytes'] for i, j in loose if i in rs)}
    p['bytes_total'] = p['archive_bytes_total'] + p['loose_bytes_total']
    p['bytes_done'] = p['archive_bytes_done'] + p['loose_bytes_done']
    recent = [(jobs.get(i) or {}).get('bytes', r.get('size') or 0) for i, r in rs.items() if (ts(r.get('finished')) or 0) > time.time() - Z3_RATE_WINDOW]
    rate = sum(recent) / Z3_RATE_WINDOW if recent else 0
    frac = p['bytes_done'] / p['bytes_total'] if p['bytes_total'] else 0
    p.update(rate_bytes_per_s=rate, rate_window_s=Z3_RATE_WINDOW, eta_min_fraction=Z3_ETA_MIN,
             eta_s=0 if frac >= 1 else ((p['bytes_total'] - p['bytes_done']) / rate if rate and frac >= Z3_ETA_MIN else None),
             status={k: sum(1 for r in rs.values() if r.get('status') == k) for k in {r.get('status') for r in rs.values()}},
             complete=bool(jobs) and all(i in rs for i in jobs))
    return p


def z3_glance(types, pdfc, totals=None):
    """Rows per kind with raw / unique / new (not in Disk-1, Disk-2 or Z4). PDFs split exactly by the worker's classification.
    The 'All files' row counts each distinct content once (totals.unique_files), so it can be below the sum of the rows."""
    F = ('files', 'bytes', 'unique_files', 'unique_bytes', 'new_files', 'new_unique', 'new_unique_bytes')
    rows = {k: dict({'kind': k}, **{f: 0 for f in F}) for k in KIND_ORDER}
    pdf = None
    for t in types or []:
        if t['type'] == 'pdf':
            pdf = t; continue
        r = rows[kind_of(t['type'])]
        for f in F:
            r[f] += t.get(f) or 0
    if pdf:
        cl = (pdfc or {}).get('classes') or {}
        for name, keys in (('CAD PDFs (drawings)', ['cad']), ('Non-CAD PDFs (documents)', ['document']),
                           ('PDFs not yet classified / unreadable', ['unknown', 'pending'])):
            r = rows[name]
            for k in keys:
                c = cl.get(k) or {}
                for f, g in (('files', 'raw'), ('bytes', 'raw_bytes'), ('unique_files', 'unique'), ('unique_bytes', 'unique_bytes'),
                             ('new_files', 'new_raw'), ('new_unique', 'new_unique'), ('new_unique_bytes', 'new_unique_bytes')):
                    r[f] += c.get(g) or 0
        u = rows['PDFs not yet classified / unreadable']   # stats written in the same round agree; guard against a lagging file
        for f in F:
            u[f] += max(0, (pdf.get(f) or 0) - sum(rows[k][f] for k in ('CAD PDFs (drawings)', 'Non-CAD PDFs (documents)', 'PDFs not yet classified / unreadable')))
    out = [rows[k] for k in KIND_ORDER if rows[k]['files']]
    tot = {'kind': 'All files', **{f: sum(r[f] for r in out) for f in F}}
    if totals and totals.get('unique_files') is not None:
        tot.update({f: totals.get(f) or 0 for f in ('unique_files', 'unique_bytes', 'new_unique', 'new_unique_bytes')}, distinct=True)
    return out + [tot]


def z3_comparison(e3_rows, pdf3, d12, e4_rows, pdf4, tot3=None, prior=None):
    """Per type: Disk-1+2 unique, Z4 unique and what Z4 added (new vs Disk-1/2), earlier disks together, then Z3 raw / unique / new."""
    e3 = {t['type']: t for t in e3_rows or []}
    e4 = {t['type']: t for t in e4_rows or []}
    dt = (d12 or {}).get('by_type', {})
    F = ('d12_unique', 'z4_unique', 'z4_new_unique', 'earlier_unique', 'z3_raw', 'z3_unique', 'z3_new_raw', 'z3_new_unique')

    def mk(label, group, exts):
        r = {'type': label, 'group': group, **{f: 0 for f in F}}
        for e in exts:
            x, a, b = dt.get(e) or {}, e4.get(e) or {}, e3.get(e) or {}
            r['d12_unique'] += x.get('combined_unique', 0)
            r['z4_unique'] += a.get('stored_files') or 0
            r['z4_new_unique'] += max(0, (a.get('stored_files') or 0) - (a.get('in_disk12_unique') or 0))
            r['z3_raw'] += b.get('files', 0); r['z3_unique'] += b.get('unique_files', 0)
            r['z3_new_raw'] += b.get('new_files', 0); r['z3_new_unique'] += b.get('new_unique', 0)
        r['earlier_unique'] = r['d12_unique'] + r['z4_new_unique']
        return r
    rows = []
    for group, exts in COMPARE_ROWS:
        g = [mk('.' + e, group, [e]) for e in exts if (e3.get(e) or {}).get('files') or (dt.get(e) or {}).get('combined_unique') or (e4.get(e) or {}).get('files')]
        rows += g
        if g:
            rows.append(dict({'type': f'All {group} (listed types)', 'group': group, 'total': True}, **{f: sum(r[f] for r in g) for f in F}))
    c3, c4 = (pdf3 or {}).get('classes') or {}, (pdf4 or {}).get('classes') or {}
    for label, dkey, ks in (('CAD PDFs (drawings)', 'cad_pdf', ['cad']), ('Non-CAD PDFs (documents)', 'other_pdf', ['document']),
                            ('PDFs not yet classified / unreadable', None, ['unknown', 'pending'])):
        x = (dt.get(dkey) or {}) if dkey else {}
        s = lambda cl, f: sum((cl.get(k) or {}).get(f, 0) for k in ks)
        r = {'type': label, 'group': 'PDF', 'd12_unique': x.get('combined_unique', 0), 'z4_unique': s(c4, 'unique'), 'z4_new_unique': s(c4, 'new_unique'),
             'z3_raw': s(c3, 'raw'), 'z3_unique': s(c3, 'unique'), 'z3_new_raw': s(c3, 'new_raw'), 'z3_new_unique': s(c3, 'new_unique')}
        r['earlier_unique'] = r['d12_unique'] + r['z4_new_unique']
        rows.append(r)
    listed = {e for _, es in COMPARE_ROWS for e in es} | {'pdf'}
    o3 = [t for t in e3_rows or [] if t['type'] not in listed]
    o4 = [t for t in e4_rows or [] if t['type'] not in listed]
    r = {'type': 'All other file types (Disk-1/2 did not extract these)', 'group': 'Other', 'd12_unique': 0,
         'z4_unique': sum(t.get('stored_files') or 0 for t in o4),
         'z4_new_unique': sum(max(0, (t.get('stored_files') or 0) - (t.get('in_disk12_unique') or 0)) for t in o4),
         'z3_raw': sum(t.get('files', 0) for t in o3), 'z3_unique': sum(t.get('unique_files', 0) for t in o3),
         'z3_new_raw': sum(t.get('new_files', 0) for t in o3), 'z3_new_unique': sum(t.get('new_unique', 0) for t in o3)}
    r['earlier_unique'] = r['z4_new_unique']
    rows.append(r)
    if tot3:
        pr = prior or {}
        rows.append({'type': 'All files (each distinct content once)', 'group': 'All', 'total': True, 'd12_unique': pr.get('disk12'),
                     'z4_unique': None, 'z4_new_unique': (pr['distinct_total'] - pr['disk12']) if pr.get('distinct_total') and pr.get('disk12') else None,
                     'earlier_unique': pr.get('distinct_total'), 'z3_raw': tot3.get('files'), 'z3_unique': tot3.get('unique_files'),
                     'z3_new_raw': tot3.get('new_files'), 'z3_new_unique': tot3.get('new_unique')})
    return {'rows': rows, 'disk12_note': (d12 or {}).get('note'),
            'rule': 'unique = distinct sha256 per type; earlier disks = Disk-1+2 unique + what Z4 added; new in Z3 = content not in the Disk-1/Disk-2/Z4 index'}


def public_ext_rows(rows, min_files=1000):
    """Extension list for the public page. Long unknown 'extensions' are often fragments of a file or person name, so any type
    that is not a known extension, is longer than 4 characters and has fewer than `min_files` files is folded into one row."""
    keep, rare = [], None
    for t in rows or []:
        e = t['type']
        if e in _KNOWN_EXT or len(e) <= 4 or (t.get('files') or 0) >= min_files:
            keep.append(t); continue
        if rare is None:
            rare = {'type': f'(other long extensions, fewer than {min_files:,} files each)', 'extensions': 0}
        rare['extensions'] += 1
        for k, v in t.items():
            if k != 'type' and isinstance(v, (int, float)):
                rare[k] = rare.get(k, 0) + v
    return keep + ([rare] if rare else [])


def z3_heartbeats():
    import datetime
    fresh = [o for o in list_objs(f'{Z3}/_state/hosts/', Z3_B)
             if (datetime.datetime.now(datetime.timezone.utc) - o['LastModified']).total_seconds() < 900]
    with ThreadPoolExecutor(32) as ex:
        hbs = list(ex.map(lambda o: (o, get_json(o['Key'], Z3_B)), fresh))
    hosts, running, named = [], [], []
    for o, h in hbs:
        if not h or not h.get('updated'):
            continue
        age = time.time() - ts(h['updated'])
        hosts.append({'alive': age < 180, 'host': h.get('host', o['Key'])})
        if age < 180:
            for v in (h.get('running') or {}).values():
                running.append({'phase': v.get('phase'), 'size': v.get('size'), 'files_total': v.get('files_total'),
                                'files_uploaded': v.get('files_uploaded')})
                named.append(dict(v, box=h.get('host', '')[:15]))
    return hosts, running, named


def z3_add_sds2_cmp(cmp, sds):
    """SDS2 models are job folders, not a file extension: add one 3D row counting job folders (raw / unique / new)."""
    if not sds or not isinstance(cmp, dict):
        return cmp
    rows = cmp.get('rows') or []
    row = {'type': 'SDS2 jobs (job folders)', 'group': '3D', 'd12_unique': None, 'z4_unique': 173, 'z4_new_unique': None,   # Z4: 173 distinct SDS2 job folders (conversion job list)
           'earlier_unique': None, 'z3_raw': sds.get('jobs_raw'), 'z3_unique': sds.get('jobs_unique'),
           'z3_new_raw': None, 'z3_new_unique': sds.get('jobs_new_unique')}
    idx = next((i for i, r in enumerate(rows) if r.get('group') == '3D' and str(r.get('type', '')).startswith('All')), len(rows))
    rows.insert(idx, row)
    cmp['rows'] = rows
    return cmp


def z3_add_sds2_glance(glance, sds):
    if not sds or not isinstance(glance, list):
        return glance
    row = {'kind': 'SDS2 job folders: files inside', 'files': sds.get('files'), 'bytes': sds.get('bytes'),
           'unique_files': None, 'unique_bytes': None, 'new_files': sds.get('files_new'), 'new_unique': None, 'new_unique_bytes': None,
           'jobs_raw': sds.get('jobs_raw'), 'jobs_unique': sds.get('jobs_unique'), 'jobs_new_unique': sds.get('jobs_new_unique')}
    idx = next((i + 1 for i, r in enumerate(glance) if r.get('kind') == '3D model files'), 0)
    glance.insert(idx, row)
    return glance


def z3_stats(z4=None, fl=None):
    jobs = get_json_cached(f'{Z3_CTL}/jobs.json', Z3_CTL_B, z3_jobs_compact) or {}
    objs = [o for o in list_objs(f'{Z3}/_state/results/', Z3_B) if o['Key'].endswith('.json')]
    todo = [o for o in objs if cache.get(o['Key'], (None,))[0] != o['ETag']]
    with ThreadPoolExecutor(32) as ex:
        for o, r in zip(todo, ex.map(lambda o: get_json(o['Key'], Z3_B), todo)):
            if r:
                cache[o['Key']] = (o['ETag'], z3_slim(r))
    rs = {}
    for o in objs:
        if o['Key'] in cache:
            r = cache[o['Key']][1]
            jid = r.get('id') or o['Key'].rsplit('/', 1)[-1][:-5]
            if not jobs or jid in jobs:
                rs[jid] = r
    prog = z3_progress(jobs, rs)
    agg = {k: sum(r.get(k) or 0 for r in rs.values()) for k in
           ('files', 'bytes', 'stored_files', 'stored_bytes', 'dedup_files', 'dedup_bytes', 'already_in_disk12_files', 'nested_count',
            'encrypted_nested', 'ransomware_files', 'zero_byte_files', 'upload_error_count')}
    agg['prior_files'] = agg.pop('already_in_disk12_files')
    agg['max_nested_depth'] = max([r.get('max_depth') or 0 for r in rs.values()] or [0])
    hosts, running, named = z3_heartbeats()
    ext = get_json(f'{Z3}/_state/stats/ext_summary.json', Z3_B) or {}
    pdfc = get_json(f'{Z3}/_state/stats/pdf_classes.json', Z3_B) or {}
    d12 = get_json(f'{Z4}/_state/stats/disk12_by_type.json', Z4_B) or {}
    prior = get_json_cached(f'{Z3_CTL}/prior_sha64.json', Z3_CTL_B) or {}
    z4ft = (z4 or {}).get('file_types') or {}
    e4 = z4ft.get('by_extension') or (get_json_cached(f'{Z4}/_state/stats/ext_summary.json', Z4_B) or {}).get('by_extension', [])
    p4 = (z4 or {}).get('pdf_classes') or get_json_cached(f'{Z4}/_state/stats/pdf_classes.json', Z4_B) or {}
    state = 'waiting' if not jobs else 'complete' if prog['complete'] else 'extracting'
    fv = get_json(f'{Z3}/_state/stats/final_verify.json', Z3_B) if state == 'complete' else None
    au = get_json(f'{Z3}/_state/stats/audit_objects.json', Z3_B) if state == 'complete' else None   # object audit (counts only)
    au = {k: au.get(k) for k in ('checked_at', 'archive_jobs', 'totals', 'total_bytes', 'problem_job_count')} if au else None
    by_ext = ext.get('by_extension', [])
    mach = {'instances': 0, 'vcpu': 0, 'regions': {}}
    for g, x in (fl or {}).items():
        if g.startswith('Z3 '):
            mach['instances'] += x['instances']; mach['vcpu'] += x['vcpu']; mach['regions'][g] = x['instances']
    PRIVATE['z3_running'] = named
    PRIVATE['z3_archives'] = (get_json(f'{Z3}/_state/stats/archives.json', Z3_B) or {}).get('archives', [])
    return {
        'label': Z3_LABEL, 'state': state, 'source': Z3_SOURCE, 'progress': prog, 'totals': agg,
        'running': running, 'boxes_alive': len({h['host'] for h in hosts if h['alive']}),
        'worker_processes_alive': sum(h['alive'] for h in hosts), 'machines': mach,
        'file_types': {**{k: ext.get(k) for k in ('updated', 'jobs_counted', 'archive_jobs_counted', 'loose_jobs_counted', 'rows_counted',
                                                   'distinct_extensions', 'max_nested_depth', 'unique_rule', 'new_rule', 'totals',
                                                   'archive_members', 'nested', 'verify', 'verify_rule', 'verify_report_listing_incomplete',
                                                   'verify_files', 'report_loaded')},
                       'by_category': ext.get('by_category', []), 'by_extension': public_ext_rows(by_ext)},
        'pdf_classes': {k: pdfc.get(k) for k in ('updated', 'pdf_paths', 'pdf_unique', 'pdf_new_unique', 'classes', 'rule')},
        'at_a_glance': z3_add_sds2_glance(z3_glance(by_ext, pdfc, ext.get('totals')), ext.get('sds2')),
        'comparison': z3_add_sds2_cmp(z3_comparison(by_ext, pdfc, d12, e4, p4, ext.get('totals'), prior), ext.get('sds2')),
        'sds2': ext.get('sds2'),
        'loose': {'files_listed': prog['loose_files_total'], 'bytes_listed': prog['loose_bytes_total'], 'files_hashed': prog['loose_files_done'],
                  'totals': ext.get('loose'), 'at_a_glance': z3_glance(ext.get('loose_by_extension', []), pdfc.get('loose'), ext.get('loose')),
                  'by_extension': public_ext_rows(ext.get('loose_by_extension', []))},
        'final_verify': fv,
        'audit': au,
        'conversions': z3_conv_status(),   # STEP conversions + 3-class grading (counts only)
    }


def move_stats():
    """annotationprod -> bim-proprietary-data move: chunks done / planned, objects and bytes copied, verified, mismatches."""
    plan = get_json_cached('cad-disk-extract/_control/move/plan.json', MOVE_B) or {}
    objs = [o for o in list_objs('cad-disk-extract/_state/move/results/', MOVE_B) if o['Key'].endswith('.json')]
    todo = [o for o in objs if cache.get(o['Key'], (None,))[0] != o['ETag']]
    with ThreadPoolExecutor(32) as ex:
        for o, r in zip(todo, ex.map(lambda o: get_json(o['Key'], MOVE_B), todo)):
            if r:
                cache[o['Key']] = (o['ETag'], {k: r.get(k) for k in ('objects', 'bytes', 'verified', 'mismatch', 'shard_errors', 'finished')}
                                   | {'shards': len(r.get('shards') or [])})
    rs = [cache[o['Key']][1] for o in objs if o['Key'] in cache]
    if not plan and not rs:
        return None
    out = {'chunks_total': plan.get('chunks'), 'shards_total': plan.get('shards'), 'chunks_done': len(rs),
           'updated': max([r.get('finished') or '' for r in rs] or ['']) or None}
    out.update({k: sum(r.get(k) or 0 for r in rs) for k in ('shards', 'objects', 'bytes', 'verified', 'mismatch', 'shard_errors')})
    out['shards_done'] = out.pop('shards')
    return out


def model_drawings():
    parts = [get_json(o['Key'], Z2_B) for o in list_objs(f'{Z2}/_state/model_drawings_status/', Z2_B) if o['Key'].endswith('.json')]
    parts = [x for x in parts if x]
    if not parts:
        return {}
    bt = {}
    for x in parts:
        for t, v in (x.get('by_type') or {}).items():
            b = bt.setdefault(t, {'documents': 0, 'bytes': 0}); b['documents'] += v['documents']; b['bytes'] += v['bytes']
    return {'documents_total': sum(x.get('documents_total', 0) for x in parts), 'documents_exported': sum(x.get('documents_exported', 0) for x in parts),
            'files_written': sum(x.get('files_written', 0) for x in parts), 'unzip_errors': sum(x.get('unzip_errors', 0) for x in parts),
            'final': all(x.get('final') for x in parts) and len(parts) == 8, 'by_type': bt,
            'updated': max(x.get('updated', '') for x in parts)}


_cnt_cache = {}


def count_suffix(prefix, suffix):
    """Number of objects under prefix ending in suffix (cached 10 min; these folders are small)."""
    c = _cnt_cache.get(prefix)                       # cache the key list per prefix; count each suffix from it
    if not c or time.time() - c[0] >= 600:
        c = _cnt_cache[prefix] = (time.time(), [o['Key'].lower() for o in list_objs(prefix, Z2_B)])
    return sum(1 for k in c[1] if k.endswith(suffix))


def z2_stats():
    marks = get_text(f'{Z2}/_state/boot_marks.log', Z2_B) or ''
    rlog = get_text(f'{Z2}/db/restore.log', Z2_B) or ''
    dbs = {}
    for m in re.finditer(r'restore (MLNG@1_\w+) rc=(\d+) in (\d+) s', rlog):
        dbs[m.group(1)] = {'rc': int(m.group(2)), 'seconds': int(m.group(3))}
    inv = {}
    for m in re.finditer(r'inventory (MLNG@1_\w+): (\d+) tables, (\d+) views', rlog):
        inv[m.group(1)] = {'tables': int(m.group(2)), 'views': int(m.group(3))}
    names = {'MLNG@1_SDB': 'site', 'MLNG@1_SDB_SCHEMA': 'site schema', 'MLNG@1_CDB': 'catalog',
             'MLNG@1_CDB_SCHEMA': 'catalog schema', 'MLNG@1_MDB': 'model (167 GB backup)'}
    databases = [{'name': names[k], 'restored': dbs.get(k, {}).get('rc') == 0, 'restore_s': dbs.get(k, {}).get('seconds'),
                  **inv.get(k, {})} for k in names]
    flog = get_text(f'{Z2}/_state/files_jobs.log', Z2_B) or ''
    def grab(pat, cast=int):
        m = re.findall(pat, flog)
        return cast(m[-1]) if m else None
    files = {
        'source_files': grab(r'sha256 done: (\d+) files'), 'distinct_files': grab(r'files, (\d+) distinct'),
        'duplicate_groups': grab(r'duplicate groups: (\d+)'),
        'sharedcontent_files': grab(r'SharedContent unpacked rc=\d+ in \d+s: (\d+) files'),
        'dxf_ok': grab(r'DWG->DXF \(LibreDWG\): ok=(\d+)'), 'dxf_failed': grab(r'DWG->DXF \(LibreDWG\): ok=\d+ failed=(\d+)'),
        'pdf_pages_png': grab(r'PDF->PNG: (\d+) pages'), 'pdfs': grab(r'pages from (\d+) PDFs'),
        'done': 'files jobs DONE' in flog,
    }
    model_pulled = 'model pulled' in marks
    # local-only details (never in sources.json)
    deep = get_text(f'{Z2}/_state/deep.log', Z2_B) or ''
    exp = get_text(f'{Z2}/json/db/_export.log', Z2_B) or ''
    per_db = {}
    for m in re.finditer(r'(MLNG@1_\w+)\.\S+ rows=(\d+) exported=(\d+)', exp):
        d = per_db.setdefault(m.group(1), [0, 0, 0]); d[0] += 1; d[1] += int(m.group(2)); d[2] += int(m.group(3))
    PRIVATE['z2_detail'] = {'deep_log': deep.splitlines()[-12:], 'db_export': per_db,
                            'pdf_classes': get_json(f'{Z2}/_state/stats/pdf_classes.json', Z2_B),
                            'extracted_types': (get_json(f'{Z2}/_state/stats/extracted_types.json', Z2_B) or [])[:40],
                            'model_3d': get_json(f'{Z2}/_state/s3d3d_status.json', Z2_B)}
    ext = get_json(f'{Z2}/_state/stats/ext_summary.json', Z2_B) or {}
    x_types = get_json(f'{Z2}/_state/stats/extracted_types.json', Z2_B) or []
    pdfc2 = get_json(f'{Z2}/_state/stats/pdf_classes.json', Z2_B) or {}
    s3d = (get_json(f'{Z2}/_state/s3d3d_status.json', Z2_B) or {}).get('counts', {})
    d2 = (get_json(f'{Z2}/_state/d2_2d_status.json', Z2_B) or {}).get('counts', {})
    return {
        'label': 'Disk Z2 (plant model backup: Smart 3D v13 + piping drawings)',
        'source_objects': 3516, 'source_bytes': 239690265998, 'real_files': 2196,
        'model_backup_on_box': model_pulled, 'databases': databases,
        'databases_restored': sum(d['restored'] for d in databases), 'files': files,
        'file_types_source': ext.get('source', []), 'file_types_sharedcontent': ext.get('sharedcontent', []),
        'at_a_glance_drawing_set': at_a_glance(ext.get('source', []), pdfc2.get('drawing_set')),
        'at_a_glance_extracted': at_a_glance(x_types, pdfc2.get('extracted')),
        'outputs_3d': {**{k: s3d.get(k) for k in ('pipelines_total', 'json_written', 'pcf_written', 'structure_area_files', 'equipment_area_files', 'ifc_files')},
                       **{k: max(s3d.get(k) or 0, s3d.get(k + '_s3') or 0) for k in ('step_files', 'step_validated', 'gltf_files', 'obj_files')},
                       'png': max(s3d.get('png') or 0, s3d.get('png_s3') or 0, count_suffix(f'{Z2}/model/png/', '.png'))},
        'model_drawings': model_drawings(),
        'outputs_2d': {'dxf_from_dwg': max(files.get('dxf_ok') or 0, count_suffix(f'{Z2}/dxf/', '.dxf')), 'png_pages': files.get('pdf_pages_png'),
                       'dxf_from_pdf_pages': count_suffix(f'{Z2}/dxf_from_pdf/', '.dxf'), 'sha_title_block_json': count_suffix(f'{Z2}/json/sha/', '.json'),
                       'model_isometrics_dxf_from_sha': count_suffix(f'{Z2}/model_drawings_dxf/', '.dxf'),
                       'model_isometrics_png_from_sha': count_suffix(f'{Z2}/model_drawings_dxf/', '.png'),
                       'model_isometrics_dxf_from_original_pcf': count_suffix(f'{Z2}/model_drawings_iso_from_pcf/', '.dxf'),
                       'model_isometrics_png_from_original_pcf': count_suffix(f'{Z2}/model_drawings_iso_from_pcf/', '.png'),
                       'model_drawing_title_block_json': count_suffix(f'{Z2}/model_drawings_json/', '.json'),
                       **{k: v for k, v in d2.items() if isinstance(v, (int, float))}},
        'stage': ('model restored' if databases[-1]['restored'] else 'restoring model DB' if model_pulled else 'pulling model backup'),
    }


def _ec2_instances(region, filters):
    out = []
    try:
        for page in sess.client('ec2', region_name=region, config=Config(retries=RETRY)).get_paginator('describe_instances').paginate(Filters=filters):
            for res in page['Reservations']:
                out += res['Instances']
    except Exception as e:                   # the coordinator's instance role may lack ec2:Describe*: fleet counts come from heartbeats then
        print('fleet: describe_instances', region, type(e).__name__, flush=True)
    return out


def fleet():
    groups = {}
    live = {'Name': 'instance-state-name', 'Values': ['pending', 'running']}
    for region in ('ap-south-1', 'ap-south-2', 'ap-southeast-1'):
        seen = {}
        for flt in ([{'Name': 'tag:Project', 'Values': ['cad-disk-extract']}, live], [{'Name': 'tag:Name', 'Values': ['cad-z3*']}, live]):
            for i in _ec2_instances(region, flt):
                seen[i['InstanceId']] = i
        for i in seen.values():
            name = next((t['Value'] for t in i.get('Tags', []) if t['Key'] == 'Name'), '')
            where = 'Hyderabad' if region == 'ap-south-2' else 'Mumbai'
            g = (f'Z3 extraction ({where})' if name.startswith('cad-z3') else
                 f'Z4 conversions to STEP ({where})' if name.startswith('cad-z4-conv') else f'Z4 extraction ({where})'
                 if name.startswith('cad-z4') else f'Z2 3D rebuild / convert ({where})' if name.startswith('cad-zen2') else 'other')
            if g == 'other':
                continue
            x = groups.setdefault(g, {'instances': 0, 'vcpu': 0, 'types': {}})
            x['instances'] += 1
            x['vcpu'] += i['CpuOptions']['CoreCount'] * i['CpuOptions']['ThreadsPerCore']
            x['types'][i['InstanceType']] = x['types'].get(i['InstanceType'], 0) + 1
    return groups


_Z3ROWS = {}


def _z3_name(path):
    """model name + context from a manifest path 'Zenitude-data-3/<archive> :: <inner path>' (inner may contain '!/' for nested)."""
    arc, _, inner = path.partition(' :: ')
    arc = arc[len('Zenitude-data-3/'):] if arc.startswith('Zenitude-data-3/') else arc
    inner = (inner or arc).replace('!/', '/')
    parts = [x for x in inner.split('/') if x]
    name = parts[-1] if parts else inner
    return name, arc


def z3_conv_status():
    """conv_status, but never shown as final while the final pass is held or not drained (final/READY absent)."""
    cs = get_json(f'{Z3}/_state/conv_status.json', Z3_B)
    if isinstance(cs, dict) and isinstance(cs.get('packaging'), dict):   # public page: counts only (no keys, no project names)
        pk = cs['packaging']
        cs['packaging'] = dict({k: v for k, v in pk.items() if isinstance(v, (int, float, bool))},
                               updated=pk.get('updated'), error=bool(pk.get('error')))
    if isinstance(cs, dict) and cs.get('final'):
        au = get_json(f'{Z3}/_state/conv/final/auto_status.json', Z3_B) or {}
        try:
            s3.head_object(Bucket=Z3_B, Key=f'{Z3}/_state/conv/final/READY')
            ready = True
        except Exception:
            ready = False
        if au.get('final_hold') or not au.get('drained') or not ready:
            cs['final'] = False
            cs['grading'] = 'interim'
        elif not cs.get('verification_complete'):
            # graded (read-back + census) but the independent verifiers have not confirmed class 1 yet
            cs['final'] = False
            cs['grading'] = 'graded r1 - independent verification in progress'
    return cs


def z3conv_rows():
    """Per-model graded rows for the site (z3conv.json): name, class, why, what is needed. Read from the builder's class lists."""
    import gzip
    rows = []
    for c, fn in ((1, 'class_1_complete'), (2, 'class_2_partial'), (3, 'class_3_broken')):
        key = f'{Z3}/_state/conv/{fn}.jsonl.gz'
        try:
            h = s3.head_object(Bucket=Z3_B, Key=key)
        except Exception:
            continue
        if _Z3ROWS.get(key, (None,))[0] != h['ETag']:
            body = gzip.decompress(s3.get_object(Bucket=Z3_B, Key=key)['Body'].read())
            _Z3ROWS[key] = (h['ETag'], [json.loads(l) for l in body.splitlines() if l.strip()])
        for r in _Z3ROWS[key][1]:
            paths = r.get('paths') or []
            name, ctx = _z3_name(paths[0]) if paths else (r.get('id', '')[:16], '')
            wr = r.get('weight_ratio') or {}
            if c == 1:
                why = [f"opens in OpenCASCADE; {r.get('parts_step')}/{r.get('parts_source')} source parts present; "
                       f"{r.get('solids')} solids, all valid; no stand-ins"
                       + (f"; {wr.get('within_5pct')}/{wr.get('checked')} parts within 5% of source volume" if wr.get('checked') else '')]
            else:
                why = [m.get('what', '').strip() for m in (r.get('missing') or []) if m.get('what')] or \
                      [str(x) for x in (r.get('reasons') or []) + (r.get('issues') or [])]
            need = [{'fix': n.get('fix', ''), 'cat': n.get('category', '')} for n in (r.get('needed_to_fix') or []) if n.get('fix')]
            rows.append({'p': r.get('pipeline'), 'n': name, 'f': ctx, 'np': r.get('n_paths'), 'v': r.get('schema') or '',
                         'c': r.get('class', c), 'k': r.get('corpus'), 'r': bool(r.get('reused')), 'rf': r.get('reuse_from'),
                         'why': why, 'need': need, 'ps': r.get('parts_source'), 'pt': r.get('parts_step'),
                         'sol': r.get('solids'), 'inv': r.get('invalid_solids'), 'sz': r.get('step_bytes'),
                         'vv': r.get('verify_verdict'), 've': r.get('verify_evidence'),
                         'vc': (r.get('verify_codes') or [])[:5], 'vm': r.get('verify_missing_count'),
                         'vp': bool(r.get('class1_pending_verification')),
                         'pr': r.get('sds2_primary'), 'ro': r.get('older_revision_of'), 'rc': r.get('revision_count'),
                         '_code': _z3_code(r.get('converter_code'))})
    # fix status: a converter-side need on a STEP made by an older converter (or reused) -> re-run with the latest code queued;
    # on a STEP made by the latest code -> fix still in progress; source-side needs can't be fixed by any converter
    latest = {}
    for x in rows:
        if x['_code'] and x['_code'] > latest.get(x['p'], ''):
            latest[x['p']] = x['_code']
    for x in rows:
        old = x['r'] or not x['_code'] or x['_code'] < latest.get(x['p'], '')
        for n in x['need']:
            n['st'] = 'src' if n['cat'].startswith('source_') else ('rerun' if old else 'wip')
        sts = {n['st'] for n in x['need']}
        x['fs'] = next((s for s in ('rerun', 'wip', 'src') if s in sts), '') if x['c'] != 1 else ''
        del x['_code']
    rows.sort(key=lambda x: (x['p'] or '', x['c'] or 9, (x['n'] or '').lower()))
    return rows


def _z3_code(code):
    """Comparable converter version: drop run-variant suffixes (+x1) so a variant of the same code counts as that code."""
    return re.sub(r'\+x\d+$', '', code or '')


def write_z3conv(git_files):
    """z3conv.json next to sources.json (loaded lazily by the page); returns True if it changed."""
    try:
        rows = z3conv_rows()
    except Exception as e:
        print(time.strftime('%H:%M:%S'), 'z3conv rows error', repr(e)[:200], flush=True)
        return False
    if not rows:
        return False
    path = os.path.join(REPO, 'z3conv.json')
    new = json.dumps({'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'interim': True, 'rows': rows},
                     separators=(',', ':'))
    old = open(path).read() if os.path.exists(path) else ''
    if re.sub(r'"generated_at":"[^"]*"', '', old) == re.sub(r'"generated_at":"[^"]*"', '', new):
        return False
    open(path, 'w').write(new)
    git_files.append('z3conv.json')
    return True


def publish(doc, path=None, git=True):
    path = path or os.path.join(REPO, 'sources.json')
    old = open(path).read() if os.path.exists(path) else ''
    new = json.dumps(doc, indent=1)
    strip = lambda s: re.sub(r'"generated_at": "[^"]*"', '', s)
    files = []
    conv_changed = write_z3conv(files) if git else False
    if strip(old) == strip(new) and time.time() - os.path.getmtime(path) < 600 and not conv_changed:   # refresh at least every 10 min
        return False
    open(path, 'w').write(new)
    if not git:
        return True
    subprocess.run(['git', '-C', REPO, 'add', 'sources.json'] + files, check=True)
    subprocess.run(['git', '-C', REPO, 'commit', '-q', '-m', f"sources: live stats {doc['generated_at']}"], check=True)
    r = subprocess.run(['git', '-C', REPO, 'push', '-q'], capture_output=True, text=True)
    if r.returncode:
        subprocess.run(['git', '-C', REPO, 'pull', '-q', '--rebase'], capture_output=True)
        subprocess.run(['git', '-C', REPO, 'push', '-q'], capture_output=True)
    return True


def write_private(doc):
    import html
    esc = lambda x: html.escape(str(x))
    gb = lambda b: f"{(b or 0)/1e9:,.1f} GB"
    run = sorted(PRIVATE.get('z4_running', []), key=lambda r: -(r.get('size') or 0))
    arcs = PRIVATE.get('z4_archives', [])
    z = doc['z4']
    rows_run = ''.join(f"<tr><td>{esc(r.get('box'))}</td><td>{esc(r.get('phase'))}</td><td class=n>{gb(r.get('size'))}</td><td class=n>{esc(r.get('files_uploaded') or '')}/{esc(r.get('files_total') or '')}</td><td>{esc(r['key'].split('/',1)[-1])}</td></tr>" for r in run)
    rows_done = ''.join(f"<tr><td>{esc(a.get('finished','')[11:19])}</td><td>{esc(a['status'])}</td><td class=n>{gb(a.get('size'))}</td><td class=n>{a['files']:,}</td><td class=n>{(a.get('stored_files') or 0):,}</td><td class=n>{a.get('nested') or 0}</td><td>{esc(', '.join(f'{e} {c:,}' for e,c in a.get('top_types',[])))}</td><td>{esc(a['path'].split('/',1)[-1])}</td></tr>" for a in arcs[:400])
    types = ''.join(f"<tr><td>{esc(t['type'])}</td><td class=n>{t['files']:,}</td><td class=n>{gb(t['bytes'])}</td><td class=n>{t['stored_files']:,}</td></tr>" for t in z['file_types']['by_extension'][:60])
    cats = ''.join(f"<tr><td>{esc(t['type'])}</td><td class=n>{t['files']:,}</td><td class=n>{gb(t['bytes'])}</td><td class=n>{t['stored_files']:,}</td></tr>" for t in z['file_types']['by_category'])
    z3 = doc.get('z3') or {}
    p3 = z3.get('progress') or {}
    run3 = sorted(PRIVATE.get('z3_running', []), key=lambda r: -(r.get('size') or 0))
    rows_run3 = ''.join(f"<tr><td>{esc(r.get('box'))}</td><td>{esc(r.get('phase'))}</td><td class=n>{gb(r.get('size'))}</td><td class=n>{esc(r.get('files_uploaded') or '')}/{esc(r.get('files_total') or '')}</td><td>{esc(str(r.get('key', '')).split('/', 1)[-1])}</td></tr>" for r in run3)
    arcs3 = PRIVATE.get('z3_archives', [])
    rows_done3 = ''.join(f"<tr><td>{esc((a.get('finished') or '')[11:19])}</td><td>{esc(a.get('status'))}</td><td class=n>{gb(a.get('size'))}</td><td class=n>{(a.get('files') or 0):,}</td><td class=n>{a.get('top_level_files') or 0:,} / {esc(a.get('report_files'))}</td><td>{esc(a.get('verify'))}</td><td class=n>{a.get('nested') or 0}</td><td>{esc(a.get('path'))}</td></tr>" for a in arcs3[:300])
    z3_html = (f"<h2>Z3 (Zenitude-data-3): {esc(z3.get('state'))} — {p3.get('jobs_done')}/{p3.get('jobs_total')} jobs, {p3.get('archive_jobs_done')}/{p3.get('archive_jobs_total')} archives, "
               f"{gb(p3.get('bytes_done'))} of {gb(p3.get('bytes_total'))}</h2>"
               f"<h2>Z3 being unzipped now ({len(run3)})</h2><table><tr><th>box</th><th>phase</th><th>size</th><th>files up/total</th><th>archive</th></tr>{rows_run3}</table>"
               f"<h2>Z3 finished archives (newest first, {len(arcs3)} in stats)</h2><table><tr><th>UTC</th><th>status</th><th>size</th><th>files</th><th>top-level / report</th><th>verify</th><th>nested</th><th>archive</th></tr>{rows_done3}</table>")
    z2d = PRIVATE.get('z2_detail', {})
    z2d_html = '<pre style="font-size:12px;background:#fff;border:1px solid #e1e0d9;padding:8px">' + esc(json.dumps({
        'db_export (tables, rows, rows exported)': z2d.get('db_export'), 'deep pass log': z2d.get('deep_log'),
        'pdf classes': z2d.get('pdf_classes'), '3D decode status': z2d.get('model_3d'),
        'extracted types (top 40)': z2d.get('extracted_types')}, indent=1)) + '</pre>'
    page = f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=60><title>PRIVATE live extraction</title>
<style>body{{font-family:system-ui,-apple-system,sans-serif;margin:24px;color:#0b0b0b;background:#f9f9f7}}table{{border-collapse:collapse;font-size:12.5px;margin-bottom:22px}}
td,th{{border-bottom:1px solid #e1e0d9;padding:4px 8px;text-align:left}}td.n{{text-align:right;font-variant-numeric:tabular-nums}}h2{{font-size:16px;margin:18px 0 6px}}
.k{{color:#52514e}}</style>
<h1 style=font-size:20px>PRIVATE — live extraction (names visible, local file only, refreshes every 60 s)</h1>
<p class=k>Generated {esc(doc['generated_at'])}. Z4: {z['archives_done']}/{z['new_archives']} new archives done, {z['files']:,} files extracted, {z['stored_files']:,} unique stored, {z['dedup_files']:,} duplicates as pointers, {z['nested_count']:,} nested archives, {z['encrypted_nested']} password-locked. Z2: {esc(doc['z2']['stage'])}, {doc['z2']['databases_restored']}/5 databases restored.</p>
{z3_html}
<h2>Zenitude-data-2 details</h2>{z2d_html}
<h2>Being unzipped now ({len(run)})</h2><table><tr><th>box</th><th>phase</th><th>size</th><th>files up/total</th><th>archive</th></tr>{rows_run}</table>
<h2>File types so far — by category</h2><table><tr><th>category</th><th>files</th><th>bytes</th><th>unique stored</th></tr>{cats}</table>
<h2>File types so far — top extensions</h2><table><tr><th>ext</th><th>files</th><th>bytes</th><th>unique stored</th></tr>{types}</table>
<h2>Finished archives (newest first, {len(arcs)})</h2><table><tr><th>UTC</th><th>status</th><th>size</th><th>files</th><th>stored</th><th>nested</th><th>top types</th><th>archive</th></tr>{rows_done}</table>"""
    os.makedirs(os.path.dirname(PRIVATE_HTML), exist_ok=True)
    open(PRIVATE_HTML, 'w').write(page)


def build_doc():
    fl = fleet()
    doc = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'interval_s': INTERVAL}
    z4 = z4_stats()
    for name, fn in (('z3', lambda: z3_stats(z4, fl)), ('move', move_stats)):    # a Z3 / move failure must not stop Z4 / Z2
        try:
            LAST[name] = fn()
        except Exception as e:
            print(time.strftime('%H:%M:%S'), name, 'error (keeping last good block)', repr(e)[:300], flush=True)
        doc[name] = LAST.get(name)
    z2 = None
    if os.environ.get('PUB_FREEZE_Z2', '1') == '1':          # data-2 is final: reuse the last published block (its folders take minutes to list)
        try:
            z2 = json.load(open(os.path.join(REPO, 'sources.json'))).get('z2')
        except Exception:
            z2 = None
    doc.update(z4=z4, z2=z2 or z2_stats(), fleet=fl)
    return doc


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('interval', nargs='?', type=int, default=120, help='seconds between rounds; 0 = one round')
    ap.add_argument('--out', help='write sources.json here instead of the status repo (implies --no-git)')
    ap.add_argument('--no-git', action='store_true', help='write sources.json but do not commit / push')
    a = ap.parse_args()
    INTERVAL = a.interval
    while True:
        t0 = time.time()
        try:
            doc = build_doc()
            pushed = publish(doc, a.out, git=not (a.out or a.no_git))
            write_private(doc)
            z, z3 = doc['z4'], doc.get('z3') or {}
            p3 = z3.get('progress') or {}
            print(doc['generated_at'], 'z3', p3.get('jobs_done'), '/', p3.get('jobs_total'), 'z4', z['archives_done'], '/', z['new_archives'],
                  'files', z['files'], 'z2', doc['z2']['stage'], 'pushed' if pushed else 'unchanged', flush=True)
        except Exception as e:
            print(time.strftime('%H:%M:%S'), 'publish error', repr(e)[:300], flush=True)
        if INTERVAL <= 0:
            break
        time.sleep(max(10, INTERVAL - (time.time() - t0)))
