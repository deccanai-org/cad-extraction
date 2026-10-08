"""Add ambiguity flags + the validated original PCF to OUT/pairs/pipelines.jsonl.gz; refresh OUT/pairs/summary.json."""
import os, re, json, gzip, collections
from common import *

OID_RE = re.compile(r'\{(00033457-[0-9A-Fa-f-]{27})\}')


def norm(s):
    return re.sub(r'[^A-Z0-9]', '', (s or '').upper().replace("''", '"'))


def main():
    od = os.path.join(OUT, 'pairs')
    val = {}
    for line in gzip.open(os.path.join(od, 'pcf_validation.jsonl.gz'), 'rt'):
        r = json.loads(line)
        val[r['pipeline']] = r
    cnt = collections.Counter()
    tmp = os.path.join(od, 'pipelines.jsonl.gz.tmp')
    with gzip.open(tmp, 'wt') as f:
        for line in gzip.open(os.path.join(od, 'pipelines.jsonl.gz'), 'rt'):
            r = json.loads(line)
            sh = r.get('s3d_iso_sheets') or []
            fl = collections.OrderedDict()
            drawings = {s.get('drawing') for s in sh if s.get('drawing')}
            if len(drawings) > 1:
                fl['multiple_iso_drawings'] = len(drawings)
            pcfs = [d for s in sh for d in s['documents'] if d['type'] == 'pcf']
            if len(pcfs) > 1:
                fl['multiple_original_pcfs'] = len(pcfs)
            mism = []
            for s in sh:
                m = OID_RE.search(s.get('file_name') or '')
                if m and m.group(1).upper() != r['pipeline']:
                    mism.append(s['sheet'])
            if mism:
                fl['sheet_filename_oid_differs_from_target'] = mism[:5]
            v = val.get(r['pipeline'])
            if v and not v.get('error'):
                if norm(v.get('orig_ref')) != norm(r.get('name')):
                    fl['pipeline_renamed_since_iso'] = {'iso_pcf_reference': v.get('orig_ref'), 'model_name': r.get('name')}
                if not v.get('identical_part_set'):
                    st = v.get('stats') or {}
                    fl['model_changed_since_iso'] = {'parts_only_in_iso': st.get('comp_only_orig', 0), 'parts_only_in_model': st.get('comp_only_ours', 0)}
                r['validated_against_original_pcf'] = {'doc': v['orig']['doc'], 'file': v['orig']['file'], 'sheet': v['orig']['sheet'],
                                                      'sheet_updated': v['orig']['sheet_updated'],
                                                      'summary': {k: (v.get('stats') or {}).get(k) for k in ('comp_matched', 'comp_only_orig', 'comp_only_ours', 'type_ok', 'skey_ok', 'points_ok', 'pts_le_5mm', 'bore_ok')}}
            shared = [d['oid'] for s in sh for d in s['documents'] if (d.get('key_shared_by_docs') or 0) > 1]
            if shared:
                fl['export_key_shared'] = shared[:5]
            if not sh:
                fl['no_iso_drawing'] = True
            r['flags'] = fl
            for k in fl:
                cnt[k] += 1
            cnt['pipelines'] += 1
            f.write(json.dumps(r, default=str) + '\n')
    os.replace(tmp, os.path.join(od, 'pipelines.jsonl.gz'))
    sp = os.path.join(od, 'summary.json')
    s = json.load(open(sp))
    s['pipeline_flags'] = dict(cnt)
    s['flag_meanings'] = {'multiple_iso_drawings': 'pipeline appears on more than one Smart 3D iso drawing component',
                          'multiple_original_pcfs': 'more than one original PCF (revisions / drawings); the latest sheet was used for validation',
                          'sheet_filename_oid_differs_from_target': 'sheet file name embeds a different pipeline oid than SheetToDrawingTarget',
                          'pipeline_renamed_since_iso': 'PIPELINE-REFERENCE in the original PCF differs from the current model name',
                          'model_changed_since_iso': 'parts added/removed in the model after the iso was issued (UCI sets differ)',
                          'export_key_shared': 'the model_drawings S3 key is shared by several documents', 'no_iso_drawing': 'no iso sheet targets this pipeline'}
    write_json(sp, s, gz=False)
    log('pairs flags %s' % dict(cnt))


if __name__ == '__main__':
    main()
