"""status.py - status parts.

Every host writes its parts to /work/2d/state/status_<part>.json. The composer host (cad-zen2-files, env D2_COMPOSER=1
or /work/2d/state/COMPOSER present) merges local parts + parts uploaded by other hosts
(_state/d2_2d_status_parts/<part>.json) into s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/d2_2d_status.json
with a top-level "counts" block. Non-composer hosts only upload their own part files."""
import collections, datetime, glob, json, os

B = 'annotationprod'
P = 'cad-disk-extract/zenitude-data-2'
S = '/work/2d/state'
os.makedirs(S, exist_ok=True)
_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client('s3', region_name='ap-south-1')
    return _s3


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def is_composer():
    return os.environ.get('D2_COMPOSER') == '1' or os.path.exists(S + '/COMPOSER')


def put_part(part, obj, upload=True):
    obj = dict(obj)
    obj['updated'] = now()
    tmp = f'{S}/status_{part}.json.tmp'
    with open(tmp, 'w') as f:
        json.dump(obj, f, indent=1, default=str)
    os.replace(tmp, f'{S}/status_{part}.json')
    if not upload:
        return
    if is_composer():
        push()
    else:
        try:
            s3().put_object(Bucket=B, Key=f'{P}/_state/d2_2d_status_parts/{part}.json',
                            Body=json.dumps(obj, default=str).encode(), ContentType='application/json')
        except Exception as e:
            print('status part upload failed', e)


def remote_parts():
    out = {}
    try:
        for page in s3().get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{P}/_state/d2_2d_status_parts/'):
            for o in page.get('Contents', []):
                try:
                    out[o['Key'].rsplit('/', 1)[-1][:-5]] = json.loads(s3().get_object(Bucket=B, Key=o['Key'])['Body'].read())
                except Exception:
                    pass
    except Exception:
        pass
    return out


def counts(parts):
    c = {}
    pdf = parts.get('pdf', {})
    if pdf:
        c['p16093_pdf'] = {'distinct_pdfs': pdf.get('distinct_pdfs_total'), 'pdf_files': pdf.get('relpaths_total'),
                           'pages': pdf.get('pages_done'), 'dxf_from_pdf_pages': pdf.get('dxf_written'),
                           'validated_pages': pdf.get('validated_pages'),
                           'iou_tol1px_mean': (pdf.get('iou_tol1px') or {}).get('mean'),
                           'pages_below_0.9': (pdf.get('iou_tol1px') or {}).get('below_0.9'),
                           'failed_files': len(pdf.get('failures') or [])}
    sj = parts.get('sha_json', {})
    if sj:
        c['p16093_sha_json'] = {'distinct': sj.get('json_ok_distinct'), 'files': sj.get('json_files_written'),
                                'failed': len(sj.get('failures') or [])}
    sd = parts.get('sha_dxf', {})
    if sd:
        c['p16093_sha_dxf_experimental'] = {'distinct': sd.get('dxf_ok'), 'validated_against_pdf': sd.get('validated_against_pdf'),
                                            'vector_precision_median': sd.get('vector_precision_0p2mm_fitted_median'),
                                            'failed': len(sd.get('failed') or [])}
    dw = parts.get('dwg_retry', {})
    if dw:
        c['p16093_dwg_retry'] = {'failed_before': dw.get('failed_before'), 'recovered': dw.get('recovered')}
    ix = parts.get('index', {})
    if ix:
        c['p16093_drawing_index'] = {'records': ix.get('records'), 'drawing_numbers': ix.get('distinct_drawing_numbers')}
    # model drawings: final aggregate if present, else sum of live per-host parts
    md = parts.get('model_drawings', {})
    if md.get('stage') == 'done' and 'sha' in md:
        src = [md]
    else:
        src = [v for k, v in parts.items() if k.startswith('model_drawings_') and isinstance(v, dict) and 'sha' in v]
    if src:
        agg = {'hosts': len(src) if src[0] is not md else 'final'}
        for t in ('sha', 'pcf'):
            st = collections.Counter()
            fr = collections.Counter()
            extra = collections.Counter()
            for v in src:
                d = v.get(t) or {}
                st.update(d.get('by_status') or {})
                for f in d.get('failures') or []:
                    fr[(f.get('reason') or '?')[:70]] += 1
                for k in ('with_png', 'entities_total', 'texts_total', 'components_total'):
                    extra[k] += d.get(k) or 0
            done = sum(st.values())
            if t == 'sha':
                agg['model_sha'] = {'total_in_index': (src[0].get('totals_in_index') or {}).get('sha'), 'done': done,
                                    'json_written': done - st.get('not_ole2', 0) - fr.get('download', 0),
                                    'dxf_written': st.get('ok', 0), 'png_written': extra['with_png'],
                                    'by_status': dict(st), 'failures_by_reason': dict(fr.most_common(10))}
            else:
                agg['model_pcf_iso'] = {'total_in_index': (src[0].get('totals_in_index') or {}).get('pcf'), 'done': done,
                                        'dxf_png_written': st.get('ok', 0) + st.get('empty', 0), 'by_status': dict(st),
                                        'failures_by_reason': dict(fr.most_common(10))}
        c['model_drawings'] = agg
    return c


def push():
    parts = {}
    for fn in sorted(glob.glob(f'{S}/status_*.json')):
        try:
            parts[os.path.basename(fn)[7:-5]] = json.load(open(fn))
        except Exception:
            pass
    for k, v in remote_parts().items():
        if k not in parts or (v.get('updated', '') > parts[k].get('updated', '')):
            parts[k] = v
    stages = [f"{k}:{v.get('stage', '?')}" for k, v in parts.items()]
    doc = {'what': 'Zenitude-data-2 2D training outputs: P16093 drawing set (dxf_from_pdf, json/drawings, json/sha, '
                   'dxf_from_sha, dxf retry, json/drawing_index.json) + Smart 3D model drawings (model_drawings_json, '
                   'model_drawings_dxf, model_drawings_iso_from_pcf, json/model_drawing_index.json)',
           'composer': 'cad-zen2-files', 'stage': ', '.join(stages), 'updated': now(), 'counts': counts(parts),
           'parts': parts}
    try:
        s3().put_object(Bucket=B, Key=f'{P}/_state/d2_2d_status.json', Body=json.dumps(doc, indent=1, default=str).encode(),
                        ContentType='application/json')
    except Exception as e:
        print('status push failed', e)
