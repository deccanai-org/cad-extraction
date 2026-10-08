#!/usr/bin/env python3
"""Authoring-tool fact checks for a rebuilt model (the teammate's two independent checks, generalised).

Our geometry pipeline (extract.py -> steelbuild -> verify.py) never reads the quantities the authoring tool (Tekla,
Revit, ...) wrote next to the geometry. This script reads them from the IFC (units from its IfcUnitAssignment, the
measure type of every value) and compares every rebuilt part with them:

  mass        rebuilt volume x 7.85e-6 kg/mm3 (steel)   vs  BaseQuantities.NetWeight / Tekla Quantity.Net weight
                                                            and Tekla Quantity.Weight (also at the tool's own density,
                                                            read off its NetWeight / NetVolume pairs)
  volume      rebuilt volume                            vs  BaseQuantities.NetVolume / Tekla Net volume / Revit Volume
  length      rebuilt extent along the member axis       vs  Tekla Quantity.Length / BaseQuantities.Length /
              (plates: longest in-plane side)                Revit Structural.Cut Length
  dims        rebuilt section / plate extents            vs  Tekla Quantity.Height / Width (+ Length)
  section     rebuilt profile area                       vs  BaseQuantities.CrossSectionArea / Revit Structural.A
  mass/length rebuilt area x 7.85e-6                     vs  Revit / AISC nominal weight W (lb/ft in foot models)
  centroid    rebuilt centre of mass                     vs  Tekla Common.Center of gravity X/Y/Z
  z extent    rebuilt bounding box min / max z           vs  Tekla Common.Bottom / Top elevation (labels, parsed)
  bbox        rebuilt world bounding box + origin        vs  per-element MinX..MaxZ (Pset_Tekla_General or any pset)
  span        rebuilt member length <= Revit Pset_*Common.Span (an analytical length: plausibility only)

and aggregates per assembly (sum of rebuilt part masses vs the sum of the tool's part weights and vs the tool's own
assembly weight; rebuilt z range vs the assembly's bottom / top elevation) and per model. Every comparison carries its
tolerance and, when it disagrees, a reason (README.md: tolerances, reasons and their evidence).

usage:
  tekla_checks.py SCHED_DIR --ifc MODEL.ifc|.ifcZIP [--out OUT_DIR] [--extents auto|run|skip] [--jobs 4]

SCHED_DIR holds our schedules (parts.csv, part_properties.jsonl, verification.csv, solids.csv, cuts.csv, members.csv,
plates.csv, profiles.csv, profile_outlines.json, exact_geometry.jsonl ...). Rebuilt extents and profile areas are
measured by extents_worker.py / profile_areas.py in separate processes (build123d); this process imports ifcopenshell
only. Outputs (OUT_DIR): tekla_parts.csv, tekla_checks_long.csv, tekla_assemblies.csv, tekla_section_groups.csv,
tekla_summary.json.
"""
import argparse, collections, csv, json, math, os, re, shutil, subprocess, sys, tempfile, time, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RHO_STEEL = 7.85e-6                 # kg/mm3, the fixed density the checks are asked for
TOL_REL_VOL = 1e-3                  # 0.1 %: explicit-geometry parts agree to <1e-4 (see README)
TOL_REL_MASS = 1e-3
TOL_LEN_ABS = 0.01                  # mm, float noise on top of the quantisation half-steps
TOL_REL_AREA = 1e-3
TOL_BBOX_MM = 1.0                   # mm, as the teammate's origin-in-box test
TOL_COG_MM = 1.0                    # mm: plates agree to <0.01 mm, catalogue members to <0.6 mm (section definition)
TOL_REL_WPL = 1e-3                  # mass per length
UNINFORMATIVE = 0.05                # a tool value whose rounding half-step exceeds 5 % of it is not compared
SECTION_GROUP_TOL = 2e-3            # a part's ratio within 0.2 % of its section group's median -> systematic
CATALOGUE_KINDS = {'I', 'U', 'L', 'RHS', 'CHS', 'CIRCLE', 'T', 'Z', 'C', 'ASYMI'}
CATALOGUE_NAME_RE = re.compile(r'^(W|HSS|MC|C|L|S|HP|WT|PIPE|IPE|HE[ABM]|UPN|UPE|RHS|SHS|CHS|UB|UC|PFC)\d', re.I)
HARDWARE_RE = re.compile(r'\b(NUT|WASHER|MOER|RING|BOLT|SCREW|ANCHOR|STUD|HEADED|DEFORMED BAR|SHEAR CONNECTOR|RIVET)\b', re.I)
HARDWARE_GRADE_RE = re.compile(r'(^|/)(4\.6|5\.6|8\.8|10\.9|12\.9|A325|A490|F1554|A307)\b', re.I)
STEEL_RE = re.compile(r'STEEL|\bS\d{3}|\bA36\b|A5\d\d|A992|A1085|A6\d\d|GR\.?\s?\d|Q2\d\d|Q3\d\d|SS400|FE\s?\d{3}|ST\s?\d{2}|S235|S275|S355|S460', re.I)
CONCRETE_RE = re.compile(r'CONCRETE|BETON|C\d\d/\d\d|GROUT|MASONRY|CMU', re.I)

# disagreement reasons by who is responsible (README: 'Reasons')
EXPLAINED = {  # export / tool conventions: the rebuild reproduces the IFC, the tool's number means something else
    'section_definition', 'section_definition_probable', 'ifc_thickness_quantised', 'tool_density',
    'tool_weight_is_gross', 'tool_weight_is_gross+section_definition', 'tool_weight_is_gross+section_definition_probable',
    'gross_before_cuts', 'gross_is_uncut_section_x_length', 'gross_is_uncut+section_definition',
    'non_flat_plate_developed', 'tool_length_is_extrusion_length', 'tool_length_other_axis',
    'max_extent_of_non_square_ends', 'ifc_profile_edge_radius_exceeds_flange', 'ifc_section_evaluation',
    'tool_plate_dims_convention', 'aisc_nominal_weight_convention', 'tool_weight_is_tool_gross_weight',
    'tool_extent_ignores_corner_radius'}
TOOL_INCONSISTENT = {'tool_weight_inconsistent_with_tool_volume', 'tool_zero'}
OUR_REBUILD = {'rebuild_mismatch'}


def reason_category(reason):
    r = reason[len('tool_density+'):] if reason.startswith('tool_density+') else reason
    if r in EXPLAINED:
        return 'explained'
    if r in TOOL_INCONSISTENT:
        return 'tool_inconsistent'
    if r in OUR_REBUILD:
        return 'our_rebuild'
    return 'unexplained'


# ---------------------------------------------------------------------------------------------------- fact slots
# (slot, physical kind, regex on "Pset.Property" lower-cased); first match wins, so order matters
SLOT_RULES = [
    ('asm_weight', 'mass', r'^(?!.*rebar).*assembly.*weight$'),
    ('asm_rebar_weight', 'mass', r'rebar weight$'),
    ('w_net', 'mass', r'(^|\.)net ?weight$'),
    ('w_gross', 'mass', r'(^|\.)gross ?weight$'),
    ('w_tekla', 'mass', r'^tekla quantity\.weight$'),
    ('w_other', 'mass', r'weight|mass'),
    ('w_per_len', 'mass_per_length', r'^structural\.w$|weight per (unit )?length|nominalweight'),
    ('v_net', 'volume', r'(^|\.)net ?volume$|^dimensions\.volume$'),
    ('v_gross', 'volume', r'(^|\.)gross ?volume$'),
    ('v_tekla', 'volume', r'^tekla quantity\.volume$'),
    ('cog', 'length', r'center of gravity ?[xyz]( coordinate)?$'),
    ('len', 'length', r'^(tekla quantity\.length|basequantities\.length|structural\.cut length|aisc\w*\.length)$'),
    ('len_analytical', 'length', r'^(dimensions\.length|pset_\w+common\.span)$'),
    # Revit family parameters (Dimensions.d / b / h / B ...) are not used: their meaning is family-specific (AISC HSS
    # "b" is the flat width, light-gauge "d" the lip), so only Tekla's Height / Width are section-dimension facts
    ('dim_h', 'length', r'^tekla quantity\.height$'),
    ('dim_w', 'length', r'^tekla quantity\.width$'),
    ('csa', 'area', r'crosssectionarea$|^structural\.a$'),
    ('bbox', 'length', r'\.(min|max)_?[xyz]$'),
]
# full-precision sources first: BaseQuantities are exported unrounded, Tekla Quantity (2018i / 21.1) at 0.1
PRIMARY_ORDER = ['basequantities.', 'tekla quantity.', 'structural.', 'dimensions.']
MEASURE_KIND = {
    'IfcMassMeasure': 'mass', 'IfcQuantityWeight': 'mass',
    'IfcVolumeMeasure': 'volume', 'IfcQuantityVolume': 'volume',
    'IfcLengthMeasure': 'length', 'IfcPositiveLengthMeasure': 'length', 'IfcNonNegativeLengthMeasure': 'length',
    'IfcQuantityLength': 'length',
    'IfcAreaMeasure': 'area', 'IfcQuantityArea': 'area',
}
UNIT_TYPE = {'mass': 'MASSUNIT', 'volume': 'VOLUMEUNIT', 'length': 'LENGTHUNIT', 'area': 'AREAUNIT'}
SI_TARGET = {'mass': 1.0, 'volume': 1e9, 'length': 1e3, 'area': 1e6, 'mass_per_length': 1.0}   # kg, mm3, mm, mm2 per SI base unit (kg, m3, m, m2)


def slot_of(key, kind):
    k = key.lower()
    for slot, knd, rx in SLOT_RULES:
        if knd == kind and re.search(rx, k):
            return slot
    return None


def _primary_rank(key):
    k = key.lower()
    for i, p in enumerate(PRIMARY_ORDER):
        if k.startswith(p):
            return i
    return len(PRIMARY_ORDER)


# ---------------------------------------------------------------------------------------------------- IFC reading
def _open_ifc(path, tmpdir):
    import ifcopenshell
    if path.lower().endswith('zip'):
        z = zipfile.ZipFile(path)
        n = [x for x in z.namelist() if x.lower().endswith('.ifc')][0]
        z.extract(n, tmpdir)
        return ifcopenshell.open(os.path.join(tmpdir, n))
    return ifcopenshell.open(path)


def _si_factor(u):
    """SI multiplier of an IfcNamedUnit relative to its SI base (m, m2, m3, kg)"""
    PREFIX = {None: 1.0, 'EXA': 1e18, 'PETA': 1e15, 'TERA': 1e12, 'GIGA': 1e9, 'MEGA': 1e6, 'KILO': 1e3, 'HECTO': 1e2,
              'DECA': 1e1, 'DECI': 1e-1, 'CENTI': 1e-2, 'MILLI': 1e-3, 'MICRO': 1e-6, 'NANO': 1e-9}
    if u.is_a('IfcSIUnit'):
        p = PREFIX[u.Prefix]
        if u.Name == 'GRAM':                               # SI base for mass is the kilogram
            return p / 1000.0
        if u.Name == 'SQUARE_METRE':
            return p ** 2
        if u.Name == 'CUBIC_METRE':
            return p ** 3
        return p
    if u.is_a('IfcConversionBasedUnit'):
        cf = u.ConversionFactor
        return float(cf.ValueComponent.wrappedValue) * _si_factor(cf.UnitComponent)
    raise ValueError(u.is_a())


def read_ifc(path):
    """-> (units {kind: (factor to kg / mm3 / mm / mm2, unit text)}, facts {GlobalId: {key: (value, measure)}},
    schema, originating system)"""
    tdir = os.environ.get('TEKLA_TMP') or None          # where a zipped IFC is unpacked (default: system temp)
    if tdir:
        os.makedirs(tdir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='tekla_ifc_', dir=tdir)
    try:
        f = _open_ifc(path, tmp)
        units = {}
        ua = f.by_type('IfcUnitAssignment')
        for u in (ua[0].Units if ua else []):
            ut = getattr(u, 'UnitType', None)
            for kind, t in UNIT_TYPE.items():
                if ut == t:
                    try:
                        txt = (u.Prefix or '') + u.Name if u.is_a('IfcSIUnit') else u.Name
                        units[kind] = (_si_factor(u) * SI_TARGET[kind], txt)
                    except Exception as e:
                        units[kind] = (None, f'unresolved {e}')
        facts = collections.defaultdict(dict)

        def take_pset(gid, pd, prefix=''):
            if pd.is_a('IfcPropertySet'):
                for pr in pd.HasProperties or []:
                    if pr.is_a('IfcPropertySingleValue') and pr.NominalValue is not None:
                        v = pr.NominalValue.wrappedValue
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            facts[gid][prefix + pd.Name + '.' + pr.Name] = (float(v), pr.NominalValue.is_a(), None)
                        elif isinstance(v, str) and pr.Name.lower().endswith('elevation'):
                            facts[gid][prefix + pd.Name + '.' + pr.Name] = (v, 'IfcLabel', None)
            elif pd.is_a('IfcElementQuantity'):
                for q in pd.Quantities or []:
                    for a in ('LengthValue', 'AreaValue', 'VolumeValue', 'WeightValue'):
                        if hasattr(q, a) and getattr(q, a) is not None:
                            unit = None
                            if getattr(q, 'Unit', None) is not None:
                                try:
                                    unit = _si_factor(q.Unit)
                                except Exception:
                                    unit = None
                            facts[gid][prefix + pd.Name + '.' + q.Name] = (float(getattr(q, a)), q.is_a(), unit)

        for p in f.by_type('IfcProduct'):
            if p.is_a('IfcOpeningElement') or p.is_a('IfcSpatialStructureElement'):
                continue
            gid = p.GlobalId
            rels = list(getattr(p, 'IsDefinedBy', None) or []) + list(getattr(p, 'IsTypedBy', None) or [])
            for rel in rels:
                if rel.is_a('IfcRelDefinesByProperties'):
                    pd = rel.RelatingPropertyDefinition
                    for one in (pd if isinstance(pd, (list, tuple)) else [pd]):
                        take_pset(gid, one)
                elif rel.is_a('IfcRelDefinesByType') and rel.RelatingType is not None:
                    for pd in rel.RelatingType.HasPropertySets or []:
                        take_pset(gid, pd, prefix='Type:')
        return units, facts, f.schema, str(f.header.file_name.originating_system)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def read_props_jsonl(folder):
    """fallback when no IFC is given: part_properties.jsonl (values only, measure types unknown)"""
    facts = collections.defaultdict(dict)
    fn = os.path.join(folder, 'part_properties.jsonl')
    for line in open(fn):
        r = json.loads(line)
        for src in ('properties', 'quantities'):
            for k, v in (r.get(src) or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    facts[r['part_id']][k] = (float(v), None, None)
                elif isinstance(v, str) and k.lower().endswith('elevation'):
                    facts[r['part_id']][k] = (v, 'IfcLabel', None)
        a = r.get('assembly')
        if a:
            for k, v in (a.get('properties') or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    facts[a['id']][k] = (float(v), None, None)
                elif isinstance(v, str) and k.lower().endswith('elevation'):
                    facts[a['id']][k] = (v, 'IfcLabel', None)
    return facts


def guess_kind(key):
    """measure kind from the property name, for part_properties.jsonl values without a measure type"""
    k = key.lower()
    if 'weight' in k or k.endswith('mass'):
        return 'mass'
    if 'volume' in k:
        return 'volume'
    if 'area' in k:
        return 'area'
    if re.search(r'(length|height|width|span|\.min_?[xyz]|\.max_?[xyz])$', k):
        return 'length'
    return None


# ---------------------------------------------------------------------------------------------------- elevations
IMPERIAL_RE = re.compile(r"""^([+-])?\s*(\d+)'\s*-?\s*(\d+)?\s*"?\s*(?:(\d+)/(\d+))?\s*"?$""")
METRIC_RE = re.compile(r'^([+-])?\s*(\d+)(?:\.(\d+))?$')


def parse_elevation(txt):
    """Tekla elevation label -> (mm, display quantum mm) or None.  Imperial  118'-4"  /  116'-1"7/8  (feet, inches,
    fraction); metric  +35.523  (metres, as many decimals as displayed) or  +35523  (no decimals: millimetres)"""
    t = (txt or '').strip()
    if not t:
        return None
    m = IMPERIAL_RE.match(t)
    if m:
        sg = -1.0 if m.group(1) == '-' else 1.0
        inch = float(m.group(3) or 0) + (float(m.group(4)) / float(m.group(5)) if m.group(4) else 0.0)
        den = float(m.group(5)) if m.group(5) else 1.0
        return sg * (float(m.group(2)) * 304.8 + inch * 25.4), 25.4 / den
    m = METRIC_RE.match(t)
    if m:
        sg = -1.0 if m.group(1) == '-' else 1.0
        if m.group(3) is not None:
            return sg * float(m.group(2) + '.' + m.group(3)) * 1000.0, 1000.0 * 10.0 ** -len(m.group(3))
        return sg * float(m.group(2)), 1.0
    return None


# ---------------------------------------------------------------------------------------------------- sections
def sharp_area(pr):
    """area of a catalogue section WITHOUT root fillets / corner radii, round sections as an inscribed 12-gon
    (3 r^2): the section the Tekla quantities are computed on (README: 'section_definition')"""
    g = lambda k: fnum(pr.get(k)) or 0.0
    k = pr.get('kind')
    if k == 'I' or (k == 'U' and not g('slope')):
        d, b, tw, tf = g('d'), g('b'), g('tw'), g('tf')
        return 2 * b * tf + (d - 2 * tf) * tw if d and b and tw and tf else None
    if k == 'L' and not g('slope'):
        d, b, t = g('d'), g('b'), g('t')
        return t * (d + b - t) if d and b and t else None
    if k == 'RHS':
        d, b, t = g('d'), g('b'), g('t')
        return b * d - (b - 2 * t) * (d - 2 * t) if d and b and t else None
    if k == 'CIRCLE':
        return 3.0 * g('radius') ** 2 if g('radius') else None
    if k == 'CHS':
        R, t = g('radius'), g('t')
        return 3.0 * (R ** 2 - (R - t) ** 2) if R and t else None
    return None


# ---------------------------------------------------------------------------------------------------- helpers
def fnum(v):
    try:
        return float(v) if v not in (None, '') else None
    except ValueError:
        return None


def quant_step(values):
    """decimal step the values were rounded to (in their own unit), 0 = full precision: the largest 10^-k on which
    99.5 % of the non-zero values lie"""
    vals = [abs(v) for v in values if v]
    if len(vals) < 5:
        return 0.0
    for k in range(0, 7):
        s = 10.0 ** k
        on = sum(1 for v in vals if abs(v * s - round(v * s)) <= 1e-12 * max(1.0, v * s))
        if on >= 0.995 * len(vals):
            return 10.0 ** -k
    return 0.0


def median(a):
    a = sorted(a)
    n = len(a)
    if not n:
        return None
    return a[n // 2] if n % 2 else 0.5 * (a[n // 2 - 1] + a[n // 2])


def rd(v, n=6):
    return None if v is None else float(f'{v:.{n}g}')


def read_csv(folder, name):
    fn = os.path.join(folder, name)
    return list(csv.DictReader(open(fn, newline='', encoding='utf-8'))) if os.path.exists(fn) else []


# ---------------------------------------------------------------------------------------------------- main check
def run_extents(folder, out_csv, jobs, kit):
    cmd = [sys.executable, os.path.join(HERE, 'extents_worker.py'), folder, out_csv, '--jobs', str(jobs), '--kit', kit]
    subprocess.run(cmd, check=True)


def classify(p, tool_density):
    """material class used to decide which parts get a mass check"""
    role = p['role']
    txt = ' '.join([p.get('name') or '', p.get('designation') or ''])
    mat = p.get('material') or ''
    if role == 'bolt':
        return 'bolt'
    if role == 'weld':
        return 'weld'
    if role == 'concrete' or CONCRETE_RE.search(mat):
        return 'concrete'
    if HARDWARE_RE.search(txt) or HARDWARE_GRADE_RE.search(mat):
        return 'hardware'
    if STEEL_RE.search(mat):
        return 'steel'
    if tool_density:
        if 6.9e-6 <= tool_density <= 8.3e-6:
            return 'steel'
        if 1.8e-6 <= tool_density <= 2.7e-6:
            return 'concrete'
    if not mat and role in ('member', 'plate', 'accessory'):
        return 'steel?'            # no material exported: treated as steel, reported separately
    return 'other'


def check_model(folder, ifc, out, extents='auto', jobs=4, kit=None, stem=None):
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    stem = stem or os.path.basename(os.path.normpath(folder))
    kit = kit or os.path.join(HERE, '..', 'pm', 'kit')
    parts = read_csv(folder, 'parts.csv')
    ver = {r['part_id']: r for r in read_csv(folder, 'verification.csv')}
    solids = read_csv(folder, 'solids.csv')
    # swept solids (paths.json): their length is the length along the path, not the first segment's vector, and the
    # frame of their first segment does not measure them (extents along / across a bent rod are not its length / section)
    paths = json.load(open(os.path.join(folder, 'paths.json'))) if os.path.exists(os.path.join(folder, 'paths.json')) else {}

    def path_len(sid):
        pp = paths[sid]['points'] + (paths[sid]['points'][:1] if paths[sid].get('closed') else [])
        return sum(math.dist(a, b) for a, b in zip(pp, pp[1:]))
    members = {r['part_id']: r for r in read_csv(folder, 'members.csv')}
    plates = {r['part_id']: r for r in read_csv(folder, 'plates.csv')}
    profiles = {r['profile_id']: r for r in read_csv(folder, 'profiles.csv')}
    body = collections.defaultdict(list)
    for s in solids:
        if s['role'] == 'body':
            body[s['part_id']].append(s)
    cuts_of = collections.defaultdict(list)
    for c in read_csv(folder, 'cuts.csv'):
        cuts_of[c['solid_id']].append(c)
    info = json.load(open(os.path.join(folder, 'extract_info.json'))) if os.path.exists(os.path.join(folder, 'extract_info.json')) else {}

    # ---- authoring-tool facts
    if ifc:
        units, facts, schema, origin = read_ifc(ifc)
        fact_source = 'ifc'
    else:
        facts, schema, origin = read_props_jsonl(folder), info.get('schema'), info.get('originating_system')
        L = info.get('length_unit_to_mm', 1.0)
        # no unit assignment without the IFC: Tekla's export convention is assumed (kg, m3, m2; length as extracted)
        units = {'length': (L, 'from extract_info'), 'area': (1e6, 'assumed m2 (Tekla convention)'),
                 'volume': (1e9, 'assumed m3 (Tekla convention)'), 'mass': (1.0, 'assumed kg')}
        fact_source = 'part_properties.jsonl'

    # facts -> slots in target units; inventory of every source key
    inv = collections.defaultdict(lambda: dict(n=0, zeros=0, measures=collections.Counter(), slot=None, kind=None,
                                               raw=[]))
    slotted = collections.defaultdict(lambda: collections.defaultdict(dict))     # gid -> slot -> key -> value
    elev = collections.defaultdict(dict)        # gid -> {'part'|'asm': {'bottom'|'top': (mm, quantum)}}
    unused = collections.Counter()
    for gid, kv in facts.items():
        for key, (val, measure, qunit) in kv.items():
            if measure == 'IfcLabel':
                pv = parse_elevation(val)
                if pv is None:
                    continue
                k = key.lower()
                lvl = 'asm' if 'assembly' in k else 'part'
                end = 'bottom' if 'bottom' in k else 'top' if 'top' in k else None
                if end:
                    elev[gid].setdefault(lvl, {})[end] = pv + ('elevation:' + key,)
                    inv_e = inv['elevation:' + key]
                    inv_e['n'] += 1
                    inv_e['slot'], inv_e['kind'], inv_e['factor'] = 'elevation_' + lvl, 'length', 1.0
                    inv_e['measures']['IfcLabel'] += 1
                    inv_e.setdefault('quanta', collections.Counter())[round(pv[1], 4)] += 1
                    inv_e['raw'].append(pv[0])
                continue
            kind = MEASURE_KIND.get(measure) if measure else guess_kind(key)
            if kind is None and slot_of(key, 'mass_per_length'):
                kind = 'mass_per_length'           # IfcReal by the exporter: unit only by pset convention
            slot = slot_of(key, kind) if kind else None
            if slot is None:
                unused[(key, measure or '?')] += 1     # numeric authoring-tool facts no check uses (inventory)
                continue
            if kind == 'mass_per_length':
                # AISC nominal weight "W": lb/ft in a foot-unit (US) model, kg/m in a metric one -> kg/m
                L_ = units.get('length', (None,))[0]
                fac = 1.4881639 if L_ and abs(L_ - 304.8) < 1e-6 else (1.0 if L_ else None)
            else:
                fac = (qunit * SI_TARGET[kind]) if qunit else units.get(kind, (None,))[0]
            if fac is None:
                continue
            it = inv[key]
            it['n'] += 1
            it['zeros'] += val == 0
            it['measures'][measure or '?'] += 1
            it['slot'], it['kind'], it['factor'] = slot, kind, fac
            it['raw'].append(val)
            slotted[gid][slot][key] = val * fac
    for key, it in inv.items():
        if 'quanta' in it:                       # elevation labels: display precision = the finest quantum shown
            it['step_raw'] = min(it['quanta'])
            it['quanta'] = {str(k): v for k, v in it['quanta'].items()}
        else:
            it['step_raw'] = quant_step(it['raw'])
        it['step'] = it['step_raw'] * it['factor']
        it['all_zero'] = it['zeros'] == it['n']
        it['unit_factor'] = it.pop('factor')
        it['measures'] = dict(it['measures'])
        it['sample'] = sorted(it['raw'])[len(it['raw']) // 2]
        del it['raw']
    usable = {k for k, it in inv.items() if not it['all_zero']}
    # one display precision per property set and kind: integer-valued metric widths (120, 15) are not rounded to 1 mm
    # when the same pset shows lengths at 0.1 mm
    fam = collections.defaultdict(list)
    for k, it in inv.items():
        if not k.startswith('elevation:') and it['step_raw'] > 0:
            fam[(k.split('.')[0], it['kind'])].append(k)
    for ks in fam.values():
        st = min(inv[k]['step_raw'] for k in ks)
        for k in ks:
            inv[k]['step_raw'] = st
            inv[k]['step'] = st * inv[k]['unit_factor']
    # elevation labels: one display precision per model (the finest fraction / decimal any of them shows)
    ek = [k for k in inv if k.startswith('elevation:')]
    if ek:
        est = min(inv[k]['step'] for k in ek)
        for k in ek:
            inv[k]['step'] = inv[k]['step_raw'] = est

    def tool(gid, slot):
        """primary (value, key, step) of a slot for a part, or (None, None, None)"""
        cand = [(k, v) for k, v in slotted.get(gid, {}).get(slot, {}).items() if k in usable]
        if not cand:
            return None, None, None
        k, v = min(cand, key=lambda kv: (_primary_rank(kv[0]), kv[0]))
        return v, k, inv[k]['step']

    def tool_all(gid, slot):
        """every usable source of a slot, primary (full-precision BaseQuantities first) first"""
        kv = [(k, v) for k, v in slotted.get(gid, {}).get(slot, {}).items() if k in usable]
        return [(k, v, inv[k]['step']) for k, v in sorted(kv, key=lambda x: (_primary_rank(x[0]), x[0]))]

    # ---- rebuilt extents (build123d, separate process)
    ext_csv = os.path.join(out, 'extents.csv')
    has_len_facts = any(inv[k]['slot'] in ('len', 'dim_h', 'dim_w', 'bbox', 'len_analytical') for k in usable)
    if extents == 'run' or (extents == 'auto' and has_len_facts and not os.path.exists(ext_csv)):
        run_extents(folder, ext_csv, jobs, kit)
    ext = {r['part_id']: r for r in read_csv(out, 'extents.csv')} if os.path.exists(ext_csv) else {}

    # ---- IFC geometry quantisation: share of body extrusion depths on a 0.1 mm grid
    depths = [math.sqrt(sum(float(s[c]) ** 2 for c in ('vx', 'vy', 'vz'))) for s in solids if s['role'] == 'body' and s['solid_id'] not in paths]
    on01 = sum(1 for d in depths if abs(d * 10 - round(d * 10)) < 1e-6) / max(1, len(depths))
    q_ifc = 0.1 if depths and on01 >= 0.9 else 0.0

    # ---- density evidence: the tool's own net weight / net volume per part
    dens = collections.defaultdict(list)
    for p in parts:
        w, kw, _ = tool(p['part_id'], 'w_net')
        v, kv, _ = tool(p['part_id'], 'v_net')
        if w and v:
            dens[p['part_id']] = w / v
    steel_dens = [d for d in dens.values() if 6.9e-6 <= d <= 8.3e-6]
    rho_tool = median(steel_dens)
    if rho_tool is not None:
        rho_tool = round(rho_tool * 1e9) / 1e9            # 7850 / 8000 kg/m3 as the tool's material catalogue has it

    # ---- section groups (systematic per-profile ratio between rebuilt and tool volume)
    # cross-section areas of every profile, built as steelbuild builds them (separate build123d process)
    pa_csv = os.path.join(out, 'profile_areas.csv')
    if profiles and not os.path.exists(pa_csv) and extents != 'skip':
        subprocess.run([sys.executable, os.path.join(HERE, 'profile_areas.py'), folder, pa_csv, '--kit', kit], check=True,
                       stdout=subprocess.DEVNULL)
    parea = {r['profile_id']: fnum(r['area_mm2']) for r in read_csv(out, 'profile_areas.csv')}

    rows = []
    long_rows = []
    for p in parts:
        pid = p['part_id']
        v = ver.get(pid, {})
        e = ext.get(pid, {})
        vol = fnum(v.get('volume'))
        if vol is not None and vol <= 0:
            vol = None
        cls = classify(p, dens.get(pid))
        m = members.get(pid, {})
        pl = plates.get(pid, {})
        bs = body.get(pid, [])
        b0 = bs[0] if bs else None
        blen = lambda b: path_len(b['solid_id']) if b['solid_id'] in paths else math.sqrt(sum(float(b[c]) ** 2 for c in ('vx', 'vy', 'vz')))
        extr = blen(b0) if b0 else fnum(m.get('length_mm'))
        swept = bool(b0) and b0['solid_id'] in paths
        pid0 = b0['profile_id'] if b0 else m.get('profile_id', '')
        kind = profiles.get(pid0, {}).get('kind', '') if pid0 else m.get('profile_kind', '')
        area = parea.get(pid0) if pid0 else fnum(m.get('section_area_mm2'))
        # the uncut extrusions (section x length before any cut) - what a tool's gross quantities describe
        gross = sum((parea.get(b['profile_id']) or 0) * blen(b) for b in bs) if bs and all(parea.get(b['profile_id']) for b in bs) else None
        r = dict(part_id=pid, ifc_class=p['ifc_class'], role=p['role'], material_class=cls, geometry=p['geometry'],
                 name=p['name'], designation=p.get('designation', ''), part_mark=p['part_mark'],
                 assembly_mark=p['assembly_mark'], assembly_id=p['assembly_id'],
                 profile_kind=kind, profile_id=pid0, n_body_solids=len(bs), verify_status=v.get('status', ''),
                 rebuilt_volume_mm3=vol, rebuilt_mass_7850_kg=rd(vol * RHO_STEEL) if vol else None,
                 rebuilt_extrusion_mm=rd(extr, 9), rebuilt_axis_extent_mm=None if swept else fnum(e.get('frame_ext_z')),
                 rebuilt_section_area_mm2=rd(area, 9), rebuilt_gross_volume_mm3=rd(gross, 9))
        if rho_tool and vol:
            r['rebuilt_mass_tool_rho_kg'] = rd(vol * rho_tool)
        rows.append(r)
        r['_facts'] = {s: tool_all(pid, s) for s in ('w_net', 'w_gross', 'w_tekla', 'w_other', 'w_per_len', 'v_net', 'v_gross',
                                                      'v_tekla', 'cog', 'len', 'len_analytical', 'dim_h', 'dim_w', 'csa', 'bbox')}
        r['_cen'] = [fnum(v.get(c)) for c in ('cx', 'cy', 'cz')]
        r['_e'] = e
        r['_pl'] = pl
        r['_b0'] = b0
        r['_swept'] = swept
        r['_prof'] = profiles.get(pid0, {})
        skew = False
        for b in bs:
            z = [float(b[c]) for c in ('zx', 'zy', 'zz')]
            for c in cuts_of.get(b['solid_id'], []):
                if c['kind'] == 'solid':
                    skew = True
                elif c['nx'] not in ('', None):
                    n_ = [float(c[k]) for k in ('nx', 'ny', 'nz')]
                    if abs(sum(x * y for x, y in zip(z, n_))) < 0.9999:
                        skew = True
        r['end_cuts_not_square'] = skew

    # ratios rebuilt / tool per part, grouped per profile (profile_id): a ratio shared by every part of a profile is
    # a systematic difference between the tool's own section and the exported IFC profile, not a part defect
    rho_c = rho_tool or RHO_STEEL

    def ratios(r):
        pid, vol = r['part_id'], r['rebuilt_volume_mm3']
        out = {}
        if not vol:
            return out
        gross = r['rebuilt_gross_volume_mm3']
        for slot in ('v_net', 'v_gross', 'v_tekla'):
            for key, tv, step in r['_facts'][slot]:
                if tv:
                    out[(slot, key)] = vol / tv
                    if gross and slot == 'v_gross':
                        out[(slot + ':gross', key)] = gross / tv
        for slot in ('w_net', 'w_tekla', 'w_gross', 'w_other'):
            for key, tw, step in r['_facts'][slot]:
                if tw:
                    out[(slot, key)] = vol * rho_c / tw
                    if gross:
                        out[(slot + ':gross', key)] = gross * rho_c / tw
        return out

    def gkey(r):
        """section group: the profile (catalogue sections) or, for members with explicit outlines (Revit HSS ...), the
        section designation"""
        if r['profile_kind'] in CATALOGUE_KINDS and r['profile_id']:
            return 'P:' + r['profile_id']
        if r['role'] == 'member' and r.get('designation'):
            return 'D:' + r['designation']
        return None

    grp = collections.defaultdict(list)
    grp_vol = collections.defaultdict(set)
    for r in rows:
        r['_ratios'] = ratios(r)
        g = gkey(r)
        if g:
            for k, v in r['_ratios'].items():
                grp[(k, g)].append(v)
                grp_vol[(k, g)].add(round(r['rebuilt_volume_mm3']))
    grp_med = {g: median(a) for g, a in grp.items()}

    def systematic(r, rkey, extra=0.0):
        """'section_definition' when the part's ratio equals its section group's median, that median is off 1 and
        the group holds parts of different sizes (a ratio shared by different lengths is a per-section offset);
        '..._probable' for a catalogue section whose group holds identical parts only. `extra` widens the match by
        the tool value's own rounding (relative half-step)"""
        g = gkey(r)
        ratio = r['_ratios'].get(rkey)
        if g is None or ratio is None:
            return None
        med = grp_med.get((rkey, g))
        if med is None:
            return None
        csa = tool(r['part_id'], 'csa')[0]
        if csa and r['rebuilt_section_area_mm2'] and abs(r['rebuilt_section_area_mm2'] / csa - ratio) < SECTION_GROUP_TOL + extra \
                and abs(ratio - 1) > TOL_REL_VOL + extra:
            return 'section_definition'                      # the tool's own section area says so
        if not (abs(med - 1) > TOL_REL_VOL + extra and abs(ratio / med - 1) <= SECTION_GROUP_TOL + extra):
            return None
        if len(grp_vol[(rkey, g)]) >= 2:
            return 'section_definition'
        catalogue = r['profile_kind'] in CATALOGUE_KINDS or bool(CATALOGUE_NAME_RE.match(r.get('designation') or ''))
        return 'section_definition_probable' if catalogue else None

    def add(r, check, key, tool_v, reb_v, tol, ok, reason='', extra=None):
        if tool_v == 0 and check.split('_hardware')[0] not in ('bbox', 'origin_in_bbox', 'centroid'):
            ok, reason = None, 'tool_value_zero'         # a zero is "not provided" (light-gauge W = 0, ...)
        d = dict(part_id=r['part_id'], check=check, source=key, tool_value=rd(tool_v, 9), rebuilt_value=rd(reb_v, 9),
                 diff=rd(reb_v - tool_v, 6) if (tool_v is not None and reb_v is not None) else None,
                 rel_diff=rd((reb_v - tool_v) / tool_v, 4) if (tool_v and reb_v is not None) else None,
                 tol=rd(tol, 4), ok=ok, reason=reason, reason_category=reason_category(reason) if reason and ok is False else '')
        if extra:
            d.update(extra)
        long_rows.append(d)
        return d

    def net_reason(r, rkey, extra=0.0):
        """why the rebuilt (= exported IFC geometry) volume / mass differs from the tool's own net value"""
        ratio = r['_ratios'][rkey]
        t = fnum(r['_e'].get('plane_t')) or fnum(r['_pl'].get('thickness_mm'))
        if r['role'] in ('plate', 'accessory') and t and q_ifc and r['profile_kind'] not in CATALOGUE_KINDS:
            if abs(t / ratio - t) <= q_ifc / 2 + 0.005 + extra * t:
                return 'ifc_thickness_quantised'   # the exporter rounded the plate thickness to 0.1 mm
        sy = systematic(r, rkey, extra)
        if sy:
            return sy
        if r['verify_status'] and r['verify_status'] != 'match':
            return 'rebuild_mismatch'
        return 'rebuilt_larger' if ratio > 1 else 'rebuilt_smaller'

    def mass_reason(r, slot, key, tw, step, tol, vrow):
        """why a rebuilt mass differs from a tool weight (density already excluded by the caller)"""
        extra = step / 2 / tw if tw else 0.0
        tv = tool(r['part_id'], 'v_net')[0]
        # 1. the weight follows the tool's own net volume: the difference is the volume difference
        if tv and abs(tv * rho_c - tw) <= tol + TOL_REL_MASS * tw:
            if vrow is not None and vrow['reason']:
                return vrow['reason']
        # 2. Tekla WEIGHT / gross weight of a profile: section x length before cuts
        if slot in ('w_tekla', 'w_gross') and r['role'] in ('member', 'accessory', 'plate') and r['profile_kind'] in CATALOGUE_KINDS:
            g = r['_ratios'].get((slot + ':gross', key))
            if g is not None and abs(g - 1) * tw <= tol:
                return 'tool_weight_is_gross'
            sy = systematic(r, (slot + ':gross', key), extra) if g is not None else None
            if sy:
                return 'tool_weight_is_gross+' + sy
        if vrow is not None and vrow['reason'] and abs(r['_ratios'][(slot, key)] - (r['rebuilt_volume_mm3'] / vrow['tool_value'])) <= SECTION_GROUP_TOL + extra:
            return vrow['reason']
        # 3. the weight is the tool's own gross weight / follows its gross volume (Tekla WEIGHT of a profile = gross)
        wg = tool(r['part_id'], 'w_gross')[0]
        vg = tool(r['part_id'], 'v_gross')[0]
        if slot != 'w_gross' and wg and abs(wg - tw) <= tol + TOL_REL_MASS * tw:
            return 'tool_weight_is_tool_gross_weight'
        if vg and abs(vg * rho_c - tw) <= tol + TOL_REL_MASS * tw:
            return 'tool_weight_is_tool_gross_weight' if slot != 'w_gross' else 'gross_before_cuts'
        # 4. the tool's weight does not follow from the tool's own net or gross volume: a tool-internal inconsistency
        if tv and abs(tv * rho_c - tw) > tol + TOL_REL_MASS * tw:
            return 'tool_weight_inconsistent_with_tool_volume'
        return net_reason(r, (slot, key), extra)

    for r in rows:
        pid, F, e = r['part_id'], r['_facts'], r['_e']
        vol = r['rebuilt_volume_mm3']
        steelish = r['material_class'] in ('steel', 'steel?')
        # ---------------- volume (no density) -- every material
        for slot, label in (('v_net', 'volume_net'), ('v_gross', 'volume_gross'), ('v_tekla', 'volume_tekla')):
            for key, tv, step in F[slot]:
                if vol is None:
                    add(r, label, key, tv, None, None, None, 'no_rebuild')
                    continue
                tol = TOL_REL_VOL * abs(tv) + step / 2
                ok = abs(vol - tv) <= tol
                reason = ''
                if step and step / 2 > UNINFORMATIVE * abs(tv):
                    ok, reason = None, 'tool_rounding_too_coarse'     # e.g. Tekla Quantity.Volume in m3 at 0.1
                elif not ok:
                    if tv == 0:
                        reason = 'tool_zero'
                    elif slot == 'v_gross':
                        g = r['_ratios'].get(('v_gross:gross', key))
                        reason = ('gross_is_uncut_section_x_length' if g is not None and abs(g - 1) <= TOL_REL_VOL else
                                  'gross_is_uncut+section_definition' if g is not None and systematic(r, ('v_gross:gross', key)) == 'section_definition'
                                  else net_reason(r, (slot, key)))
                        if reason in ('rebuilt_smaller', 'rebuild_mismatch') and vol < tv:
                            reason = 'gross_before_cuts'
                    else:
                        reason = net_reason(r, (slot, key), step / 2 / abs(tv))
                d_ = add(r, label, key, tv, vol, tol, ok, reason)
                if slot == 'v_net' and 'vnet' not in r:
                    r['vnet'] = d_
        # ---------------- mass (steel, and fastener hardware reported apart)
        if steelish or r['material_class'] == 'hardware':
            for slot, label in (('w_net', 'mass_net'), ('w_tekla', 'mass_tekla_weight'), ('w_gross', 'mass_gross'),
                                ('w_other', 'mass_other')):
                for key, tw, step in F[slot]:
                    lab = label + ('_hardware' if r['material_class'] == 'hardware' else '')
                    if vol is None:
                        add(r, lab, key, tw, None, None, None, 'no_rebuild')
                        continue
                    m7 = vol * RHO_STEEL
                    tol = TOL_REL_MASS * abs(tw) + step / 2
                    ok = abs(m7 - tw) <= tol
                    ok_rho = abs(vol * rho_tool - tw) <= tol if rho_tool else None
                    reason = ''
                    if step and step / 2 > UNINFORMATIVE * abs(tw):
                        ok, ok_rho, reason = None, None, 'tool_rounding_too_coarse'   # e.g. a 0.06 kg nut at 0.1 kg
                    elif not ok:
                        if tw == 0:
                            reason = 'tool_zero'
                        elif ok_rho:
                            reason = 'tool_density'
                        else:
                            reason = mass_reason(r, slot, key, tw, step, tol, r.get('vnet'))
                            if rho_tool and abs(rho_tool - RHO_STEEL) > 1e-9 and reason:
                                reason = 'tool_density+' + reason
                    add(r, lab, key, tw, m7, tol, ok, reason,
                        dict(ok_at_tool_density=ok_rho, rebuilt_value_tool_density=rd(vol * rho_tool, 9) if rho_tool else None))
        # ---------------- length
        ax = None if r['_swept'] else fnum(e.get('frame_ext_z'))
        extr = r['rebuilt_extrusion_mm']
        cands = json.loads(e['plane_cands']) if e.get('plane_cands') else []
        hw = '_hardware' if r['material_class'] == 'hardware' else ''
        is_section = (r['role'] == 'member' or r['profile_kind'] in CATALOGUE_KINDS or
                      (r['ifc_class'] in ('IfcBeam', 'IfcColumn', 'IfcMember') and r['role'] != 'plate' and bool(r['_b0'])))
        for key, tl, step in F['len']:
            tol = step / 2 + q_ifc / 2 + TOL_LEN_ABS + 1e-6 * abs(tl)
            if is_section and (ax is not None or extr is not None):
                reb = ax if ax is not None else extr
                ok = abs(reb - tl) <= tol
                reason = ''
                if not ok:
                    if tl == 0:
                        reason = 'tool_zero'
                    elif extr is not None and abs(extr - tl) <= tol:
                        reason = 'tool_length_is_extrusion_length'
                    elif fnum(e.get('face_ext_a')) and abs(fnum(e['face_ext_a']) - tl) <= tol:
                        reason = 'tool_length_other_axis'
                    elif r['verify_status'] and r['verify_status'] != 'match':
                        reason = 'rebuild_mismatch'
                    elif reb > tl and r['end_cuts_not_square']:
                        reason = 'max_extent_of_non_square_ends'   # tool length on its reference line, ours = max
                    else:
                        reason = 'rebuilt_longer' if reb > tl else 'rebuilt_shorter'
                add(r, 'length_member' + hw, key, tl, reb, tol, ok, reason,
                    dict(rebuilt_basis='axis_extent' if ax is not None else 'extrusion_length'))
            elif r['role'] in ('plate', 'accessory') and cands:
                best = min(cands, key=lambda c: abs(c[0] - tl))
                reb = best[0]
                ok = abs(reb - tl) <= tol
                reason = '' if ok else ('tool_zero' if tl == 0 else
                                        'non_flat_plate_developed' if (fnum(e.get('plane_t')) or 0) > 3 * (tool(pid, 'dim_w')[0] or 1e9)
                                        else 'tool_plate_dims_convention' if (r.get('vnet') is not None and r['vnet']['ok'])
                                        else 'rebuilt_longer' if reb > tl else 'rebuilt_shorter')
                add(r, 'length_plate' + hw, key, tl, reb, tol, ok, reason, dict(rebuilt_basis='longest_in_plane_side'))
            elif r['role'] in ('plate', 'accessory', 'concrete', 'other', 'bolt') and fnum(e.get('face_ext_a')):
                reb = fnum(e['face_ext_a'])
                ok = abs(reb - tl) <= tol
                add(r, 'length_other' + hw, key, tl, reb, tol, ok, '' if ok else ('rebuilt_longer' if reb > tl else 'rebuilt_shorter'),
                    dict(rebuilt_basis='largest_face_frame'))
        # analytical length (Revit Span / Dimensions.Length on framing): plausibility only, rebuilt <= span (+ tol)
        for key, sp, step in F['len_analytical']:
            reb = ax if ax is not None else extr
            if reb is None or r['role'] not in ('member',):
                continue
            tol = step / 2 + q_ifc / 2 + TOL_LEN_ABS + 1e-6 * abs(sp)
            add(r, 'span_plausibility', key, sp, reb, tol, reb <= sp + tol, '' if reb <= sp + tol else 'rebuilt_exceeds_analytical_length',
                dict(exact_equal=abs(reb - sp) <= tol))
        # ---------------- dims: Tekla Height / Width (+ Length) vs rebuilt extents
        th, tw_ = tool(pid, 'dim_h'), tool(pid, 'dim_w')
        if th[0] is not None and tw_[0] is not None:
            step = max(th[2] or 0, tw_[2] or 0)
            tol_f = lambda x: step / 2 + q_ifc / 2 + TOL_LEN_ABS + 1e-6 * abs(x)
            if is_section and e.get('frame_ext_x') and not r['_swept']:
                reb = sorted([fnum(e['frame_ext_x']), fnum(e['frame_ext_y'])])
                tl = sorted([th[0], tw_[0]])
                dmax = max(abs(a - b) - tol_f(b) for a, b in zip(reb, tl))
                ok = dmax <= 0
                reason = ''
                if not ok:
                    pr_ = r['_prof']
                    nom = sorted([fnum(pr_.get('d')) or 0, fnum(pr_.get('b')) or 0])
                    flange = fnum(pr_.get('tf')) or fnum(pr_.get('t')) or 0
                    if 0 in tl:
                        reason = 'tool_zero'
                    elif pr_.get('kind') in ('U', 'L') and (fnum(pr_.get('r_edge')) or 0) > flange > 0 and min(reb) < min(tl):
                        reason = 'ifc_profile_edge_radius_exceeds_flange'   # IFC toe radius > flange: section narrows
                    elif all(abs(a - b) <= tol_f(b) for a, b in zip(nom, tl)):
                        reason = 'ifc_section_evaluation'    # tool = nominal profile, the evaluated IFC solid is not
                    else:
                        reason = 'section_dims_differ'
                r['dims_reason'] = reason
                add(r, 'dims_member_section' + hw, th[1] + '+' + tw_[1], tl[1], reb[1], tol_f(tl[1]), ok, reason,
                    dict(tool_dims=json.dumps([round(x, 4) for x in tl]), rebuilt_dims=json.dumps([round(x, 4) for x in reb])))
            elif r['role'] in ('plate', 'accessory') and cands and fnum(e.get('plane_t')) is not None:
                tL = tool(pid, 'len')[0]
                t_reb = fnum(e['plane_t'])
                if tL is not None:
                    tool_inplane = sorted([th[0], tL], reverse=True)
                    best = min(cands, key=lambda c: abs(c[0] - tool_inplane[0]) + abs(c[1] - tool_inplane[1]))
                    errs = [abs(best[0] - tool_inplane[0]) - tol_f(tool_inplane[0]),
                            abs(best[1] - tool_inplane[1]) - tol_f(tool_inplane[1]),
                            abs(t_reb - tw_[0]) - tol_f(tw_[0])]
                    ok = max(errs) <= 0
                    reason = ''
                    if not ok:
                        if 0 in (th[0], tw_[0], tL):
                            reason = 'tool_zero'
                        elif t_reb > 3 * tw_[0]:
                            reason = 'non_flat_plate_developed'
                        elif errs[2] > 0 and errs[0] <= 0 and errs[1] <= 0:
                            reason = 'thickness_differs'
                        elif r.get('vnet') is not None and r['vnet']['ok']:
                            reason = 'tool_plate_dims_convention'   # the tool's own net volume confirms the outline
                        else:
                            reason = 'outline_differs'
                    add(r, 'dims_plate' + hw, th[1] + '+' + tw_[1], tw_[0], t_reb, tol_f(tw_[0]), ok, reason,
                        dict(tool_dims=json.dumps([round(x, 4) for x in tool_inplane + [tw_[0]]]),
                             rebuilt_dims=json.dumps([round(x, 4) for x in best + [t_reb]])))
        # ---------------- cross-section area
        for key, ca, step in F['csa']:
            if is_section and r['rebuilt_section_area_mm2']:
                reb = r['rebuilt_section_area_mm2']
                tol = TOL_REL_AREA * ca + step / 2
                ok = abs(reb - ca) <= tol
                add(r, 'section_area' + hw, key, ca, reb, tol, ok, '' if ok else 'section_definition')
        # ---------------- centre of gravity (Tekla Common / Center of Gravity psets) vs rebuilt centroid
        cogs = collections.defaultdict(dict)
        for key, v_, step in F['cog']:
            m_ = re.search(r'([xyz])( coordinate)?$', key.lower())
            cogs[key[:m_.start()]][m_.group(1)] = (v_, step)
        for pre, xyz in cogs.items():
            if len(xyz) == 3 and None not in r['_cen']:
                t3 = [xyz[a][0] for a in 'xyz']
                step = max(xyz[a][1] for a in 'xyz')
                dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(r['_cen'], t3)))
                tol = TOL_COG_MM + step / 2
                ok = dist <= tol
                reason = ''
                if not ok:
                    reason = ('rebuild_mismatch' if r['verify_status'] and r['verify_status'] != 'match' else
                              'section_definition' if r.get('vnet') is not None and r['vnet']['reason'].startswith('section_definition')
                              else 'centroid_differs')
                add(r, 'centroid' + hw, pre.strip() + ' X/Y/Z', 0.0, dist, tol, ok, reason,
                    dict(within_0p01mm=dist <= 0.01 + step / 2))
        # ---------------- mass per length (AISC nominal weight W) vs rebuilt section area x 7.85e-6
        for key, wpl, step in F['w_per_len']:
            if r['rebuilt_section_area_mm2'] and steelish:
                reb = r['rebuilt_section_area_mm2'] * RHO_STEEL * 1000.0      # kg/m
                tol = TOL_REL_WPL * wpl + step / 2
                ok = abs(reb - wpl) <= tol
                reason = ''
                if not ok:
                    csa = tool(pid, 'csa')[0]
                    if csa and abs(r['rebuilt_section_area_mm2'] / csa - 1) <= TOL_REL_AREA:
                        reason = 'aisc_nominal_weight_convention'   # area agrees with the tool's A, W is nominal
                    else:
                        reason = 'section_definition' if csa else 'rebuilt_larger' if reb > wpl else 'rebuilt_smaller'
                add(r, 'mass_per_length', key, wpl, reb, tol, ok, reason)
        # ---------------- Z extent: Tekla Common.Bottom / Top elevation (a per-element MinZ / MaxZ) vs rebuilt bbox
        ev = elev.get(pid, {}).get('part')
        if ev and len(ev) == 2 and e.get('lo_z'):
            step = max(inv[ev[k][2]]['step'] for k in ('bottom', 'top'))
            tol = step / 2 + q_ifc / 2 + TOL_LEN_ABS
            db, dt = fnum(e['lo_z']) - ev['bottom'][0], fnum(e['hi_z']) - ev['top'][0]
            dmax = max(abs(db), abs(dt))
            ok = dmax <= tol
            # convex corner radius of the section (RHS outer radius, U / L toe radius): a tool that bounds the
            # section's sharp-cornered rectangle reports up to r (sqrt 2 - 1) more on a rolled member
            rc = max(fnum(r['_prof'].get('r_outer')) or 0, fnum(r['_prof'].get('r_edge')) or 0)
            inside = db >= -tol and dt <= tol
            reason = '' if ok else ('rebuild_mismatch' if r['verify_status'] and r['verify_status'] != 'match' else
                                    r['dims_reason'] if r.get('dims_reason') in ('ifc_profile_edge_radius_exceeds_flange', 'ifc_section_evaluation')
                                    else 'tool_extent_ignores_corner_radius' if (rc and inside and dmax <= rc * (math.sqrt(2) - 1) + tol)
                                    else 'rebuilt_z_extent_differs')
            add(r, 'z_extent' + hw, 'Tekla Common.Bottom/Top elevation', ev['bottom'][0], fnum(e['lo_z']), tol, ok, reason,
                dict(d_bottom_mm=rd(db, 6), d_top_mm=rd(dt, 6), tool_top=rd(ev['top'][0], 9), rebuilt_top=fnum(e['hi_z'])))
        # ---------------- bbox (per-element MinX..MaxZ)
        bb = {k.split('.')[-1].lower().replace('_', ''): v for k, v, s in F['bbox']}
        if len(bb) == 6 and e.get('lo_x'):
            lo = [bb['minx'], bb['miny'], bb['minz']]
            hi = [bb['maxx'], bb['maxy'], bb['maxz']]
            rlo = [fnum(e['lo_x']), fnum(e['lo_y']), fnum(e['lo_z'])]
            rhi = [fnum(e['hi_x']), fnum(e['hi_y']), fnum(e['hi_z'])]
            step = max(s for k, v, s in F['bbox'])
            tol = TOL_BBOX_MM + step / 2
            dmax = max(max(abs(a - b) for a, b in zip(lo, rlo)), max(abs(a - b) for a, b in zip(hi, rhi)))
            add(r, 'bbox', 'MinX..MaxZ', 0.0, dmax, tol, dmax <= tol, '' if dmax <= tol else 'bbox_differs')
            if r['_b0'] is not None:
                o = [float(r['_b0'][c]) for c in ('ox', 'oy', 'oz')]
                inside = all(lo[i] - tol <= o[i] <= hi[i] + tol for i in range(3))
                add(r, 'origin_in_bbox', 'MinX..MaxZ', 0.0, 0.0, tol, inside, '' if inside else 'origin_outside')

    # ---------------- per-part wide summary
    by_part = collections.defaultdict(list)
    for d in long_rows:
        by_part[d['part_id']].append(d)
    for r in rows:
        for d in by_part.get(r['part_id'], []):
            c = d['check']
            if c + '_tool' in r:
                continue                               # primary source = first written (sorted keys; see tool())
            r[c + '_source'] = d['source']
            r[c + '_tool'] = d['tool_value']
            r[c + '_rebuilt'] = d['rebuilt_value']
            r[c + '_rel_diff'] = d['rel_diff']
            r[c + '_ok'] = d['ok']
            r[c + '_reason'] = d['reason']
        for k in ('_facts', '_e', '_pl', '_b0', '_swept', '_ratios', 'vnet', '_prof', '_cen', 'dims_reason'):
            r.pop(k, None)

    # ---------------- assemblies
    asm_rows = []
    asm_w = {}
    for gid, kv in slotted.items():
        for key, val in kv.get('asm_weight', {}).items():
            if key in usable:
                asm_w.setdefault(gid, (val, key, inv[key]['step']))
    part_asm_w = collections.defaultdict(set)
    for r in rows:
        for key, val in slotted.get(r['part_id'], {}).get('asm_weight', {}).items():
            if key in usable:
                part_asm_w[r['assembly_id']].add(round(val, 6))
    groups = collections.defaultdict(list)
    for r in rows:
        if r['assembly_id']:
            groups[r['assembly_id']].append(r)
    lr_by = collections.defaultdict(dict)
    for d in long_rows:
        lr_by[d['part_id']].setdefault(d['check'], d)
    def status(ok, part_rows):
        """assembly status: agree / explained (every disagreeing part has an explained reason) / unexplained"""
        if ok:
            return 'agree'
        cats = {reason_category(d['reason']) for d in part_rows if d is not None and d['ok'] is False}
        if not cats:
            return 'explained_by_rounding'             # all parts agree within their own rounding; the sum does not
        if cats <= {'explained'}:
            return 'explained'
        if 'unexplained' in cats:
            return 'unexplained'
        return 'tool_inconsistent' if 'tool_inconsistent' in cats else 'our_rebuild'

    for aid, rs in groups.items():
        steel = [r for r in rs if r['material_class'] in ('steel', 'steel?')]
        withw = [r for r in steel if lr_by[r['part_id']].get('mass_net', {}).get('ok') is not None]
        a = dict(assembly_id=aid, assembly_mark=rs[0]['assembly_mark'], n_parts=len(rs), n_steel=len(steel),
                 n_steel_with_net_weight=len(withw))
        if withw:
            ds = [lr_by[r['part_id']]['mass_net'] for r in withw]
            sm = sum(d['rebuilt_value'] for d in ds)
            st = sum(d['tool_value'] for d in ds)
            tol = TOL_REL_MASS * st + sum(inv[d['source']]['step'] / 2 for d in ds)
            ok = abs(sm - st) <= tol
            a.update(sum_rebuilt_mass_kg=rd(sm, 9), sum_tool_net_weight_kg=rd(st, 9), net_rel_diff=rd((sm - st) / st, 4) if st else None,
                     net_ok=ok, net_status=status(ok, ds))
            if rho_tool:
                smr = sum(r['rebuilt_volume_mm3'] * rho_tool for r in withw)
                okr = abs(smr - st) <= tol
                a.update(net_rel_diff_tool_density=rd((smr - st) / st, 4) if st else None, net_ok_tool_density=okr,
                         net_status_tool_density=status(okr, [dict(d, reason=d['reason'][len('tool_density+'):] if d['reason'].startswith('tool_density+') else d['reason'],
                                                                   ok=d['ok_at_tool_density']) for d in ds]))
        aw = asm_w.get(aid)
        if aw is None and len(part_asm_w.get(aid, ())) == 1:
            v = next(iter(part_asm_w[aid]))
            aw = (v, 'Tekla Assembly.Assembly/Cast unit weight (on parts)', inv.get('Tekla Assembly.Assembly/Cast unit weight', {}).get('step', 0.0))
        if aw is not None and aw[0] and steel and all(r['rebuilt_volume_mm3'] for r in steel):
            W, key, step = aw
            sm = sum(r['rebuilt_volume_mm3'] for r in steel) * RHO_STEEL
            smr = sum(r['rebuilt_volume_mm3'] for r in steel) * (rho_tool or RHO_STEEL)
            tds = [lr_by[r['part_id']].get('mass_tekla_weight') for r in steel]
            tol = TOL_REL_MASS * W + step / 2
            ok, okr = abs(sm - W) <= tol, abs(smr - W) <= tol
            a.update(tool_assembly_weight_kg=rd(W, 9), tool_assembly_weight_source=key,
                     sum_rebuilt_steel_mass_kg=rd(sm, 9), asm_rel_diff=rd((sm - W) / W, 4), asm_ok=ok,
                     asm_rel_diff_tool_density=rd((smr - W) / W, 4), asm_ok_tool_density=okr)
            consistent = None
            if all(d is not None and d['tool_value'] is not None for d in tds):
                ts = sum(d['tool_value'] for d in tds)
                qs = sum(inv[d['source']]['step'] / 2 for d in tds)
                consistent = abs(ts - W) <= TOL_REL_MASS * W + step / 2 + qs
                a.update(tool_sum_part_weights_kg=rd(ts, 9), tool_self_consistent=consistent)
            # the tool's assembly weight is the sum of its part WEIGHTs (gross for profiles): an assembly-level
            # disagreement is explained when the tool is self-consistent and every part's Weight check is explained
            if okr:
                a['asm_status_tool_density'] = 'agree'
            elif consistent is False:
                a['asm_status_tool_density'] = 'tool_inconsistent'
            elif consistent:
                a['asm_status_tool_density'] = status(False, [dict(d, reason=d['reason'][len('tool_density+'):] if d['reason'].startswith('tool_density+') else d['reason'],
                                                                   ok=d['ok_at_tool_density']) for d in tds])
            else:
                a['asm_status_tool_density'] = 'unexplained'
        # assembly Z extent: Tekla Assembly bottom / top elevation vs the rebuilt parts' (no bolts / welds) z range
        ae = elev.get(aid, {}).get('asm')
        if not ae or len(ae) < 2:
            vals = {tuple(sorted((k, v[0]) for k, v in elev.get(r['part_id'], {}).get('asm', {}).items())) for r in rs}
            vals.discard(())
            if len(vals) == 1:
                ae = next((elev[r['part_id']]['asm'] for r in rs if elev.get(r['part_id'], {}).get('asm')), None)
        geo = [ext.get(r['part_id'], {}) for r in rs if r['role'] not in ('bolt', 'weld') and r['material_class'] not in ('bolt', 'weld')]
        geo = [g for g in geo if g.get('lo_z')]
        if ae and len(ae) == 2 and geo:
            lo = min(fnum(g['lo_z']) for g in geo)
            hi = max(fnum(g['hi_z']) for g in geo)
            step = max(inv[ae[k][2]]['step'] for k in ('bottom', 'top'))
            tol = step / 2 + q_ifc / 2 + TOL_LEN_ABS
            dmax = max(abs(lo - ae['bottom'][0]), abs(hi - ae['top'][0]))
            a.update(tool_bottom_elevation_mm=rd(ae['bottom'][0], 9), tool_top_elevation_mm=rd(ae['top'][0], 9),
                     rebuilt_lo_z=rd(lo, 9), rebuilt_hi_z=rd(hi, 9), z_extent_max_diff_mm=rd(dmax, 6), z_extent_ok=dmax <= tol,
                     z_extent_parts_measured=len(geo))
        asm_rows.append(a)

    # ---------------- summary
    def rate(sel):
        n = [d for d in sel if d['ok'] is not None]
        ok = sum(1 for d in n if d['ok'])
        cat = collections.Counter(reason_category(d['reason']) for d in n if not d['ok'])
        return dict(compared=len(n), agree=ok, agree_pct=round(100 * ok / len(n), 2) if n else None,
                    disagree_by_category=dict(cat),
                    agree_or_explained_pct=round(100 * (ok + cat['explained']) / len(n), 2) if n else None,
                    unexplained_pct=round(100 * cat['unexplained'] / len(n), 2) if n else None,
                    not_compared=dict(collections.Counter(d['reason'] for d in sel if d['ok'] is None)),
                    reasons=dict(collections.Counter(d['reason'] for d in n if not d['ok']).most_common()))
    checks = collections.defaultdict(list)
    by_src = collections.defaultdict(list)
    for d in long_rows:
        checks[d['check']].append(d)
        by_src[(d['check'], d['source'])].append(d)
    primary = collections.defaultdict(list)            # one row per part per check (the primary source)
    for pid, cs in lr_by.items():
        for c, d in cs.items():
            primary[c].append(d)
    summ = dict(model=stem, ifc=os.path.basename(ifc) if ifc else None, fact_source=fact_source, schema=schema,
                originating_system=origin, parts=len(parts),
                parts_rebuilt=sum(1 for r in rows if r['rebuilt_volume_mm3']),
                material_classes=dict(collections.Counter(r['material_class'] for r in rows)),
                units={k: dict(to_target=v[0], unit=v[1], target={'mass': 'kg', 'volume': 'mm3', 'length': 'mm', 'area': 'mm2'}[k])
                       for k, v in units.items()},
                facts_inventory={k: {kk: vv for kk, vv in it.items()} for k, it in sorted(inv.items())},
                facts_usable=sorted(usable), facts_all_zero=sorted(k for k, it in inv.items() if it['all_zero']),
                numeric_facts_not_checked={f'{k} [{m}]': n for (k, m), n in sorted(unused.items(), key=lambda kv: -kv[1])},
                ifc_extrusion_depth_on_0p1mm_grid=round(on01, 4), ifc_geometry_quantum_mm=q_ifc,
                extents=dict(parts=len(ext), ok=sum(1 for x in ext.values() if x.get('ext_status') == 'ok'),
                             volume_differs_from_verification=sum(
                                 1 for r in rows if r['rebuilt_volume_mm3'] and fnum(ext.get(r['part_id'], {}).get('volume')) is not None
                                 and abs(fnum(ext[r['part_id']]['volume']) - r['rebuilt_volume_mm3']) > 1e-6 * r['rebuilt_volume_mm3'] + 1e-3)),
                tool_density_kg_per_m3=round(rho_tool * 1e9, 1) if rho_tool else None,
                tool_density_evidence_parts=len(steel_dens),
                checks_primary={c: rate(ds) for c, ds in sorted(primary.items())},
                checks_by_source={f'{c} | {s}': rate(ds) for (c, s), ds in sorted(by_src.items())},
                tolerances=dict(volume_rel=TOL_REL_VOL, mass_rel=TOL_REL_MASS, length_abs_mm=TOL_LEN_ABS,
                                plus='half the tool quantisation step of the source (+ half the IFC geometry quantum for lengths)',
                                section_group_rel=SECTION_GROUP_TOL, area_rel=TOL_REL_AREA, bbox_mm=TOL_BBOX_MM))
    # agreement on mass at the tool density
    mn = [d for d in primary.get('mass_net', []) if d['ok_at_tool_density'] is not None]
    if mn:
        summ['checks_primary']['mass_net']['agree_at_tool_density'] = sum(1 for d in mn if d['ok_at_tool_density'])
        summ['checks_primary']['mass_net']['agree_pct_at_tool_density'] = round(100 * summ['checks_primary']['mass_net']['agree_at_tool_density'] / len(mn), 2)
    # model totals (teammate's model-level check: total mass vs the tool's own NetWeight)
    tot = {}
    for c in ('mass_net', 'mass_tekla_weight', 'volume_net'):
        ds = [d for d in primary.get(c, []) if d['rebuilt_value'] is not None and d['tool_value'] is not None]
        if ds:
            R_ = sum(d['rebuilt_value'] for d in ds)
            T_ = sum(d['tool_value'] for d in ds)
            tot[c] = dict(parts=len(ds), rebuilt=rd(R_, 9), tool=rd(T_, 9), rel_diff=rd((R_ - T_) / T_, 4) if T_ else None)
            use_rho = c.startswith('mass') and rho_tool
            if use_rho:
                Rr = sum(d['rebuilt_value_tool_density'] for d in ds if d.get('rebuilt_value_tool_density') is not None)
                tot[c]['rel_diff_tool_density'] = rd((Rr - T_) / T_, 4) if T_ else None
            # what the model-level difference is made of: sum of (rebuilt - tool) per reason, as a share of the
            # tool total (masses at the tool's own density, so the density offset is shown on its own line)
            by = collections.defaultdict(float)
            for d in ds:
                rv = d['rebuilt_value_tool_density'] if use_rho and d.get('rebuilt_value_tool_density') is not None else d['rebuilt_value']
                rs_ = d['reason'][len('tool_density+'):] if d['reason'].startswith('tool_density+') else d['reason']
                by[rs_ or ('agree' if d['ok'] else 'not_compared')] += rv - d['tool_value']
            if use_rho and abs(rho_tool - RHO_STEEL) > 1e-12:
                by['density_7850_vs_tool'] = R_ - Rr
            tot[c]['diff_share_by_reason_pct'] = {k: round(100 * v / T_, 3) for k, v in sorted(by.items(), key=lambda kv: -abs(kv[1]))} if T_ else {}
    summ['model_totals'] = tot
    if asm_rows:
        def arate(key):
            n = [a for a in asm_rows if a.get(key) is not None]
            return dict(compared=len(n), agree=sum(1 for a in n if a[key]),
                        agree_pct=round(100 * sum(1 for a in n if a[key]) / len(n), 2) if n else None)
        def astat(key):
            c = collections.Counter(a[key] for a in asm_rows if a.get(key))
            n = sum(c.values())
            return dict(compared=n, status=dict(c), agree_or_explained_pct=round(100 * (c['agree'] + c['explained'] + c['explained_by_rounding']) / n, 2) if n else None)
        summ['assemblies'] = dict(n=len(asm_rows), net=arate('net_ok'), net_tool_density=arate('net_ok_tool_density'),
                                  net_status=astat('net_status'), net_status_tool_density=astat('net_status_tool_density'),
                                  assembly_weight=arate('asm_ok'), assembly_weight_tool_density=arate('asm_ok_tool_density'),
                                  assembly_weight_status_tool_density=astat('asm_status_tool_density'),
                                  z_extent=arate('z_extent_ok'),
                                  tool_assembly_weight_self_consistent=arate('tool_self_consistent'))
    summ['seconds'] = round(time.time() - t0, 1)

    # ---------------- write
    def wcsv(name, rs):
        cols = []
        for x in rs:
            for k in x:
                if k not in cols:
                    cols.append(k)
        with open(os.path.join(out, name), 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for x in rs:
                w.writerow(x)
    # section groups: the per-profile ratio rebuilt / tool net volume (the evidence behind 'section_definition')
    sec_rows = []
    seen_g = set()
    for (rkey, g), vals in sorted(grp.items(), key=lambda kv: (-len(kv[1]), kv[0][1], _primary_rank(kv[0][0][1]))):
        if rkey[0] != 'v_net' or len(vals) < 1 or g in seen_g:
            continue                                    # one row per group: its primary net-volume source
        seen_g.add(g)
        mem_ = [r for r in rows if gkey(r) == g]
        pr_ = profiles.get(g[2:], {}) if g.startswith('P:') else {}
        sv = sorted(vals)
        sa = sharp_area(pr_) if pr_ else None
        ra = fnum(mem_[0]['rebuilt_section_area_mm2']) if mem_ else None
        exp_ratio = ra / sa if (sa and ra) else None
        sec_rows.append(dict(group=g, source=rkey[1], kind=pr_.get('kind', mem_[0]['profile_kind'] if mem_ else ''),
                             profile_designation=pr_.get('designation', '') or (g[2:] if g.startswith('D:') else ''),
                             d=pr_.get('d', ''), b=pr_.get('b', ''), t=pr_.get('t', '') or pr_.get('tw', ''),
                             rebuilt_area_mm2=mem_[0]['rebuilt_section_area_mm2'] if mem_ else '',
                             parts=len(vals), distinct_volumes=len(grp_vol[(rkey, g)]),
                             median_ratio=rd(median(vals), 6), p05=rd(sv[int(0.05 * (len(sv) - 1))], 6),
                             p95=rd(sv[int(0.95 * (len(sv) - 1))], 6),
                             sharp_section_area_mm2=rd(sa, 9), expected_ratio_sharp_section=rd(exp_ratio, 6),
                             explained_by_sharp_section=(abs(median(vals) / exp_ratio - 1) <= SECTION_GROUP_TOL) if exp_ratio else None))
    wcsv('tekla_section_groups.csv', sec_rows)
    off = [x for x in sec_rows if x['median_ratio'] is not None and abs(x['median_ratio'] - 1) > TOL_REL_VOL]
    summ['section_groups'] = dict(groups=len(sec_rows), groups_off_1=len(off), parts_in_off_groups=sum(x['parts'] for x in off),
                                  off_groups_explained_by_sharp_section=sum(1 for x in off if x['explained_by_sharp_section']),
                                  parts_explained_by_sharp_section=sum(x['parts'] for x in off if x['explained_by_sharp_section']))
    wcsv('tekla_parts.csv', rows)
    wcsv('tekla_checks_long.csv', long_rows)
    wcsv('tekla_assemblies.csv', asm_rows)
    json.dump(summ, open(os.path.join(out, 'tekla_summary.json'), 'w'), indent=1, default=str)
    return summ


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder', help='schedule folder (parts.csv, part_properties.jsonl, verification.csv, ...)')
    ap.add_argument('--ifc', default='', help='source IFC (.ifc or zipped); without it part_properties.jsonl is used')
    ap.add_argument('--out', default='', help='output folder (default: the schedule folder)')
    ap.add_argument('--extents', choices=('auto', 'run', 'skip'), default='auto')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--kit', default=os.path.join(HERE, '..', 'pm', 'kit'), help='folder holding steelbuild.py')
    ap.add_argument('--stem', default='')
    a = ap.parse_args()
    s = check_model(a.folder, a.ifc or None, a.out or a.folder, a.extents, a.jobs, os.path.abspath(a.kit), a.stem or None)
    print(json.dumps({k: s[k] for k in ('model', 'parts', 'facts_usable', 'facts_all_zero', 'tool_density_kg_per_m3',
                                        'checks_primary', 'model_totals') if k in s}, indent=1, default=str))


if __name__ == '__main__':
    main()
