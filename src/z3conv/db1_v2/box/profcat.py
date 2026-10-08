#!/usr/bin/env python3
"""Harvest Tekla profile definitions (ProfileName -> parameterized IFC profile incl. fillet/edge radii) from Tekla IFC
exports, streamed (no ifcopenshell). Units from the IFC's length unit (SI milli/metre or conversion-based foot/inch).
Output JSONL rows per file: {key, unit_mm, profiles: {name: [kind, [params mm]]}}.  profcat.py KEYS_JSON OUT [threads]"""
import sys, re, json, time, concurrent.futures as cf, threading
import boto3, botocore
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1', config=botocore.config.Config(max_pool_connections=64, retries={'max_attempts': 8, 'mode': 'standard'}))
RX = re.compile(rb"^#\d+\s*=\s*IFC(ISHAPE|LSHAPE|USHAPE|TSHAPE|CSHAPE|ZSHAPE|ASYMMETRICISHAPE|RECTANGLEHOLLOW|CIRCLEHOLLOW|RECTANGLE|CIRCLE)PROFILEDEF\((.*)\);", re.S)
NUM = re.compile(rb"^-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?$")
def args(s):
    out = []; depth = 0; cur = b''; q = False
    for ch in s:
        c = bytes([ch])
        if c == b"'" : q = not q
        if not q and c == b'(': depth += 1
        if not q and c == b')': depth -= 1
        if not q and depth == 0 and c == b',':
            out.append(cur.strip()); cur = b''
        else: cur += c
    out.append(cur.strip()); return out
def work(key):
    try:
        h = s3.get_object(Bucket=B, Key=key, Range='bytes=0-2999')['Body'].read()
        if b'Tekla' not in h and b'TEKLA' not in h: return None
        body = s3.get_object(Bucket=B, Key=key)['Body']
        unit = None; prof = {}; n = 0
        for line in body.iter_lines(chunk_size=1 << 20):
            if b'PROFILEDEF(' in line:
                m = RX.match(line)
                if m:
                    a = args(m.group(2))
                    name = a[1].strip(b"'").decode('latin1') if len(a) > 1 else ''
                    if not name or name == '$': continue
                    vals = []
                    for x in a[3:]:
                        vals.append(float(x) if NUM.match(x) else None)
                    k = m.group(1).decode()
                    prof.setdefault(name, (k, vals)); n += 1
            elif b'LENGTHUNIT' in line and unit is None:
                if b'.MILLI.' in line and b'.METRE.' in line: unit = 1.0
                elif b'.METRE.' in line and b'.MILLI.' not in line and b'IFCSIUNIT' in line: unit = 1000.0
            elif b'IFCCONVERSIONBASEDUNIT' in line and b'LENGTHUNIT' in line:
                if b"'FOOT'" in line.upper(): unit = 304.8
                elif b"'INCH'" in line.upper(): unit = 25.4
        u = unit or 1.0
        out = {nm: [k, [(v * u if v is not None else None) for v in vals]] for nm, (k, vals) in prof.items()}
        return {'key': key, 'unit_mm': u, 'unit_found': unit is not None, 'profiles': out}
    except Exception as e:
        return {'key': key, 'error': type(e).__name__ + ':' + str(e)[:100]}
if __name__ == '__main__':
    keys = json.load(open(sys.argv[1])); outp = sys.argv[2]; th = int(sys.argv[3]) if len(sys.argv) > 3 else 24
    n = t = 0; t0 = time.time()
    with open(outp, 'w') as fo, cf.ThreadPoolExecutor(th) as ex:
        futs = [ex.submit(work, k) for k in keys]
        for f in cf.as_completed(futs):
            r = f.result(); n += 1
            if r: fo.write(json.dumps(r) + '\n'); t += 1
            if n % 500 == 0: print(n, t, round(time.time() - t0), flush=True); fo.flush()
    print('DONE', n, t, flush=True)
