"""Catalog / codelist mapping helpers for piping (pure Python over the meta pickles)."""
import re, collections
from common import load_pkl, fnum

# nominal inch -> DN (mm) bores used for UNITS-BORE MM
IN2DN = {0.125: 6, 0.25: 8, 0.375: 10, 0.5: 15, 0.75: 20, 1: 25, 1.25: 32, 1.5: 40, 2: 50, 2.5: 65, 3: 80, 3.5: 90, 4: 100,
         4.5: 115, 5: 125, 6: 150, 8: 200, 10: 250, 12: 300, 14: 350, 16: 400, 18: 450, 20: 500, 22: 550, 24: 600, 26: 650,
         28: 700, 30: 750, 32: 800, 34: 850, 36: 900, 38: 950, 40: 1000, 42: 1050, 44: 1100, 46: 1150, 48: 1200, 52: 1300,
         54: 1350, 56: 1400, 60: 1500, 64: 1600, 72: 1800, 80: 2000, 84: 2100, 88: 2200, 96: 2400}


def bore_mm(npd, unit):
    if npd is None:
        return None
    try:
        v = float(npd)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    u = (unit or '').strip().lower()
    if u in ('in', 'inch', '"'):
        k = round(v, 4)
        for key, dn in IN2DN.items():
            if abs(key - k) < 1e-3:
                return float(dn)
        return round(v * 25.0, 1)
    return round(v, 1)


class Meta:
    def __init__(self):
        self.proxies = load_pkl('proxies')
        self.catparts = load_pkl('catparts')
        self.catports = load_pkl('catports')
        self.catattrs = load_pkl('catattrs')
        self.matctl = load_pkl('matctl')
        self.codelists = load_pkl('codelists')
        self.attrmap = load_pkl('attrmap')
        self.enddata = load_pkl('enddata')
        self.systree = load_pkl('systree')
        self.sections = load_pkl('sections')
        sk = load_pkl('skey')
        self.skey0 = collections.defaultdict(list)
        self.endsfx = {}
        for r in sk:
            if r['MapType'] == 0 and r['PartClassName']:
                self.skey0[r['PartClassName']].append((r['SKEY'], r['PCFComponentID']))
            elif r['MapType'] == 2 and r['CodeList'] is not None:
                self.endsfx[int(r['CodeList'])] = r['SKEY']
        # (size, unit) -> OD, learned from the catalog
        cnt = collections.defaultdict(collections.Counter)
        for d in self.catparts.values():
            for s, u, od in ((d.get('PrimarySize'), d.get('PriSizeNPDUnits'), d.get('FirstSizeOutsideDiameter')),
                             (d.get('SecondarySize'), d.get('SecSizeNPDUnits'), d.get('SecondSizeOutsideDiameter'))):
                if s and od and od > 0 and u:
                    cnt[(round(float(s), 4), u.strip().lower())][round(float(od), 5)] += 1
        self.od_by_npd = {k: c.most_common(1)[0][0] for k, c in cnt.items()}
        # bolted end data: (npd, unit, endprep, rating) -> rows
        self.bolted = collections.defaultdict(list)
        for d in self.enddata['bolted']:
            if d.get('NominalPipingDiameter') is None:
                continue
            k = (round(float(d['NominalPipingDiameter']), 4), (d.get('NominalDiameterUnits') or '').strip().lower())
            self.bolted[k].append(d)
        self.female = collections.defaultdict(list)
        for d in self.enddata['female']:
            if d.get('NominalPipingDiameter') is None:
                continue
            k = (round(float(d['NominalPipingDiameter']), 4), (d.get('NominalDiameterUnits') or '').strip().lower())
            self.female[k].append(d)

    # ---- codelists
    def cl(self, table, v, long=False):
        if v is None:
            return None
        try:
            t = self.codelists.get(table, {}).get(int(v))
        except (TypeError, ValueError):
            return None
        if not t:
            return None
        return t[1] if long else t[0]

    def attr_name(self, iid, dispid):
        return self.attrmap.get((str(iid).upper(), int(dispid)))

    def named_attrs(self, rows):
        """rows of (iid, dispid, d, l, s) -> {Iface.Prop: value (codelist-decoded where applicable)}"""
        out = {}
        for iid, disp, d, l, s in rows:
            nm = self.attr_name(iid, disp)
            key = '%s.%s' % (nm[0], nm[1]) if nm else '%s:%s' % (str(iid)[:8], disp)
            v = d if d is not None else (l if l is not None else s)
            if isinstance(v, float):
                v = fnum(v, 7)
            if nm and nm[2] and l is not None:
                dec = self.cl(nm[2], l)
                if dec is not None:
                    v = dec
            out[key] = v
        return out

    # ---- proxies / catalog
    def resolve(self, proxy):
        """proxy oid -> (moniker, catalog oid) ; model-resident parts are their own catalog oid"""
        if not proxy:
            return None, None
        p = proxy.upper()
        m = self.proxies.get(p)
        if m:
            return m
        if p in self.catparts:
            return None, p
        return None, None

    def od(self, size, unit):
        if size is None or not unit:
            return None
        return self.od_by_npd.get((round(float(size), 4), unit.strip().lower()))

    def flange_dims(self, npd, unit, endprep=None, rating=None, endstd=None):
        """-> dict(FlangeOutsideDiameter, FlangeThickness, RaisedFaceDiameter, BoltCircleDiameter, ...) best match or None"""
        if npd is None or not unit:
            return None
        rows = self.bolted.get((round(float(npd), 4), unit.strip().lower()))
        if not rows:
            return None
        def score(d):
            s = 0
            if rating is not None and d.get('PressureRating') == rating: s += 4
            if endprep is not None and d.get('EndPreparation') == endprep: s += 2
            if endstd is not None and d.get('EndStandard') == endstd: s += 1
            if d.get('FlangeOutsideDiameter'): s += 0.5
            return s
        best = max(rows, key=score)
        if rating is not None and best.get('PressureRating') != rating:
            # no row for this rating: nearest rating (codelist ids increase with class)
            with_r = [d for d in rows if d.get('PressureRating') is not None and d.get('FlangeOutsideDiameter')]
            if with_r:
                best = min(with_r, key=lambda d: abs((d['PressureRating'] or 0) - rating))
        return best

    def hub_dims(self, npd, unit, endprep=None, rating=None):
        if npd is None or not unit:
            return None
        rows = self.female.get((round(float(npd), 4), unit.strip().lower()))
        if not rows:
            return None
        return max(rows, key=lambda d: (rating is not None and d.get('PressureRating') == rating) * 2 +
                   (endprep is not None and d.get('EndPreparation') == endprep))

    # ---- system tree
    def system_path(self, oid):
        par, name = self.systree['par'], self.systree['name']
        out, o, guard = [], oid.upper(), 0
        while o in par and guard < 50:
            o = par[o]
            out.append(name.get(o, '?'))
            guard += 1
        out = out[::-1]
        return out[1:] if len(out) > 1 else out     # drop the model root


def area_of(path):
    if not path:
        return '_unassigned'
    return '/'.join(path[:2]) if len(path) >= 2 else path[0] + '/_'


# ---- PCF component type + SKEY
TYPE_BY_CT = [
    (r'^(E\d+|E90.*|E45.*|E22.*|E11.*|ELL.*|ELB.*|L90|L45)$', 'ELBOW'),
    (r'^(BEND.*|PB.*)$', 'BEND'),
    (r'^(T|RT|TEE.*|TR|TRED|LAT.*|RLAT.*|Y|CROSS|X)$', 'TEE'),
    (r'^(REDC|RC|CONRED|RCON.*|SWGC)$', 'REDUCER-CONCENTRIC'),
    (r'^(REDE|RE|ECCRED|RECC.*|SWGE)$', 'REDUCER-ECCENTRIC'),
    (r'^(FBLD|FBL|BLIND|FBLND)$', 'FLANGE-BLIND'),
    (r'^(F[A-Z]{1,4}|FLG.*|FLANGE.*)$', 'FLANGE'),
    (r'^(WOL|SOL|TOL|NOL|LOL|EOL|FLGOL|OLET|ELBOL|LATROL|SWOL|THOL|NIPOL.*|.*OLET)$', 'OLET'),
    (r'^(CAP.*|PLUG|HPLUG|BPLUG)$', 'CAP'),
    (r'^(CPLG|COUP.*|HCPLG|FCPLG)$', 'COUPLING'),
    (r'^(UN|UNION)$', 'UNION'),
    (r'^(NIP.*|NIPPLE)$', 'PIPE-FIXED'),
]


def pcf_type(cls, part_class, ct_short, cc_short, pcf_from_map, n_ports):
    if cls == 80012:
        return 'PIPE'
    if pcf_from_map and pcf_from_map.strip().lower() in ('n/a', 'na', 'none'):
        return 'MISC-COMPONENT'
    if pcf_from_map and pcf_from_map not in ('SUPPORT', 'WELD'):
        return pcf_from_map
    if cls == 80054:
        return 'INSTRUMENT'
    s = (ct_short or '').strip().upper()
    pc = (part_class or '').lower()
    ccs = (cc_short or '').lower()
    if 'valve' in ccs or 'valve' in pc or re.match(r'^(GAT|GLO|BAL|CHK|BTF|PLG|NDL|DIA|VALV|CV|BFV|ANG|3W|4W)', s):
        return 'VALVE'
    if 'flange' in pc and 'blind' in pc:
        return 'FLANGE-BLIND'
    if 'flange' in pc or pc in ('fso', 'fwn'):
        return 'FLANGE'
    for rx, t in TYPE_BY_CT:
        if s and re.match(rx, s):
            return t
    if 'elbow' in pc or pc.startswith('e90') or pc.startswith('e45'):
        return 'ELBOW'
    if 'tee' in pc or 'lateral' in pc:
        return 'TEE'
    if 'reduc' in pc:
        return 'REDUCER-ECCENTRIC' if 'ecc' in pc else 'REDUCER-CONCENTRIC'
    if 'olet' in pc or 'nipolet' in pc:
        return 'OLET'
    if 'cap' == pc or pc.startswith('cap'):
        return 'CAP'
    if 'strainer' in pc or 'filter' in pc:
        return 'FILTER'
    if 'instrument' in ccs or 'thermowell' in pc:
        return 'INSTRUMENT'
    return 'MISC-COMPONENT'


SKEY_BASE = {'ELBOW': 'EL', 'BEND': 'BE', 'TEE': 'TE', 'REDUCER-CONCENTRIC': 'RC', 'REDUCER-ECCENTRIC': 'RE',
             'FLANGE': 'FL', 'FLANGE-BLIND': 'FB', 'OLET': 'WT', 'CAP': 'KA', 'COUPLING': 'CP', 'UNION': 'UN',
             'VALVE': 'VV', 'INSTRUMENT': 'II', 'FILTER': 'FR', 'PIPE-FIXED': 'PF'}


def skey_for(meta, part_class, pcftype, endprep1):
    """-> (skey, pcf_component_id_from_map, source)"""
    rows = meta.skey0.get(part_class or '')
    sfx = meta.endsfx.get(int(endprep1)) if endprep1 is not None else None
    if rows:
        best = None
        for sk, pcf in rows:
            if sfx and sk and sk[-2:] == sfx:
                best = (sk, pcf); break
        if best is None:
            best = rows[0]
        return best[0], best[1], 'map'
    base = SKEY_BASE.get(pcftype)
    if not base:
        return None, None, None
    if pcftype == 'FLANGE':
        pc = (part_class or '').lower()
        kind = 'SO' if ('slip' in pc or pc.startswith('fso')) else ('BL' if 'blind' in pc else ('LJ' if 'lap' in pc else
               ('SW' if 'socket' in pc else 'WN')))
        return 'FL' + kind, None, 'derived'
    return base + (sfx or 'BW'), None, 'derived'
