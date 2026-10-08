"""Minimal ISOGEN PCF parser (component records + points, bores, SKEY, ITEM-CODE)."""
HEADER = {'ISOGEN-FILES', 'UNITS-BORE', 'UNITS-CO-ORDS', 'UNITS-WEIGHT', 'UNITS-BOLT-DIA', 'UNITS-BOLT-LENGTH', 'UNITS-WEIGHT-LENGTH',
          'PIPELINE-REFERENCE', 'PROJECT-IDENTIFIER', 'AREA', 'DATE-DMY', 'REVISION', 'PIPING-SPEC', 'MESSAGE-SQUARE', 'MESSAGE-CIRCLE',
          'MESSAGE-TRIANGLE', 'MESSAGE-ROUND', 'COORDINATE-SYSTEM', 'ISO-TITLE', 'START-CO-ORDS', 'SPLIT-POINT'}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse(text):
    comps, cur, mat = [], None, False
    ref = None; units = {}
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw[0] not in ' \t':
            parts = raw.split()
            kw = parts[0]
            if kw == 'MATERIALS':
                mat = True; cur = None; continue
            if mat:
                cur = None; continue
            if kw.startswith('UNITS-'):
                units[kw] = parts[1] if len(parts) > 1 else None
            if kw == 'PIPELINE-REFERENCE':
                ref = raw.split(None, 1)[1].strip() if len(parts) > 1 else None
            if kw in HEADER or kw.startswith('UNITS-') or kw.startswith('MESSAGE'):
                cur = None; continue
            cur = {'type': kw, 'ep': [], 'cp': None, 'bp': [], 'co': None, 'skey': None, 'item': None, 'uci': None}
            comps.append(cur)
        elif cur is not None:
            parts = raw.split()
            k = parts[0]
            nums = [_f(x) for x in parts[1:5]]
            if k == 'END-POINT' and len(parts) >= 4:
                cur['ep'].append((nums[0], nums[1], nums[2], nums[3] if len(parts) > 4 else None))
            elif k == 'CENTRE-POINT' and len(parts) >= 4:
                cur['cp'] = (nums[0], nums[1], nums[2])
            elif k.startswith('BRANCH') and k.endswith('-POINT') and len(parts) >= 4:
                cur['bp'].append((nums[0], nums[1], nums[2], nums[3] if len(parts) > 4 else None))
            elif k == 'CO-ORDS' and len(parts) >= 4:
                cur['co'] = (nums[0], nums[1], nums[2], nums[3] if len(parts) > 4 else None)
            elif k == 'SKEY' and len(parts) > 1:
                cur['skey'] = parts[1]
            elif k == 'ITEM-CODE' and len(parts) > 1:
                cur['item'] = raw.split(None, 1)[1].strip()
            elif k == 'UCI' and len(parts) > 1:
                cur['uci'] = parts[1].strip('{}').upper()
    return {'ref': ref, 'units': units, 'comps': comps}
