#!/usr/bin/env python3
"""Header survey of every distinct IFC model in the data-3 scan (range GET of the first 64 KB; zips: member list)
-> FILE_SCHEMA, originating system, XML / zip / gzip / other. usage: AWS_PROFILE=bim schema_survey.py contents_ifc.jsonl.gz OUT.jsonl"""
import sys, gzip, json, re, io, zipfile, boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
rows = [json.loads(l) for l in gzip.open(sys.argv[1], 'rt')]
def one(r):
    k = r.get('input_key')
    o = {'id': r['id'], 'kind': r.get('kind'), 'action': r.get('action'), 'size': r.get('size')}
    if not k:
        o['err'] = 'no input_key'; return o
    try:
        h = s3.get_object(Bucket=B, Key=k, Range='bytes=0-65535')['Body'].read()
    except Exception as e:
        o['err'] = str(e)[:80]; return o
    if h[:4] == b'PK\x03\x04':
        o['container'] = 'zip'
        try:
            b = s3.get_object(Bucket=B, Key=k)['Body'].read() if (r.get('size') or 0) < 64 << 20 else None
            if b:
                z = zipfile.ZipFile(io.BytesIO(b)); ms = [i for i in z.infolist() if not i.is_dir()]
                o['members'] = [[i.filename[-60:], i.file_size] for i in ms][:5]
                m = max([i for i in ms if i.filename.lower().endswith(('.ifc', '.ifcxml'))] or ms, key=lambda i: i.file_size)
                h = z.open(m).read(65536)
        except Exception as e:
            o['err'] = 'zip:' + str(e)[:60]; return o
    if h[:2] == b'\x1f\x8b':
        o['container'] = 'gzip'; h = gzip.GzipFile(fileobj=io.BytesIO(h)).read(65536) if True else h
    if h.lstrip()[:5] == b'<?xml' or b'iso_10303_28' in h[:4096] or b'<ifcXML' in h[:4096]:
        o['format'] = 'ifcxml'
        m = re.search(rb'(IFC[0-9A-Z_]+)', h[:8192]); o['schema'] = m.group(1).decode() if m else None
        return o
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", h)
    o['schema'] = m.group(1).decode('latin1') if m else None
    m = re.search(rb"FILE_NAME\s*\((.*?)\);", h, re.S)
    if m:
        st = re.findall(rb"'((?:[^']|'')*)'", re.sub(rb'/\*.*?\*/', b'', m.group(1), flags=re.S))
        o['system'] = st[-2].decode('latin1')[:60] if len(st) >= 2 else None
        o['preproc'] = st[-3].decode('latin1')[:60] if len(st) >= 3 else None
    o['iso'] = b'ISO-10303-21' in h[:4096]
    return o
with ThreadPoolExecutor(32) as ex, open(sys.argv[2], 'w') as g:
    for o in ex.map(one, rows):
        g.write(json.dumps(o) + '\n')
