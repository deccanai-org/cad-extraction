"""Build decode/joist_catalog.json from SDS/2's BIMJoist material file (plugins/BIMJoist/joists.xml).

The file ships inside SDS/2 job folders of the corpus (byte-identical copies, sha256 5641232a...e830, e.g.
Disk-2/Completed_Jobs_Data/SDS_Jobs_7.258/RiverPoint_Job/plugins/BIMJoist/joists.xml and
.../SDS_Jobs_7.245/NASHVILLE/NASHVILLE_JOB/plugins/BIMJoist/joists.xml). It is a "JoistMaterialFile" with one
<material> per designation (source_reference "Vulcraft 2003", 346 designations: K, KCS, LH, DLH, SLH, G, BG, VG):
top / bottom chord angle, bearing seat angle, bearing (seat) depth, bearing length, bearing gage, filler (gap between
the back-to-back chord angles), bottom-chord setback and depth. weight_per_foot is 0.0 in every record.

usage: python build_joist_catalog.py joists.xml ../decode/joist_catalog.json
"""
import sys, json, hashlib, re
import xml.etree.ElementTree as ET


def frac(s):
    """'1 1/4' -> 1.25, '3/16' -> 0.1875, '2' -> 2.0"""
    s = s.strip()
    tot = 0.0
    for part in s.split():
        if '/' in part:
            a, b = part.split('/')
            tot += float(a) / float(b)
        else:
            tot += float(part)
    return tot


def angle(s):
    """'L1 1/4x1 1/4x1/4' -> [1.25, 1.25, 0.25]; '' -> None"""
    m = re.fullmatch(r'\s*L\s*([\d /.]+)x([\d /.]+)x([\d /.]+)\s*', s or '')
    return [round(frac(m.group(i)), 4) for i in (1, 2, 3)] if m else None


def main(src, dst):
    raw = open(src, 'rb').read()
    root = ET.fromstring(raw)
    out = {}
    for m in root.findall('material'):
        r = {c.tag: (c.text or '').strip() for c in m}
        name = r['section_size']
        out[name] = dict(depth=float(r['depth'] or 0), joist_type=int(r['joist_type'] or 0),
                         tc=angle(r['top_chord_section_size']), bc=angle(r['btm_chord_section_size']),
                         seat=angle(r['bearing_seat_section_size']), seat_depth=float(r['bearing_depth'] or 0),
                         bearing_length=float(r['bearing_length'] or 0), bearing_gage=float(r['bearing_gage'] or 0),
                         filler=float(r['filler_thickness'] or 0), bc_setback=float(r['btm_chord_setback'] or 0),
                         source=r['source_reference'])
    doc = {'_source': {'file': 'plugins/BIMJoist/joists.xml (SDS/2 BIMJoist JoistMaterialFile)', 'sha256': hashlib.sha256(raw).hexdigest(),
                       'reference': sorted({v['source'] for v in out.values()}), 'designations': len(out)},
           'joists': out}
    json.dump(doc, open(dst, 'w'), indent=0, sort_keys=True)
    print(dst, len(out), 'designations', doc['_source']['sha256'])


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
