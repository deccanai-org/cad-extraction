"""Cited dimension tables for the BLUE (standard) builders. Inch tables are basic (nominal) dimensions in inches;
every builder converts to mm (IN = 25.4 exactly). Each table carries its citation in CITES[<table name>].

What is a standard here and what is not (the honesty rule of the completion):
  * a value read from one of these tables for a size the source data gives  -> BLUE (cite table + row);
  * a choice the source does not make (which grade family, which grating spacing, which joist chord angles,
    head side, washer count) -> AMBER, even when the candidate values come from a table (the basis says why).
Rows marked with a note in CITES were transcribed from the standard's published table; the unit tests re-derive the
regular ones from the standards' own size formulas (heavy hex F = 1.5D + 1/8, H = D - 1/64; J3.3 hole = d + 1/16 ...).
"""
from fractions import Fraction as _F

IN = 25.4
LB_PER_FT_PER_IN2 = 3.4  # steel, 490 lb/ft3: 1 in2 of section weighs 3.40 lb/ft (AISC Manual Part 1)


def f(s):
    """'1-15/32' / '15/32' / '1' -> float inches"""
    s = str(s).strip()
    if '-' in s:
        a, b = s.split('-')
        return float(_F(a)) + float(_F(b))
    return float(_F(s))


CITES = {
    'HEAVY_HEX_BOLT': 'ASME B18.2.6-2019 Table 1 (heavy hex structural bolts, ASTM F3125 Grades A325/A490/F1852/F2280); '
                      'same values: AISC Steel Construction Manual 15th ed. Table 7-14 / RCSC 2020 Table C-2.1',
    'HEAVY_HEX_NUT': 'ASME B18.2.6-2019 Table 3 (heavy hex nuts for structural bolts, ASTM A563 DH / A194 2H) for '
                     '1/2-1 1/2 in; ASME B18.2.2-2015 heavy hex nuts (ASTM A563) for 1/4-7/16 in; '
                     'basic F = 1 1/2 D + 1/8 in (1/2-1 1/2 in), H = D - 1/64 in (to 1 1/8 in) / D - 1/32 in (1 1/4-1 1/2 in)',
    'HEX_BOLT': 'ASME B18.2.1-2012 Table 2 (hex bolts, ASTM A307 Grade A): width across flats F, head height H (basic)',
    'HEX_NUT': 'ASME B18.2.2-2015 Table 2 (hex nuts, ASTM A563 Grade A): width across flats F, thickness H (basic)',
    'F436_WASHER': 'ASTM F436/F436M-19 Table 1 (circular hardened steel washers): nominal ID, OD, thickness min / max; '
                   'thickness modelled = 5/32 in for 1/2-1 1/2 in (the RCSC Table C-2.2 allowance per flat washer), '
                   'else the mid-tolerance thickness',
    'GRIP_ADD': 'RCSC Specification for Structural Joints Using High-Strength Bolts (2020), Commentary Table C-2.2 '
                '(= AISC Manual Table 7-15): length to add to the grip; + 5/32 in per F436 washer; total rounded up to '
                'the next 1/4 in (L <= 5 in) or 1/2 in (L > 5 in)',
    'HOLES_J3_3': 'AISC 360-16 Table J3.3 (nominal hole dimensions, in.): standard, oversized, short-slot, long-slot',
    'STUDS_AWS': 'AWS D1.1/D1.1M:2020 Figure 9.1 (Figure 7.1 in the 2015 ed.) standard-type headed studs (Type B): '
                 'shank diameter C, head diameter H, minimum head height T',
    'STUDS_NELSON': 'Nelson Stud Welding H4L headed concrete anchor catalogue (sizes below the AWS table: 1/4, 3/8 in)',
    'REBAR_A615': 'ASTM A615/A615M-22 Table 1 (deformed bar designation numbers, nominal weights, nominal dimensions)',
    'REBAR_BEND': 'ACI 318-19 Table 25.3.1 (minimum inside bend diameter of standard hooks: #3-#8 6db, #9-#11 8db, '
                  '#14-#18 10db) and Table 25.3.2 (stirrups / ties #3-#5: 4db)',
    'HSS_AISC': 'AISC Steel Construction Manual 15th ed. Part 1 (Tables 1-11 / 1-12 / 1-13): ASTM A500 HSS design wall '
                'thickness t_des = 0.93 t_nom (AISC 360-16 B4.2); section properties computed with the outside corner '
                'radius = 2.0 t_des (inside radius = t_des)',
    'SJI_K': 'Steel Joist Institute SJI 100-2020 (Standard Specification for K-Series, LH-Series and DLH-Series Open Web '
             'Steel Joists): nominal depth = the designation number (in.), K / KCS standard end bearing depth 2 1/2 in, '
             'LH / DLH 5 in; K-Series Standard Load Table approximate weight (lb/ft) for the weight check',
    'NAAMM_MBG531': 'NAAMM ANSI/NAAMM MBG 531-17 Metal Bar Grating Manual: welded steel grating type designations '
                    '(19-W-4 = bearing bars at 1 3/16 in centres, cross bars at 4 in centres; 15-W-4 = 15/16 in; '
                    '19-W-2 = cross bars at 2 in), cross bars flush with the top of the bearing bars',
    'ANCHOR_14_2': 'AISC Steel Construction Manual 15th ed. Table 14-2 (recommended sizes for anchor-rod holes in base '
                   'plates; minimum washer dimension and thickness); rods ASTM F1554, nuts ASTM A563 heavy hex '
                   '(ASME B18.2.2); hooked rods: ACI 318-19 17.6.3.2.2 (3 da <= eh <= 4.5 da)',
}

# ---------------------------------------------------------------- heavy hex structural bolt: D: (F, H, thread length)
HEAVY_HEX_BOLT = {
    0.5: (f('7/8'), f('5/16'), 1.0), 0.625: (f('1-1/16'), f('25/64'), 1.25), 0.75: (1.25, f('15/32'), f('1-3/8')),
    0.875: (f('1-7/16'), f('35/64'), 1.5), 1.0: (f('1-5/8'), f('39/64'), 1.75), 1.125: (f('1-13/16'), f('11/16'), 2.0),
    1.25: (2.0, f('25/32'), 2.0), 1.375: (f('2-3/16'), f('27/32'), 2.25), 1.5: (f('2-3/8'), f('15/16'), 2.25),
}

# ---------------------------------------------------------------- heavy hex nut: D: (F, H)
HEAVY_HEX_NUT = {
    0.25: (0.5, f('15/64')), 0.3125: (f('9/16'), f('19/64')), 0.375: (f('11/16'), f('23/64')), 0.4375: (0.75, f('27/64')),
    0.5: (f('7/8'), f('31/64')), 0.625: (f('1-1/16'), f('39/64')), 0.75: (1.25, f('47/64')), 0.875: (f('1-7/16'), f('55/64')),
    1.0: (f('1-5/8'), f('63/64')), 1.125: (f('1-13/16'), f('1-7/64')), 1.25: (2.0, f('1-7/32')), 1.375: (f('2-3/16'), f('1-11/32')),
    1.5: (f('2-3/8'), f('1-15/32')),
}  # sizes above 1 1/2 in are left out on purpose (not transcribed): a builder asked for one returns None

# ---------------------------------------------------------------- hex bolt (A307) and hex nut: D: (F, H)
HEX_BOLT = {
    0.25: (f('7/16'), f('11/64')), 0.3125: (0.5, f('7/32')), 0.375: (f('9/16'), 0.25), 0.4375: (f('5/8'), f('19/64')),
    0.5: (0.75, f('11/32')), 0.625: (f('15/16'), f('27/64')), 0.75: (f('1-1/8'), 0.5), 0.875: (f('1-5/16'), f('37/64')),
    1.0: (1.5, f('43/64')), 1.125: (f('1-11/16'), 0.75), 1.25: (f('1-7/8'), f('27/32')), 1.375: (f('2-1/16'), f('29/32')),
    1.5: (2.25, 1.0),
}
HEX_NUT = {
    0.25: (f('7/16'), f('7/32')), 0.3125: (0.5, f('17/64')), 0.375: (f('9/16'), f('21/64')), 0.4375: (f('11/16'), 0.375),
    0.5: (0.75, f('7/16')), 0.625: (f('15/16'), f('35/64')), 0.75: (f('1-1/8'), f('41/64')), 0.875: (f('1-5/16'), 0.75),
    1.0: (1.5, f('55/64')), 1.125: (f('1-11/16'), f('31/32')), 1.25: (f('1-7/8'), f('1-1/16')), 1.375: (f('2-1/16'), f('1-11/64')),
    1.5: (2.25, f('1-9/32')),
}

# ---------------------------------------------------------------- F436 circular washer: D: (ID, OD, t_min, t_max)
F436_WASHER = {
    0.25: (f('9/32'), f('5/8'), 0.051, 0.080), 0.3125: (f('11/32'), f('11/16'), 0.051, 0.080),
    0.375: (f('13/32'), f('13/16'), 0.051, 0.080), 0.4375: (f('15/32'), f('59/64'), 0.051, 0.080),
    0.5: (f('17/32'), f('1-1/16'), 0.097, 0.177), 0.625: (f('21/32'), f('1-5/16'), 0.122, 0.177),
    0.75: (f('13/16'), f('1-15/32'), 0.122, 0.177), 0.875: (f('15/16'), f('1-3/4'), 0.136, 0.177),
    1.0: (f('1-1/8'), 2.0, 0.136, 0.177), 1.125: (f('1-1/4'), 2.25, 0.136, 0.177), 1.25: (f('1-3/8'), 2.5, 0.136, 0.177),
    1.375: (f('1-1/2'), 2.75, 0.136, 0.177), 1.5: (f('1-5/8'), 3.0, 0.136, 0.177),
}
F436_FLAT_ALLOWANCE = f('5/32')  # RCSC Table C-2.2 note: add 5/32 in for each flat washer

# ---------------------------------------------------------------- length to add to grip (RCSC Table C-2.2): D: add
GRIP_ADD = {0.5: f('11/16'), 0.625: f('7/8'), 0.75: 1.0, 0.875: f('1-1/8'), 1.0: f('1-1/4'), 1.125: 1.5,
            1.25: f('1-5/8'), 1.375: f('1-3/4'), 1.5: f('1-7/8')}

# ---------------------------------------------------------------- AISC 360-16 Table J3.3: d: (std dia, oversize dia, (short w, l), (long w, l))
HOLES_J3_3 = {
    0.5: (f('9/16'), f('5/8'), (f('9/16'), f('11/16')), (f('9/16'), f('1-1/4'))),
    0.625: (f('11/16'), f('13/16'), (f('11/16'), f('7/8')), (f('11/16'), f('1-9/16'))),
    0.75: (f('13/16'), f('15/16'), (f('13/16'), 1.0), (f('13/16'), f('1-7/8'))),
    0.875: (f('15/16'), f('1-1/16'), (f('15/16'), f('1-1/8')), (f('15/16'), f('2-3/16'))),
    1.0: (f('1-1/16'), 1.25, (f('1-1/16'), f('1-5/16')), (f('1-1/16'), 2.5)),
}

# ---------------------------------------------------------------- headed studs: C: (head dia H, min head height T, source)
STUDS = {
    0.25: (0.5, f('3/16'), 'STUDS_NELSON'), 0.375: (0.75, f('9/32'), 'STUDS_NELSON'),
    0.5: (1.0, 0.281, 'STUDS_AWS'), 0.625: (1.25, 0.281, 'STUDS_AWS'), 0.75: (1.25, 0.375, 'STUDS_AWS'),
    0.875: (1.375, 0.375, 'STUDS_AWS'), 1.0: (1.625, 0.5, 'STUDS_AWS'),
}

# ---------------------------------------------------------------- ASTM A615 bars: number: (nominal dia in, area in2, weight lb/ft)
REBAR_A615 = {
    3: (0.375, 0.11, 0.376), 4: (0.5, 0.20, 0.668), 5: (0.625, 0.31, 1.043), 6: (0.75, 0.44, 1.502),
    7: (0.875, 0.60, 2.044), 8: (1.0, 0.79, 2.670), 9: (1.128, 1.00, 3.400), 10: (1.270, 1.27, 4.303),
    11: (1.410, 1.56, 5.313), 14: (1.693, 2.25, 7.650), 18: (2.257, 4.00, 13.600),
}
# soft-metric A615M designation -> inch-pound number
REBAR_METRIC = {10: 3, 13: 4, 16: 5, 19: 6, 22: 7, 25: 8, 29: 9, 32: 10, 36: 11, 43: 14, 57: 18}

# ---------------------------------------------------------------- AISC Table 14-2: rod d: (hole dia, min washer dim, min washer t)
ANCHOR_14_2 = {
    0.75: (f('1-5/16'), 2.0, 0.25), 0.875: (f('1-9/16'), 2.5, f('5/16')), 1.0: (f('1-13/16'), 3.0, 0.375),
    1.25: (f('2-1/16'), 3.0, 0.5), 1.5: (f('2-5/16'), 3.5, 0.5), 1.75: (f('2-3/4'), 4.0, f('5/8')),
    2.0: (f('3-1/4'), 5.0, 0.75), 2.5: (f('3-3/4'), 5.5, f('7/8')),
}

# ---------------------------------------------------------------- SJI K-series approximate weight (lb/ft), K-Series Standard Load Table
SJI_K_WEIGHT = {
    '8K1': 5.1, '10K1': 5.0, '12K1': 5.0, '12K3': 5.7, '12K5': 7.1, '14K1': 5.2, '14K3': 6.0, '14K4': 6.7, '14K6': 7.7,
    '16K2': 5.5, '16K3': 6.3, '16K4': 7.0, '16K5': 7.5, '16K6': 8.1, '16K7': 8.6, '16K9': 10.0,
    '18K3': 6.6, '18K4': 7.2, '18K5': 7.7, '18K6': 8.5, '18K7': 9.0, '18K9': 10.2, '18K10': 11.7,
    '20K3': 6.7, '20K4': 7.6, '20K5': 8.2, '20K6': 8.9, '20K7': 9.3, '20K9': 10.8, '20K10': 12.2,
    '22K4': 8.0, '22K5': 8.8, '22K6': 9.2, '22K7': 9.7, '22K9': 11.3, '22K10': 12.6, '22K11': 13.8,
    '24K4': 8.4, '24K5': 9.3, '24K6': 9.7, '24K7': 10.1, '24K8': 11.5, '24K9': 12.0, '24K10': 13.1, '24K12': 16.0,
    '26K5': 9.8, '26K6': 10.6, '26K7': 10.9, '26K8': 12.1, '26K9': 12.2, '26K10': 13.8, '26K12': 16.6,
    '28K6': 11.4, '28K7': 11.8, '28K8': 12.7, '28K9': 13.0, '28K10': 14.3, '28K12': 17.1,
    '30K7': 12.3, '30K8': 13.2, '30K9': 13.4, '30K10': 15.0, '30K11': 16.4, '30K12': 17.6,
}
SJI_SEAT_DEPTH = {'K': 2.5, 'KCS': 2.5, 'LH': 5.0, 'DLH': 5.0}

# ---------------------------------------------------------------- NAAMM MBG 531 welded grating types: name: (bearing bar pitch, cross bar pitch)
GRATING_TYPES = {'19-W-4': (f('1-3/16'), 4.0), '15-W-4': (f('15/16'), 4.0), '19-W-2': (f('1-3/16'), 2.0),
                 '15-W-2': (f('15/16'), 2.0), '11-W-4': (f('11/16'), 4.0), '7-W-4': (f('7/16'), 4.0)}
GRATING_CROSS_BAR = 0.25  # in, the usual welded-grating cross bar (1/4 in twisted square, modelled as a 1/4 in square bar)


def nearest(table, d_in, tol_in=0.02):
    """the table key closest to d_in when within tol_in (metric-rounded inch sizes: 19.05 mm -> 0.75)"""
    k = min(table, key=lambda x: abs(x - d_in))
    return k if abs(k - d_in) <= tol_in else None


def frac(x):
    """0.75 -> '3/4', 1.375 -> '1 3/8' (64ths)"""
    n = round(x * 64)
    w, r = divmod(n, 64)
    if r == 0:
        return str(w)
    fr = _F(r, 64)
    return (f'{w} ' if w else '') + f'{fr.numerator}/{fr.denominator}'
