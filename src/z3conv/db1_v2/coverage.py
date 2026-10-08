"""engine x (members / plates / bolts / holes) accuracy table from the truth-pair validation outputs (vb.json bolts, vp.txt head
placement, vparts.json members/plates, conv.json decode stats). coverage.py VAL_DIR [VAL_DIR...] -> markdown"""
import sys, os, json, re, glob, collections
rows = collections.defaultdict(lambda: collections.Counter())
tags = collections.defaultdict(list)
for vd in sys.argv[1:]:
    for d in sorted(glob.glob(os.path.join(vd, '*/'))):
        t = os.path.basename(d.rstrip('/')); e = t.split('_')[0]
        c = collections.Counter()
        try:
            vb = json.load(open(d + 'vb.json')); r = vb['result']; a = vb['attributes']
            c['ifc_groups'] += r.get('ifc_groups', 0); c['joined'] += r.get('joined', 0)
            c['groups_exact'] += r.get('groups_exact', 0); c['groups_judged'] += r.get('groups_exact', 0) + r.get('groups_off', 0)
            c['bolts_ok'] += r.get('bolts_xy_ok', 0); c['bolts'] += r.get('bolts', 0)
            for k, v in a.items():
                nm, ok = k.split(':'); c[f'attr_{nm}_{ok}'] += v
        except Exception:
            pass
        try:
            for line in open(d + 'vp.txt'):
                m = re.match(r"^(record|plies\+record_centre|plies) n (\d+) median .* within 1mm ([\d.]+)", line)
                if m: c[f'head_{m.group(1)}_n'] += int(m.group(2)); c[f'head_{m.group(1)}_ok'] += round(int(m.group(2)) * float(m.group(3)))
        except Exception:
            pass
        try:
            vp = json.load(open(d + 'vparts.json'))['result']
            for k, v in vp.items():
                c['parts_' + k] += v
        except Exception:
            pass
        try:
            cj = json.load(open(d + 'conv.json')); bs = cj.get('bolt_stats') or {}
            c['conv_ok'] += cj.get('status') == 'ok'; c['holes_cut'] += bs.get('holes_cut', 0) or 0; c['groups_written'] += bs.get('groups_written', 0) or 0
        except Exception:
            pass
        if c: rows[e].update(c); tags[e].append(t)
def pct(a, b): return f'{100.0 * a / b:.1f}% ({a}/{b})' if b else '–'
print('| engine | pairs | members: axis line ≤1 mm | members: length ≤1 mm | plates: outline ≤1 mm | bolt groups joined | bolts xy ≤1 mm | head z ≤1 mm | d / L / hole match | holes cut |')
print('|---|---|---|---|---|---|---|---|---|---|')
for e in sorted(rows):
    c = rows[e]
    ml = sum(v for k, v in c.items() if k.startswith('parts_') and '|line_ok|True' in k); mlt = sum(v for k, v in c.items() if k.startswith('parts_') and '|line_ok|' in k)
    mn = sum(v for k, v in c.items() if k.startswith('parts_') and '|length_ok|True' in k); mnt = sum(v for k, v in c.items() if k.startswith('parts_') and '|length_ok|' in k)
    po = c.get('parts_IfcPlate|outline_ok|True', 0); pot = po + c.get('parts_IfcPlate|outline_ok|False', 0)
    hz = sum(c[f'head_{k}_ok'] for k in ('record', 'plies+record_centre', 'plies')); hzt = sum(c[f'head_{k}_n'] for k in ('record', 'plies+record_centre', 'plies'))
    att = []
    for nm in ('d', 'L', 'hole'):
        ok = c.get(f'attr_{nm}_True', 0); tot = ok + c.get(f'attr_{nm}_False', 0)
        att.append(f'{100.0 * ok / tot:.0f}%' if tot else '–')
    print(f"| {e} | {len(tags[e])} | {pct(ml, mlt)} | {pct(mn, mnt)} | {pct(po, pot)} | {pct(c['joined'], c['ifc_groups'])} | {pct(c['bolts_ok'], c['bolts'])} | {pct(hz, hzt)} | {' / '.join(att)} | {c['holes_cut']} |")
