#!/usr/bin/env python3
"""sha2json.py - Smart 3D / SmartSketch .sha (OLE2) -> JSON: streams, storage CLSIDs, OLE property sets,
all TaggedTxtData XML (title block, revision, notes, custom, ...) and derived title-block fields."""
import datetime, json, os, re, struct, sys
import xml.etree.ElementTree as ET
import olefile

CODE_VERSION = 'd2-sha2json-2026-09-29a'


def xml_to_obj(e):
    kids = list(e)
    if not kids:
        return (e.text or '').strip()
    out = {}
    for k in kids:
        v = xml_to_obj(k)
        if k.tag in out:
            if not isinstance(out[k.tag], list):
                out[k.tag] = [out[k.tag]]
            out[k.tag].append(v)
        else:
            out[k.tag] = v
    if e.attrib:
        out['@attrs'] = dict(e.attrib)
    return out


def jsonable(v):
    if isinstance(v, bytes):
        try:
            s = v.decode('utf-8')
            if s.isprintable():
                return s.rstrip('\x00')
        except Exception:
            pass
        return {'hex': v[:64].hex(), 'len': len(v)}
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def utf16_strings(b, minlen=3):
    out = []
    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){%d,}' % minlen, b):
        out.append(m.group().decode('utf-16le'))
    return out


def nonempty(d):
    if isinstance(d, dict):
        r = {k: nonempty(v) for k, v in d.items()}
        return {k: v for k, v in r.items() if v not in ('', {}, [], None)}
    if isinstance(d, list):
        r = [nonempty(v) for v in d]
        return [v for v in r if v not in ('', {}, [], None)]
    return d


LEVEL_RE = re.compile(r'FROM\s+(GRADE(?:\s+LEVEL)?|[\d.]+)\s*(?:LEVEL\s*)?TO\s+([\d.]+)\s*(?:LEVEL)?', re.I)
SECTION_RE = re.compile(r'SECTION[\s\-]*([A-Z]{1,3}\d?)\b', re.I)


def derive(tt, rel):
    ta = tt.get('TitleArea', {}) if isinstance(tt.get('TitleArea'), dict) else {}
    cu = tt.get('Custom', {}) if isinstance(tt.get('Custom'), dict) else {}
    cf = tt.get('Configuration', {}) if isinstance(tt.get('Configuration'), dict) else {}
    st = tt.get('Structure', {}) if isinstance(tt.get('Structure'), dict) else {}
    rv = tt.get('Revision', {})
    recs = []
    if isinstance(rv, dict):
        r = rv.get('RevisionRecord')
        recs = r if isinstance(r, list) else ([r] if r else [])
    recs = [x for x in recs if isinstance(x, dict)]
    titles = [ta.get('Title%d' % i, '') for i in range(1, 7)]
    title = ' '.join(t for t in titles if t)
    dn = ta.get('DrawingNumber') or st.get('ViewName') or ''
    sheet = ta.get('Sheet', '')
    m = re.match(r'\s*(\d+)\s*(?:of|/|\s)\s*(\d+)', sheet or '', re.I)
    sheet_no, sheet_of = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    full = ' '.join([title, rel])
    lv = LEVEL_RE.search(title) or LEVEL_RE.search(rel)
    sec = SECTION_RE.search(title) or SECTION_RE.search(rel)
    last = recs[-1] if recs else {}
    return {
        'drawing_number': dn,
        'sheet': sheet, 'sheet_no': sheet_no, 'sheet_of': sheet_of,
        'title': title, 'title_lines': [t for t in titles if t],
        'plant_name': ta.get('PlantName', ''),
        'revision': cu.get('RevisionCode') or last.get('MajorRev_ForRevise', ''),
        'revision_records': recs,
        'last_revision_date': last.get('RevisedDate', ''),
        'last_revision_description': last.get('RevisionDescription', ''),
        'created': cf.get('Created', ''), 'modified': cf.get('Modified', ''),
        'area_code': cu.get('AreaCode', ''), 'plant_area_code': cu.get('PlantAreaCode', ''),
        'document_code': cu.get('DocumentCode', ''), 'serial_no': cu.get('SerialNo', ''),
        'section': sec.group(1).upper() if sec else '',
        'level_from': (lv.group(1).upper() if lv else ''), 'level_to': (lv.group(2) if lv else ''),
        'view_name': st.get('ViewName', ''),
    }


def convert(path, rel, sha):
    o = olefile.OleFileIO(path)
    rec = {'source_relpath': rel, 'sha256': sha, 'size': os.path.getsize(path), 'converter': CODE_VERSION}
    rec['root_clsid'] = o.root.clsid
    streams = []
    storages = {}
    for s in o.listdir(streams=True, storages=True):
        n = '/'.join(s)
        t = o.get_type(n)
        if t == olefile.STGTY_STORAGE:
            storages[n] = o.getclsid(n)
        else:
            streams.append({'name': n, 'size': o.get_size(n)})
    rec['streams'] = streams
    rec['storages'] = storages
    rec['stream_bytes_total'] = sum(s['size'] for s in streams)
    # OLE property sets
    props = {}
    for ps in ('\x05SummaryInformation', '\x05DocumentSummaryInformation'):
        if o.exists(ps):
            try:
                p = o.getproperties(ps, convert_time=True, no_conversion=[10])
                props[ps.strip('\x05')] = {str(k): jsonable(v) for k, v in p.items()}
            except Exception as e:
                props[ps.strip('\x05')] = {'error': str(e)[:120]}
    try:
        md = o.get_metadata()
        meta = {}
        for k in md.SUMMARY_ATTRIBS + md.DOCSUM_ATTRIBS:
            v = getattr(md, k, None)
            if v not in (None, b'', ''):
                meta[k] = jsonable(v)
        rec['metadata'] = meta
    except Exception as e:
        rec['metadata'] = {'error': str(e)[:120]}
    rec['property_sets'] = props
    # tagged text data (title block etc.) - root and embedded JSite documents
    tagged = {}
    tagged_sites = {}
    for s in o.listdir(streams=True, storages=False):
        if 'TaggedTxtData' in s:
            n = '/'.join(s)
            raw = o.openstream(n).read()
            txt = raw.decode('utf-8', 'replace').strip().strip('\x00')
            try:
                obj = xml_to_obj(ET.fromstring(txt))
            except Exception as e:
                obj = {'_unparsed': txt[:4000], '_error': str(e)[:100]}
            i = s.index('TaggedTxtData')
            key = s[i + 1] if i + 1 < len(s) else n
            if i == 0:
                tagged[key] = obj
            else:
                tagged_sites.setdefault('/'.join(s[:i]), {})[key] = obj
    rec['tagged_text'] = tagged
    if tagged_sites:
        rec['tagged_text_embedded'] = tagged_sites
    # small descriptive streams
    small = {}
    for n in ('DocVersion3', 'JTaggedTxtStgList', 'JSitesList', 'AppObject', 'DocVersion2'):
        if o.exists(n):
            b = o.openstream(n).read()
            a = [x.decode('latin-1') for x in re.findall(rb'[\x20-\x7e]{4,}', b)]
            small[n] = {'ascii': a[:40], 'utf16': utf16_strings(b)[:40], 'size': len(b)}
    jprops = {}
    for s in o.listdir(streams=True, storages=False):
        if s[-1] == 'JProperties':
            b = o.openstream('/'.join(s)).read()
            jprops['/'.join(s[:-1])] = {'size': len(b), 'utf16': utf16_strings(b)[:20],
                                        'ascii': [x.decode('latin-1') for x in re.findall(rb'[\x20-\x7e]{4,}', b)][:20]}
    rec['descriptor_streams'] = small
    rec['jsite_properties'] = jprops
    rec['fields'] = derive(tagged, rel)
    o.close()
    return rec


if __name__ == '__main__':
    rec = convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1], '')
    print(json.dumps(nonempty(rec['fields']), indent=1)[:2500])
    print(json.dumps({k: rec[k] for k in ('root_clsid', 'storages', 'descriptor_streams')}, default=str)[:1500])
