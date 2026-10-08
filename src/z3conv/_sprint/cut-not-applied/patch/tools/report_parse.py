"""report_parse.py : Tekla part-list reports (KSS_part_list: mark profile length qty total_weight; part_list: mark profile no grade
length area weight_each) -> rows [mark, profile, qty, length, weight_total]"""
import re, os, glob
NUM = re.compile(r'^-?\d+(\.\d+)?$')
def parse(path):
    rows = []
    txt = open(path, 'rb').read().decode('latin-1').replace('\r', '')
    for l in txt.split('\n'):
        t = l.split()
        if len(t) < 5 or not all(NUM.match(x) for x in t[-3:]): continue
        if t[0].lower().startswith(('total', '---')): continue
        if len(t) >= 7 and re.match(r'^\d+$', t[-5]) and not NUM.match(t[-4]):          # part_list: ... No. Grade Length Area Weight(each)
            qty = int(t[-5]); prof = ' '.join(t[1:-5]); rows.append([t[0], prof, qty, float(t[-3]), float(t[-1]) * qty])
        elif re.match(r'^\d+$', t[-2]):                                                 # KSS: mark profile length qty weight(total)
            prof = ' '.join(t[1:-3])
            if not prof: continue
            rows.append([t[0], prof, int(t[-2]), float(t[-3]), float(t[-1])])
    return rows
PREF = ('KSS_part_list.xsr', 'part_list.xsr', 'KSS_part_list.xls', '12-30-KSS_part_list.xsr', '12-30-part_list.xsr')
def pick(d):
    for p in PREF:
        f = os.path.join(d, p)
        if os.path.exists(f) and os.path.getsize(f) > 200:
            r = parse(f)
            if len(r) >= 5: return f, r
    for f in sorted(glob.glob(os.path.join(d, '*part_list*'))):
        if 'ssembly' in f: continue
        r = parse(f)
        if len(r) >= 5: return f, r
    return None, []
PLATE = re.compile(r'^(PLATE|PLT|PL|FLT|FL|BL|PD)\s*(\d+(?:\.\d+)?)')
def bucket(p):
    p = (p or '').upper().replace(' ', '').replace('\xd8', 'D').replace('Ø', 'D')
    m = PLATE.match(p)
    if m and m.group(1) != 'PD': return 'PL t=%g' % float(m.group(2))
    return p
