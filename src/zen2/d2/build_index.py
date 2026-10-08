#!/usr/bin/env python3
"""build_index.py - json/drawing_index.json: one record per drawing number + sheet linking every representation
(source PDF pages / PNG / DXF-from-PDF / DWG / DXF-from-DWG / .sha / .sha JSON / other), title-block fields,
folder date + review context, duplicate content groups (sha256), and the CAD-vs-document class of each PDF."""
import collections, datetime, json, os, re, sys

sys.path.insert(0, '/work/2d')
SRC = '/work/in/src/'
B = 's3://annotationprod/cad-disk-extract/zenitude-data-2/'
TSV = '/work/out/json/source_sha256.tsv'
PDFRES = '/work/2d/state/pdf_results.jsonl'
SHARES = '/work/2d/state/sha_results.jsonl'
DWGRETRY = '/work/2d/state/dwg_retry.json'
OUT = '/work/2d/out/json/drawing_index.json'
CODE_VERSION = 'd2-index-2026-09-30a'

DN = re.compile(r'(?:P16093-)?(\d\d)-(\d\d)-(\d\d)-(\d{4})(?:-(\d{1,2}))?(?![\d])', re.I)
DOC_CODES = {'21': 'GA piping (general arrangement)', '13': 'piping layout', '04': 'plot plan', '79': 'GA civil',
             '01': 'overall plot plan'}


def s3key(prefix, rel):
    return B + prefix + rel


def parse_dates(rel):
    out = []
    for m in re.finditer(r'(?<!\d)(\d{2})[-.](\d{2})[-.](\d{4})(?!\d)', rel):
        d, mth, y = m.groups()
        try:
            out.append(datetime.date(int(y), int(mth), int(d)).isoformat())
        except ValueError:
            pass
    for m in re.finditer(r'(?<!\d)(\d{4})\.(\d{2})\.(\d{2})(?!\d)', rel):
        y, mth, d = m.groups()
        try:
            out.append(datetime.date(int(y), int(mth), int(d)).isoformat())
        except ValueError:
            pass
    return out


def folder_context(rel):
    parts = rel.split('/')
    top = parts[0] if len(parts) > 1 else ''
    low = rel.lower()
    tags = []
    for k, v in (('re-submission', 'Re-Submission'), ('tec comments', 'TEC comments'), ('cppe', 'CPPE comments'),
                 ('comments updated', 'comments updated'), ('final sub', 'final submission'),
                 ('(extended)', 'extended set'), ('related file', 'Related File (S3D/CAD source next to the issued PDF)'),
                 ('/construction/', 'Construction'), ('/updated/', 'updated'), ('revised', 'revised')):
        if k in low:
            tags.append(v)
    m = re.search(r'/LOT\s*(\d+)/', rel, re.I)
    if m:
        tags.append('LOT%s' % m.group(1))
    dates = parse_dates(rel)
    return {'top_folder': top, 'folder': os.path.dirname(rel), 'dates': dates,
            'issue_date': dates[-1] if dates else None, 'tags': tags}


def dn_from_text(s):
    m = DN.search(s or '')
    if not m:
        return None, None
    a, pa, dc, ser, suf = m.groups()
    return 'P16093-%s-%s-%s-%s' % (a, pa, dc, ser), suf


# ------------------------------------------------------------------ PDF page title block (Smart 3D sheets)
TB = re.compile(r'(\d\d)\s*(\d\d)\s*(\d\d)\s*(\d{4})\s+(\S{1,3})\s+(\d{1,2})\s*/\s*(\d{1,2})')


def _rows(ws, tol=3.0):
    rows = []
    for w in sorted(ws, key=lambda w: (w[1] + w[3]) / 2):
        cy = (w[1] + w[3]) / 2
        if rows and abs(rows[-1][0] - cy) <= tol:
            rows[-1][1].append(w)
        else:
            rows.append([cy, [w]])
    return [(cy, sorted(r, key=lambda w: w[0])) for cy, r in rows]


def pdf_page_ids(path):
    """per page (Smart 3D title block, positional): {'dn','rev','sheet','of','title_text','rev_rows','sha_label'}."""
    import pymupdf
    out = []
    try:
        doc = pymupdf.open(path)
    except Exception:
        return out
    for pg in doc:
        r = {}
        W, H = pg.rect.width, pg.rect.height
        ws = [w for w in pg.get_text('words') if w[0] > W * 0.75 and w[1] > H * 0.6]
        revh = [w for w in ws if w[4] == 'REV.' and w[1] > H * 0.9]
        lab = [w for w in ws if w[4].upper().startswith('DRG.NO') and w[1] > H * 0.9]
        if revh and lab:
            R = max(revh, key=lambda w: w[1])
            L = max(lab, key=lambda w: w[1])
            sht = sorted([w for w in ws if w[4] == 'SHT' and abs(w[1] - R[1]) < 3], key=lambda w: w[0])
            vals = [w for w in ws if L[0] - 2 < w[0] and R[1] - 50 < w[1] < L[1] - 4 and w[4] != '/']
            vy = max((w[1] for w in vals), default=None)
            vals = sorted([w for w in vals if vy is not None and abs(w[1] - vy) < 6], key=lambda w: w[0])
            digits = ''
            rest = []
            for w in vals:
                if len(digits) < 10 and re.fullmatch(r'\d+', w[4]) and (w[0] + w[2]) / 2 < R[0] - 5:
                    digits += w[4]
                else:
                    rest.append(w)
            if len(digits) == 10:
                r['dn'] = 'P16093-%s-%s-%s-%s' % (digits[:2], digits[2:4], digits[4:6], digits[6:])

                def near(xc):
                    c = [w for w in rest if abs((w[0] + w[2]) / 2 - xc) < 25]
                    return min(c, key=lambda w: abs((w[0] + w[2]) / 2 - xc))[4] if c else None
                rv = near((R[0] + R[2]) / 2)
                if rv:
                    r['rev'] = rv
                if len(sht) >= 2:
                    a, b = near((sht[0][0] + sht[0][2]) / 2), near((sht[1][0] + sht[1][2]) / 2)
                    if a and a.isdigit():
                        r['sheet'] = int(a)
                    if b and b.isdigit():
                        r['of'] = int(b)
                r['tb_source'] = 'title-block boxes'
            # title lines between 'TITLE:' and the value row
            T = [w for w in ws if w[4] == 'TITLE:' and w[1] > H * 0.85]
            if T and vy is not None:
                t0 = T[0]
                tl = [w for w in ws if t0[1] - 4 < w[1] < vy - 4 and w[0] > t0[0] - 20 and w[4] != 'TITLE:' and w[4] != 'DRG.']
                r['title_text'] = [' '.join(x[4] for x in row) for _, row in _rows(tl)]
            lbl = [w for w in ws if re.fullmatch(r'P16093-[\d-]+', w[4]) and w[1] > L[1]]
            if lbl:
                r['sha_label'] = lbl[-1][4]
            # revision table rows: rev, date, drawn, checked, approved, description
            rr = []
            for cy, row in _rows([w for w in ws if w[1] < R[1] - 60]):
                tx = [w[4] for w in row]
                di = next((i for i, x in enumerate(tx) if re.fullmatch(r'\d\d-\d\d-\d{4}', x)), None)
                if di is not None and di >= 1 and len(tx) >= di + 5 and re.fullmatch(r'\w{1,3}', tx[di - 1]):
                    rr.append({'rev': tx[di - 1], 'date': tx[di], 'drawn': tx[di + 1], 'checked': tx[di + 2],
                               'approved': tx[di + 3], 'description': ' '.join(tx[di + 4:])})
            if rr:
                r['rev_rows'] = rr
        out.append(r)
    return out


def main():
    rows = [l.rstrip('\n').split('\t', 1) for l in open(TSV)]
    rows = [(h, p) for h, p in rows if not p.startswith('PLC 17072025/')]
    by_sha = collections.defaultdict(list)
    for h, p in rows:
        by_sha[h].append(p)
    pdfres = {}
    if os.path.exists(PDFRES):
        for l in open(PDFRES):
            r = json.loads(l)
            pdfres[r['sha256']] = r
    shares = {}
    if os.path.exists(SHARES):
        for l in open(SHARES):
            r = json.loads(l)
            shares[r['sha256']] = r
    dwgretry = json.load(open(DWGRETRY)) if os.path.exists(DWGRETRY) else {}
    shadxf = {}
    if os.path.exists('/work/2d/state/sha_dxf_results.jsonl'):
        for l in open('/work/2d/state/sha_dxf_results.jsonl'):
            r = json.loads(l)
            shadxf[r['sha256']] = r
    # sheets known per base number (from .sha title blocks)
    sheets_of = collections.defaultdict(set)
    for r in shares.values():
        if r.get('status') == 'ok':
            f = r['fields']
            base, suf = dn_from_text(f.get('drawing_number'))
            if base:
                sheets_of[base].add(f.get('sheet_of'))
    recs = collections.OrderedDict()
    unassigned = []

    def rec_for(base, sheet):
        k = '%s|%s' % (base, sheet if sheet is not None else '?')
        if k not in recs:
            dc = base.split('-')[3]
            recs[k] = {'key': k, 'drawing_number': base, 'sheet': sheet, 'sheet_of': None,
                       'document_code': dc, 'document_type': DOC_CODES.get(dc, 'code ' + dc),
                       'title': None, 'title_lines': None, 'section': None, 'area': None, 'level_from': None,
                       'level_to': None, 'revisions': [], 'pdf_pages': [], 'sha': [], 'dwg': [], 'dwg_bak': [],
                       'other_files': [], 'folders': [], 'duplicate_groups': []}
        return recs[k]

    def resolve_sheet(base, suf, sheet_hint=None):
        if sheet_hint is not None:
            return sheet_hint
        dc = base.split('-')[3]
        so = sheets_of.get(base, set())
        if suf and (dc == '13' or any(x and x > 1 for x in so)):
            return int(suf)
        if so == {1} or dc == '21':
            return 1
        return None

    pdf_cache = {}
    for h, p in rows:
        ext = os.path.splitext(p)[1].lower()
        fc = folder_context(p)
        dup = by_sha[h] if len(by_sha[h]) > 1 else None
        base_fn, suf_fn = dn_from_text(os.path.basename(p))
        base_dir, suf_dir = dn_from_text(os.path.basename(os.path.dirname(p)))
        touched = []
        if ext == '.pdf':
            r = pdfres.get(h)
            if h not in pdf_cache:
                pdf_cache[h] = pdf_page_ids(SRC + p)
            ids = pdf_cache[h]
            npages = (r or {}).get('page_count') or max(1, len(ids))
            for i in range(npages):
                pid = ids[i] if i < len(ids) else {}
                pr = next((x for x in (r or {}).get('pages', []) if x['page'] == i + 1), {})
                base = pid.get('dn') or base_fn or base_dir
                if not base:
                    unassigned.append({'relpath': p, 'page': i + 1, 'sha256': h})
                    continue
                sheet = resolve_sheet(base, suf_fn if pid.get('dn') is None or pid.get('dn') == base_fn else None,
                                      pid.get('sheet'))
                rc = rec_for(base, sheet)
                if pid.get('of'):
                    rc['sheet_of'] = pid['of']
                v = pr.get('validation', {})
                ent = {'relpath': p, 'page': i + 1, 'sha256': h, 'source': s3key('source/', p),
                       'png': s3key('png/', '%s/page-%d.png' % (p, i + 1)) if os.path.exists(
                           '/work/out/png/%s/page-%d.png' % (p, i + 1)) else None,
                       'dxf_from_pdf': s3key('dxf_from_pdf/', '%s/page-%d.dxf' % (p, i + 1)) if pr.get('dxf') else None,
                       'page_kind': pr.get('kind'), 'iou_tol1px': v.get('iou_tol1px'), 'iou_strict': v.get('iou_strict'),
                       'validation': v.get('status'),
                       'pdf_class': (r or {}).get('doc_class'), 'pdf_class_reason': (r or {}).get('doc_class_reason'),
                       'producer': (r or {}).get('producer'), 'creator': (r or {}).get('creator'),
                       'pdf_status': (r or {}).get('status'), 'pdf_error': (r or {}).get('reason'),
                       'text': s3key('json/drawings_text/', p.replace('/', '__') + '.txt'),
                       'title_block': {k: pid[k] for k in ('dn', 'rev', 'sheet', 'of', 'tb_source', 'title_text',
                                                           'rev_rows') if k in pid},
                       'issue_date': fc['issue_date'], 'folder_tags': fc['tags']}
                rc['pdf_pages'].append(ent)
                for rr in pid.get('rev_rows', []):
                    rc['revisions'].append(dict(rr, source='pdf', relpath=p))
                touched.append(rc)
        elif ext == '.sha':
            r = shares.get(h)
            f = (r or {}).get('fields', {})
            base, suf = dn_from_text(f.get('drawing_number') or '')
            base = base or base_fn
            if not base:
                unassigned.append({'relpath': p, 'sha256': h})
                continue
            sheet = f.get('sheet_no') if f.get('sheet_no') else resolve_sheet(base, suf or suf_fn)
            rc = rec_for(base, sheet)
            if f.get('sheet_of'):
                rc['sheet_of'] = f['sheet_of']
            sd = shadxf.get(h, {})
            sv = sd.get('validation', {})
            rc['sha'].append({'relpath': p, 'sha256': h, 'source': s3key('source/', p),
                              'json': s3key('json/sha/', p + '.json'),
                              'dxf_from_sha': s3key('dxf_from_sha/', p + '.dxf') if sd.get('status') == 'ok' else None,
                              'dxf_from_sha_texts': s3key('dxf_from_sha/', p + '.texts.json') if sd.get('status') == 'ok' else None,
                              'dxf_from_sha_note': 'experimental geometry-only decode' if sd.get('status') == 'ok' else None,
                              'dxf_from_sha_precision_1px': sv.get('precision_1px'),
                              'dxf_from_sha_recall_1px': sv.get('recall_1px'),
                              'dxf_from_sha_validated_against': sv.get('paired_pdf'),
                              'revision': f.get('revision'),
                              'created': f.get('created'), 'modified': f.get('modified'),
                              'last_revision_date': f.get('last_revision_date'),
                              'title_block_drawing_number': f.get('drawing_number'), 'sheet_field': f.get('sheet'),
                              'issue_date': fc['issue_date'], 'folder_tags': fc['tags']})
            for rr in f.get('revision_records') or []:
                rc['revisions'].append({'rev': rr.get('MajorRev_ForRevise'), 'date': rr.get('RevisedDate'),
                                        'drawn': rr.get('RevisedBy'), 'checked': rr.get('CheckedBy'),
                                        'approved': rr.get('ApprovedBy'), 'description': rr.get('RevisionDescription'),
                                        'source': 'sha', 'relpath': p})
            for k in ('title', 'title_lines', 'section', 'level_from', 'level_to'):
                if f.get(k):
                    rc[k] = f[k]
            m = re.search(r'AREA-([A-Z]{1,2}\d{1,3})', f.get('title') or '')
            if m:
                rc['area'] = m.group(1)
            touched.append(rc)
        elif ext in ('.dwg', '.bak'):
            base = base_fn or base_dir
            if not base:
                unassigned.append({'relpath': p, 'sha256': h})
                continue
            rc = rec_for(base, resolve_sheet(base, suf_fn))
            ent = {'relpath': p, 'sha256': h, 'source': s3key('source/', p), 'issue_date': fc['issue_date'],
                   'folder_tags': fc['tags']}
            if ext == '.dwg':
                with open(SRC + p, 'rb') as fh:
                    ent['dwg_version'] = fh.read(6).decode('latin-1')
                if os.path.exists('/work/out/dxf/%s.dxf' % p):
                    ent['dxf_from_dwg'] = s3key('dxf/', p + '.dxf')
                    ent['dxf_converter'] = 'LibreDWG 0.13.3 dwg2dxf'
                elif p in dwgretry:
                    ent['dxf_from_dwg'] = dwgretry[p].get('s3')
                    ent['dxf_converter'] = dwgretry[p].get('converter')
                    ent['dxf_note'] = dwgretry[p].get('note')
                rc['dwg'].append(ent)
            else:
                rc['dwg_bak'].append(ent)
            touched.append(rc)
        else:
            base = base_fn or base_dir
            if base:
                rc = rec_for(base, resolve_sheet(base, suf_fn))
                rc['other_files'].append({'relpath': p, 'sha256': h, 'type': ext.lstrip('.'),
                                          'source': s3key('source/', p), 'folder_tags': fc['tags']})
                touched.append(rc)
            else:
                unassigned.append({'relpath': p, 'sha256': h, 'type': ext.lstrip('.')})
        for rc in touched:
            if fc['folder'] not in [x['folder'] for x in rc['folders']]:
                rc['folders'].append(fc)
            if dup and h not in [g['sha256'] for g in rc['duplicate_groups']]:
                rc['duplicate_groups'].append({'sha256': h, 'relpaths': dup})
    # finalise: de-duplicate revisions, sort by date
    for rc in recs.values():
        seen = set()
        revs = []
        for rv in rc['revisions']:
            k = (str(rv.get('rev')).lstrip('0'), rv.get('date'), rv.get('description'))
            if k in seen:
                continue
            seen.add(k)
            revs.append(rv)

        def dkey(rv):
            m = re.match(r'(\d\d)-(\d\d)-(\d{4})', rv.get('date') or '')
            return (m.group(3), m.group(2), m.group(1)) if m else ('', '', '')
        rc['revisions'] = sorted(revs, key=dkey)
        rc['issue_dates'] = sorted(set(d for f in rc['folders'] for d in f['dates']))
        rc['counts'] = {k: len(rc[k]) for k in ('pdf_pages', 'sha', 'dwg', 'dwg_bak', 'other_files')}
        rc['has'] = {'pdf': bool(rc['pdf_pages']), 'dxf_from_pdf': any(x.get('dxf_from_pdf') for x in rc['pdf_pages']),
                     'sha': bool(rc['sha']), 'dwg': bool(rc['dwg']),
                     'dxf_from_dwg': any(x.get('dxf_from_dwg') for x in rc['dwg']),
                     'dxf_from_sha': any(x.get('dxf_from_sha') for x in rc['sha'])}
        if not rc['title']:
            for e in rc['pdf_pages']:
                tt = e['title_block'].get('title_text')
                if tt:
                    rc['title_lines'] = tt
                    rc['title'] = ' '.join(tt)
                    break
        if not rc['title']:
            for f in rc['folders']:
                seg = [s for s in f['folder'].split('/') if re.search(r'SECTION|AREA|LAYOUT|GA ', s, re.I)]
                if seg:
                    rc['title'] = seg[-1]
                    rc['title_source'] = 'folder name'
                    break
        if not rc['section']:
            m = re.search(r'SECTION[\s\-]*([A-Z]{1,3})\b', rc['title'] or '', re.I)
            rc['section'] = m.group(1).upper() if m else None
        if not rc['level_from']:
            m = re.search(r'FROM\s+(GRADE(?:\s+LEVEL)?|[\d.]+)\s*(?:LEVEL\s*)?(?:TO\s+([\d.]+)|&\s*ABOVE)', rc['title'] or '', re.I)
            if m:
                rc['level_from'], rc['level_to'] = m.group(1).upper(), m.group(2) or 'ABOVE'
    items = sorted(recs.values(), key=lambda r: (r['drawing_number'], r['sheet'] if r['sheet'] is not None else 999))
    summary = {
        'records': len(items), 'distinct_drawing_numbers': len(set(r['drawing_number'] for r in items)),
        'records_by_document_type': dict(collections.Counter(r['document_type'] for r in items)),
        'with_pdf': sum(r['has']['pdf'] for r in items), 'with_dxf_from_pdf': sum(r['has']['dxf_from_pdf'] for r in items),
        'with_sha': sum(r['has']['sha'] for r in items), 'with_dwg': sum(r['has']['dwg'] for r in items),
        'with_dxf_from_dwg': sum(r['has']['dxf_from_dwg'] for r in items),
        'with_dxf_from_sha': sum(r['has']['dxf_from_sha'] for r in items),
        'sheet_unknown': sum(1 for r in items if r['sheet'] is None),
        'pdf_classes_distinct': dict(collections.Counter(r.get('doc_class') for r in pdfres.values())),
        'unassigned_files': len(unassigned),
        'duplicate_groups_total': sum(1 for v in by_sha.values() if len(v) > 1),
    }
    doc = {'what': 'P16093 (ADNOC Onshore, EPC of Sahil Phase 3, plant CDS) piping drawing index - Zenitude-data-2',
           'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
           'code': CODE_VERSION, 'key': 'drawing_number|sheet',
           'notes': ['pdf_pages[].iou_tol1px = raster validation of dxf_from_pdf vs the 150-dpi PNG (see _state/d2_2d_status.json)',
                     'sheet resolved from the title block (PDF boxes or .sha TitleArea/Sheet), else filename suffix for '
                     'multi-sheet layouts; "?" = unknown',
                     'duplicate_groups = identical content (sha256) stored under several relpaths'],
           'summary': summary, 'drawings': items, 'unassigned': unassigned}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(doc, f, indent=1, ensure_ascii=False, default=str)
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
