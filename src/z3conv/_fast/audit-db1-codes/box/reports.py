"""reports.py: the model folder's own Tekla bolt reports (sib/<id>/) -> per (diameter, grade, length) quantities.
KSS_BOLT_LIST.CSV / .xls : 'Diam ,Grade ,Site or Workshop ,Length , Quantity ,' rows (dated header 'Date: , dd.mm.yyyy,')
assembly_bolt_list1.xls  : Tekla assembly bolt list (per assembly mark: Diam Type Length No. Connected assemblies)
*.rpt files are report TEMPLATES (object Text ...), not data -> ignored."""
import re, os, glob, datetime, collections
ROW = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*,\s*([^,]+?)\s*,([^,]*),\s*(\d+(?:\.\d+)?)\s*,\s*(\d+)\s*,')
DATE = re.compile(r'Date:\s*,?\s*(\d{1,2})\.(\d{1,2})\.(\d{4})')
AROW = re.compile(r'^\s{6,}(\d+(?:\.\d+)?)\s+(\S+)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+\S')
AHDR = re.compile(r'^\s{1,4}(\S+)\s+(\d+)\s*$')


def parse_kss(path):
    txt = open(path, 'rb').read().decode('latin-1')
    if txt.lstrip().startswith('object '):
        return None
    m = DATE.search(txt); date = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat() if m else None
    rows = collections.Counter()
    for l in txt.splitlines():
        r = ROW.match(l)
        if r:
            rows[(float(r.group(1)), r.group(2).strip().upper(), float(r.group(4)), r.group(3).split()[0].upper() if r.group(3).split() else '')] += int(r.group(5))
    return {'file': os.path.basename(path), 'date': date, 'kind': 'bolt_list', 'rows': rows} if rows else None


def parse_assembly(path):
    txt = open(path, 'rb').read().decode('latin-1')
    if txt.lstrip().startswith('object '):
        return None
    m = re.search(r'Date:\s*(\d{1,2})\.(\d{1,2})\.(\d{4})', txt)
    date = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat() if m else None
    rows = collections.Counter()
    for l in txt.splitlines():
        r = AROW.match(l)
        if r:
            rows[(float(r.group(1)), r.group(2).strip().upper(), float(r.group(3)), '')] += int(r.group(4))
    return {'file': os.path.basename(path), 'date': date, 'kind': 'assembly_bolt_list', 'rows': rows} if rows else None


def model_reports(i, root='sib'):
    out = []
    for p in sorted(glob.glob(f'{root}/{i}/*')):
        b = os.path.basename(p).lower()
        if b.endswith('.rpt') or b.endswith('.xsr'):
            continue
        try:
            if 'bolt_list' in b and 'assembly' not in b:
                r = parse_kss(p)
            elif 'assembly_bolt_list' in b:
                r = parse_assembly(p)
            else:
                r = None
        except Exception:
            r = None
        if r:
            out.append(r)
    return out
