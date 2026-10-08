#!/usr/bin/env python3
"""md_index.py - json/model_drawing_index.json: one record per drawing (file name without {GUID}/revision suffix and
extension, which carries the pipeline line number) linking the Smart 3D model documents of each type (sha, pcf, xml,
pod, ...) with our outputs (model_drawings_json, model_drawings_dxf + png + texts, model_drawings_iso_from_pcf)."""
import collections, gzip, json, re, sys
sys.path.insert(0, '/work/2d')
import md_run

B = 's3://annotationprod/cad-disk-extract/zenitude-data-2/'


def base_name(fn):
    b = re.sub(r'\.(sha|pcf|xml|pod|log|txt|mes|xls|sat)(\.zip)?$', '', fn, flags=re.I)
    b = re.sub(r'\{[0-9A-Fa-f-]{36}\}(-\d+)?$', '', b)
    return b


def main():
    idx = md_run.load_index()
    res = {}
    for pfx in ('_state/d2_md_results/',):
        pg = md_run.s3().get_paginator('list_objects_v2')
        for page in pg.paginate(Bucket=md_run.BK, Prefix=md_run.P + pfx):
            for o in page.get('Contents', []):
                b = md_run.s3().get_object(Bucket=md_run.BK, Key=o['Key'])['Body'].read()
                for l in gzip.decompress(b).decode('utf-8').splitlines():
                    if l.strip():
                        r = json.loads(l)
                        res[r['key']] = r
    recs = collections.OrderedDict()
    for r in idx:
        t = (r.get('file_type') or '').lower()
        keys = [o['key'] for o in r.get('objects') or [] if '/%s/0001ade2__' % t not in o['key']]
        if not keys:
            continue
        key = next((k for k in keys if not k.lower().endswith('.zip')), keys[0])
        nm = md_run.out_name(key)
        bn = base_name(r.get('file_name') or nm)
        rec = recs.setdefault(bn, {'drawing': bn, 'line_numbers': set(), 'documents': collections.defaultdict(list)})
        if r.get('line_number'):
            rec['line_numbers'].add(r['line_number'])
        ent = {'oid': r.get('oid'), 'file_name': r.get('file_name'), 'source': B + key}
        x = res.get(key)
        if t == 'sha':
            ent['json'] = B + 'model_drawings_json/%s.json' % nm
            if x and x.get('status') == 'ok':
                ent['dxf'] = B + 'model_drawings_dxf/%s.dxf' % nm
                ent['texts'] = B + 'model_drawings_dxf/%s.texts.json' % nm
                ent['png'] = B + 'model_drawings_dxf/%s.png' % nm if x.get('png') else None
                ent['dxf_entities'] = x.get('dxf_entities')
                ent['title_fields'] = x.get('fields')
            elif x:
                ent['status'] = x.get('status')
                ent['reason'] = x.get('reason')
        if t == 'pcf' and x:
            if x.get('status') in ('ok', 'empty'):
                ent['iso_dxf'] = B + 'model_drawings_iso_from_pcf/%s.dxf' % nm
                ent['iso_png'] = B + 'model_drawings_iso_from_pcf/%s.png' % nm
                ent['pipeline_reference'] = x.get('pipeline_reference')
                ent['components'] = x.get('components')
            else:
                ent['status'] = x.get('status')
                ent['reason'] = x.get('reason')
        rec['documents'][t].append(ent)
    out = []
    for rec in recs.values():
        rec['line_numbers'] = sorted(rec['line_numbers'])
        rec['documents'] = dict(rec['documents'])
        rec['has'] = {t: len(v) for t, v in rec['documents'].items()}
        rec['pair_sha_pcf'] = bool(rec['documents'].get('sha')) and bool(rec['documents'].get('pcf'))
        out.append(rec)
    summ = {'drawings': len(out), 'documents': len(idx),
            'with_sha': sum(1 for r in out if r['documents'].get('sha')),
            'with_pcf': sum(1 for r in out if r['documents'].get('pcf')),
            'with_sha_and_pcf': sum(1 for r in out if r['pair_sha_pcf']),
            'results_seen': len(res)}
    doc = {'what': 'Smart 3D model drawings (plant MLNG) - document/outputs index', 'summary': summ, 'drawings': out}
    body = json.dumps(doc, ensure_ascii=False, default=str).encode()
    md_run.s3().put_object(Bucket=md_run.BK, Key=md_run.P + 'json/model_drawing_index.json', Body=body,
                           ContentType='application/json')
    print(json.dumps(summ))


if __name__ == '__main__':
    main()
