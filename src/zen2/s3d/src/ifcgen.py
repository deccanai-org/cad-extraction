"""IFC4 writer for S3D extracted JSON (piping / structure / equipment), one file per area chunk.

Geometry policy (property S3D_Geometry.Method on every element):
  exact       - pipes (port points + OD + wall), linear members (axis + catalog profile + roll + cardinal point), nozzles
  parametric  - elbows (revolved, bend radius/angle from ports & turn feature), tees, reducers, flanges (REFDATBoltedEndData),
                olets, caps, blind flanges, equipment primitives (A-E parameters + placement matrix)
  approximate - valves / instruments / specialties (symbol-only bodies: cones + stem/actuator), support components (bbox),
                symbol-only equipment (bbox), unknown sections
Local origin per file (coordinates reach 7.4 km): recorded as IfcMapConversion + S3D_LocalOrigin pset on the site.
"""
import math, time, collections
import numpy as np
import ifcopenshell, ifcopenshell.guid

EPS = 1e-9


def unit(v):
    v = np.asarray(v, float); n = np.linalg.norm(v)
    return v / n if n > EPS else None


def perp(z):
    z = unit(z)
    a = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = a - z * (a @ z)
    return unit(x)


def guid_of(oid, salt=''):
    h = (oid or '').replace('-', '').lower()
    if salt or len(h) != 32:
        import hashlib
        h = hashlib.md5((oid + '|' + salt).encode()).hexdigest()
    return ifcopenshell.guid.compress(h)


COLORS = {
    'PIPE': (0.40, 0.46, 0.52), 'FITTING': (0.42, 0.55, 0.72), 'FLANGE': (0.72, 0.66, 0.42), 'VALVE': (0.82, 0.18, 0.16),
    'INSTRUMENT': (0.93, 0.58, 0.10), 'MISC': (0.60, 0.42, 0.72), 'SUPPORT': (0.38, 0.38, 0.40),
    'Beam': (0.86, 0.52, 0.18), 'Column': (0.70, 0.36, 0.14), 'Brace': (0.92, 0.70, 0.28), 'Handrail': (0.95, 0.86, 0.18),
    'MEMBER': (0.80, 0.60, 0.30), 'EQUIPMENT': (0.28, 0.50, 0.80), 'NOZZLE': (0.18, 0.33, 0.62), 'EQUIP_BBOX': (0.55, 0.62, 0.80),
}


class IfcW:
    def __init__(self, name, origin, site_name, meta_props=None):
        f = self.f = ifcopenshell.file(schema='IFC4')
        self.origin = np.array(origin, float)
        self._dirs = {}; self._prof = {}; self._styles = {}
        self.stats = collections.Counter()
        self.o3 = f.createIfcCartesianPoint((0., 0., 0.))
        self.p2 = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0., 0.)), None)
        self.id3 = f.createIfcAxis2Placement3D(self.o3, None, None)
        units = f.createIfcUnitAssignment([f.createIfcSIUnit(None, 'LENGTHUNIT', None, 'METRE'),
                                           f.createIfcSIUnit(None, 'PLANEANGLEUNIT', None, 'RADIAN'),
                                           f.createIfcSIUnit(None, 'MASSUNIT', 'KILO', 'GRAM'),
                                           f.createIfcSIUnit(None, 'AREAUNIT', None, 'SQUARE_METRE'),
                                           f.createIfcSIUnit(None, 'VOLUMEUNIT', None, 'CUBIC_METRE')])
        self.ctx = f.createIfcGeometricRepresentationContext(None, 'Model', 3, 1e-5, self.id3, f.createIfcDirection((0., 1., 0.)))
        self.body = f.createIfcGeometricRepresentationSubContext('Body', 'Model', None, None, None, None, self.ctx, None, 'MODEL_VIEW', None)
        org = f.createIfcOrganization(None, 'S3D-extract', None, None, None)
        app = f.createIfcApplication(org, '1.0', 's3d2ifc (licence-free Smart 3D v13 reader)', 's3d2ifc')
        self.oh = f.createIfcOwnerHistory(f.createIfcPersonAndOrganization(f.createIfcPerson(None, None, 's3d2ifc'), org, None),
                                          app, None, 'NOCHANGE', None, None, None, int(time.time()))
        self.proj = f.createIfcProject(ifcopenshell.guid.new(), self.oh, name, 'Smart 3D v13 model MLNG@1', None, None, None, [self.ctx], units)
        crs = f.createIfcProjectedCRS('S3D-MLNG@1-GLOBAL', 'Smart 3D global model frame (X east, Y north, Z up), metres', None, None, None, None, None)
        f.createIfcMapConversion(self.ctx, crs, float(self.origin[0]), float(self.origin[1]), float(self.origin[2]), 1.0, 0.0, 1.0)
        self.site_pl = f.createIfcLocalPlacement(None, self.id3)
        self.site = f.createIfcSite(ifcopenshell.guid.new(), self.oh, site_name, None, None, self.site_pl, None, None, 'ELEMENT', None, None, None, None, None)
        f.createIfcRelAggregates(ifcopenshell.guid.new(), self.oh, None, None, self.proj, [self.site])
        props = {'OffsetX_m': float(self.origin[0]), 'OffsetY_m': float(self.origin[1]), 'OffsetZ_m': float(self.origin[2]),
                 'Note': 'global S3D coordinate = local IFC coordinate + offset'}
        props.update(meta_props or {})
        self.pset(self.site, 'S3D_LocalOrigin', props)
        self.contained = []
        self.groups = collections.defaultdict(list)

    # ------------------------------------------------------------ primitives
    def P(self, p):
        q = np.asarray(p, float) - self.origin
        return self.f.createIfcCartesianPoint((float(q[0]), float(q[1]), float(q[2])))

    def Pl(self, p):
        q = np.asarray(p, float)
        return self.f.createIfcCartesianPoint((float(q[0]), float(q[1]), float(q[2])))

    def D(self, v):
        v = unit(v)
        k = tuple(round(float(x), 9) for x in v)
        d = self._dirs.get(k)
        if d is None:
            d = self._dirs[k] = self.f.createIfcDirection(k)
        return d

    def ax(self, loc, z, x, local=False):
        z = unit(z)
        x = np.asarray(x, float); x = x - z * (x @ z); x = unit(x)
        if x is None:
            x = perp(z)
        return self.f.createIfcAxis2Placement3D(self.Pl(loc) if local else self.P(loc), self.D(z), self.D(x))

    def lp(self, loc, z, x):
        return self.f.createIfcLocalPlacement(self.site_pl, self.ax(loc, z, x))

    def lp0(self):
        if getattr(self, '_lp0', None) is None:
            self._lp0 = self.f.createIfcLocalPlacement(self.site_pl, self.f.createIfcAxis2Placement3D(self.P(self.origin), None, None))
        return self._lp0

    def prof(self, key, fn):
        p = self._prof.get(key)
        if p is None:
            p = self._prof[key] = fn()
        return p

    def circ(self, r, t=None):
        r = max(float(r), 1e-4)
        if t and 0 < t < r * 0.95:
            return self.prof(('ch', round(r, 5), round(t, 5)), lambda: self.f.createIfcCircleHollowProfileDef('AREA', None, self.p2, r, float(t)))
        return self.prof(('c', round(r, 5)), lambda: self.f.createIfcCircleProfileDef('AREA', None, self.p2, r))

    def extrude(self, profile, depth, pos=None):
        return self.f.createIfcExtrudedAreaSolid(profile, pos or self.id3, self.D((0, 0, 1)), float(max(depth, 1e-5)))

    def cyl(self, p0, p1, r, t=None, local=False):
        """solid/hollow cylinder between two points (world coords unless local)"""
        a = np.asarray(p1, float) - np.asarray(p0, float); L = np.linalg.norm(a)
        if L < 1e-5:
            return None
        pos = self.ax(p0, a, perp(a), local=local)
        return self.extrude(self.circ(r, t), L, pos)

    def frustum(self, p0, p1, r0, r1, t=None, local=False):
        """cone frustum as revolved polygon (hollow if t)"""
        a = np.asarray(p1, float) - np.asarray(p0, float); L = float(np.linalg.norm(a))
        if L < 1e-5:
            return None
        r0 = max(float(r0), 1e-4); r1 = max(float(r1), 1e-4)
        if abs(r0 - r1) < 1e-5:
            return self.cyl(p0, p1, r0, t, local)
        if t and t < min(r0, r1) * 0.95:
            pts = [(r0 - t, 0.), (r0, 0.), (r1, L), (r1 - t, L)]
        else:
            pts = [(0., 0.), (r0, 0.), (r1, L), (0., L)]
        f = self.f
        poly = f.createIfcPolyline([f.createIfcCartesianPoint(p) for p in pts + [pts[0]]])
        prof = f.createIfcArbitraryClosedProfileDef('AREA', None, poly)
        pz = perp(a)                       # position Z: perpendicular to the axis; position Y = axis
        px = np.cross(unit(a), pz)         # X = Y x Z
        pos = self.ax(p0, pz, px, local=local)
        axis = f.createIfcAxis1Placement(self.o3, self.D((0, 1, 0)))
        return f.createIfcRevolvedAreaSolid(prof, pos, axis, 2 * math.pi)

    def revolve_rh(self, p0, axis, rh):
        """solid of revolution about axis through p0 from (radius, height) points (closed to the axis)"""
        f = self.f
        pts = [(0.0, 0.0)] + [(float(r), float(h)) for r, h in rh] + [(0.0, float(rh[-1][1]))]
        dd = []
        for q in pts:
            if not dd or abs(q[0] - dd[-1][0]) > 1e-6 or abs(q[1] - dd[-1][1]) > 1e-6:
                dd.append(q)
        poly = f.createIfcPolyline([f.createIfcCartesianPoint(q) for q in dd + [dd[0]]])
        prof = f.createIfcArbitraryClosedProfileDef('AREA', None, poly)
        a = unit(axis); pz = perp(a); px = np.cross(a, pz)
        return f.createIfcRevolvedAreaSolid(prof, self.ax(p0, pz, px), f.createIfcAxis1Placement(self.o3, self.D((0, 1, 0))), 2 * math.pi)

    def torus_bend(self, p1, t1, n1, R, ang, r, t=None):
        """revolved circle: start at p1, tangent t1, bend centre at p1 + n1*R, sweep angle ang"""
        f = self.f
        pos = self.ax(p1, t1, n1)
        axis = f.createIfcAxis1Placement(f.createIfcCartesianPoint((float(R), 0., 0.)), self.D((0, 1, 0)))
        return f.createIfcRevolvedAreaSolid(self.circ(r, t), pos, axis, float(ang))

    def box(self, center, x, y, z, dx, dy, dz):
        """box centred at center with local axes x,y,z and full sizes dx,dy,dz (world coords)"""
        f = self.f
        base = np.asarray(center, float) - unit(z) * dz / 2
        prof = self.prof(('r', round(dx, 5), round(dy, 5)), lambda: f.createIfcRectangleProfileDef('AREA', None, self.p2, float(max(dx, 1e-4)), float(max(dy, 1e-4))))
        return self.extrude(prof, dz, self.ax(base, z, x))

    def mesh(self, verts, tris):
        f = self.f
        pl = f.createIfcCartesianPointList3D([tuple(float(c) for c in (np.asarray(v) - self.origin)) for v in verts])
        return f.createIfcTriangulatedFaceSet(pl, None, True, [tuple(int(i) + 1 for i in t) for t in tris], None)

    def loft(self, c0, c1, n0, r0, r1, xref, off1=None, seg=24):
        """closed mesh between two parallel circles (eccentric reducer): centres c0, c1, common normal n0"""
        n0 = unit(n0); xa = perp(n0) if xref is None else unit(np.asarray(xref) - n0 * (np.asarray(xref) @ n0))
        ya = np.cross(n0, xa)
        V = []
        for c, r in ((c0, r0), (c1, r1)):
            for k in range(seg):
                a = 2 * math.pi * k / seg
                V.append(np.asarray(c) + r * (math.cos(a) * xa + math.sin(a) * ya))
        V.append(np.asarray(c0)); V.append(np.asarray(c1))
        T = []
        for k in range(seg):
            k1 = (k + 1) % seg
            T += [(k, k1, seg + k1), (k, seg + k1, seg + k)]
            T += [(2 * seg, k1, k), (2 * seg + 1, seg + k, seg + k1)]
        return self.mesh(V, T)

    def brep(self, V, F, closed=True):
        """ACIS-derived polygon faces -> IfcFacetedBrep (closed) or IfcFaceBasedSurfaceModel (open); coords world metres"""
        f = self.f
        pts = [f.createIfcCartesianPoint(tuple(float(c) for c in (v - self.origin))) for v in V]
        faces = []
        for lo, hs in F:
            bounds = [f.createIfcFaceOuterBound(f.createIfcPolyLoop([pts[i] for i in lo]), True)]
            for h in hs:
                bounds.append(f.createIfcFaceBound(f.createIfcPolyLoop([pts[i] for i in h]), True))
            faces.append(f.createIfcFace(bounds))
        if not faces:
            return None
        if closed:
            return f.createIfcFacetedBrep(f.createIfcClosedShell(faces))
        return f.createIfcFaceBasedSurfaceModel([f.createIfcConnectedFaceSet(faces)])

    def style(self, key):
        s = self._styles.get(key)
        if s is None:
            c = COLORS.get(key, (0.6, 0.6, 0.6))
            f = self.f
            col = f.createIfcColourRgb(None, *c)
            rend = f.createIfcSurfaceStyleShading(col, 0.0)
            s = self._styles[key] = f.createIfcSurfaceStyle(key, 'BOTH', [rend])
        return s

    # ------------------------------------------------------------ elements
    def element(self, cls, name, items, placement=None, oid=None, style='MISC', predefined=None, object_type=None,
                psets=None, rep_type='SweptSolid', group=None, tag=None, salt=''):
        items = [i for i in items if i is not None]
        if not items:
            self.stats['no_geometry'] += 1
            return None
        f = self.f
        st = self.style(style)
        for it in items:
            f.createIfcStyledItem(it, [st], None)
        if rep_type in ('Brep', 'SurfaceModel'):
            pass
        elif any(i.is_a('IfcTriangulatedFaceSet') for i in items):
            rep_type = 'Tessellation' if all(i.is_a('IfcTriangulatedFaceSet') for i in items) else 'SolidModel'
        elif any(i.is_a('IfcRevolvedAreaSolid') for i in items) and rep_type == 'SweptSolid':
            rep_type = 'SweptSolid'
        rep = f.createIfcShapeRepresentation(self.body, 'Body', rep_type, items)
        kw = dict(GlobalId=guid_of(oid, salt) if oid else ifcopenshell.guid.new(), OwnerHistory=self.oh, Name=(name or '')[:250],
                  ObjectPlacement=placement or self.lp0(), Representation=f.createIfcProductDefinitionShape(None, None, [rep]),
                  Tag=(tag or oid or '')[:250] or None)
        if object_type:
            kw['ObjectType'] = object_type[:250]
        if predefined:
            kw['PredefinedType'] = predefined
        e = f.create_entity(cls, **kw)
        if psets:
            for pn, props in psets.items():
                self.pset(e, pn, props)
        self.contained.append(e)
        if group:
            self.groups[group].append(e)
        self.stats[cls] += 1
        return e

    def pset(self, e, name, props):
        f = self.f
        vals = []
        for k, v in props.items():
            if v is None or v == '' or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                continue
            if isinstance(v, bool):
                nv = f.createIfcBoolean(v)
            elif isinstance(v, int):
                nv = f.createIfcInteger(v)
            elif isinstance(v, float):
                nv = f.createIfcReal(v)
            else:
                s = str(v)
                nv = f.createIfcLabel(s[:255]) if len(s) <= 255 else f.createIfcText(s[:2000])
            vals.append(f.createIfcPropertySingleValue(k, None, nv, None))
        if not vals:
            return
        ps = f.createIfcPropertySet(ifcopenshell.guid.new(), self.oh, name, None, vals)
        f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), self.oh, None, None, [e], ps)

    def write(self, path, group_cls='IfcDistributionSystem'):
        f = self.f
        for gname, els in self.groups.items():
            if group_cls == 'IfcDistributionSystem':
                g = f.createIfcDistributionSystem(ifcopenshell.guid.new(), self.oh, gname[:250], None, 'PROCESS PIPING', None, 'USERDEFINED')
            else:
                g = f.createIfcGroup(ifcopenshell.guid.new(), self.oh, gname[:250], None, None)
            f.createIfcRelAssignsToGroup(ifcopenshell.guid.new(), self.oh, None, None, els, None, g)
        if self.contained:
            f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), self.oh, None, None, self.contained, self.site)
        f.write(path)


# ============================================================== piping
def _v(x):
    return np.asarray(x, float) if x is not None else None


def comp_geometry(W, C, wall_hint):
    """-> (items, method, notes) for one piping component"""
    t = C['pcf_type']
    ports = {q['index']: q for q in C['ports']}
    p1, p2, p3 = _v(C.get('ep1')), _v(C.get('ep2')), _v(C.get('ep3'))
    q1, q2 = ports.get(1, {}), ports.get(2, {})
    od1 = q1.get('od') or C.get('od1') or 0.05
    od2 = q2.get('od') or C.get('od2') or od1
    wall = q1.get('wall') or q2.get('wall') or wall_hint
    M = C.get('matrix')
    X = _v(M[0:3]) if M else None; Y = _v(M[3:6]) if M else None; O = _v(M[9:12]) if M else None
    ff = (C.get('catalog_attrs') or {}).get('IJFaceToFace.FacetoFace') or (C.get('occ_attrs') or {}).get('IJFaceToFace.FacetoFace')
    items, method, notes = [], 'parametric', []

    def fl(q):
        return q.get('flange') or {}

    if t in ('PIPE', 'PIPE-FIXED'):
        if p1 is not None and p2 is not None:
            items.append(W.cyl(p1, p2, od1 / 2, wall))
            for i, q in ports.items():            # stub-in ports are just connection points, no geometry
                pass
        return items, 'exact', notes
    if t in ('ELBOW', 'BEND'):
        cp = _v(C.get('cp'))
        if p1 is not None and p2 is not None and cp is not None:
            d1 = cp - p1; d2 = p2 - cp
            T1, T2 = np.linalg.norm(d1), np.linalg.norm(d2)
            if T1 > 1e-5 and T2 > 1e-5:
                t1, t2 = d1 / T1, d2 / T2
                c = float(np.clip(t1 @ t2, -1, 1)); ang = math.acos(c)
                if ang > 1e-3 and ang < math.pi - 1e-3:
                    n1 = unit(t2 - t1 * c)
                    R = ((T1 + T2) / 2) / math.tan(ang / 2)
                    items.append(W.torus_bend(p1, t1, n1, R, ang, od1 / 2, wall))
                    if abs(T1 - T2) > 0.002:
                        notes.append('unequal tangent lengths %.4f/%.4f' % (T1, T2))
                    return items, 'parametric', notes
        if p1 is not None and p2 is not None:
            items.append(W.cyl(p1, p2, od1 / 2, wall)); notes.append('no centre point: straight chord')
            return items, 'approximate', notes
        return items, 'approximate', notes
    if t == 'TEE':
        cp = _v(C.get('cp'))
        if p1 is not None and p2 is not None:
            items.append(W.cyl(p1, p2, od1 / 2, wall))
            if cp is None:
                cp = (p1 + p2) / 2
            if p3 is not None:
                od3 = ports.get(3, {}).get('od') or C.get('od2') or od1
                items.append(W.cyl(cp, p3, od3 / 2, None))
        return items, 'parametric', notes
    if t == 'OLET':
        hp = _v(C.get('header_point'))
        if p1 is not None and p2 is not None:
            mb = (C.get('catalog_attrs') or {}).get('IJUAMajorBodyDia.MajorBodyDiameter') or od2 * 1.6
            items.append(W.frustum(p1, p2, mb / 2, od2 / 2))
        return items, 'parametric', notes
    if t in ('REDUCER-CONCENTRIC', 'REDUCER-ECCENTRIC'):
        if p1 is not None and p2 is not None:
            ax = unit(X) if X is not None else unit(p2 - p1)
            if t == 'REDUCER-ECCENTRIC':
                items.append(W.loft(p1, p2, ax, od1 / 2, od2 / 2, None)); return items, 'parametric', notes
            items.append(W.frustum(p1, p2, od1 / 2, od2 / 2, wall))
        return items, 'parametric', notes
    if t in ('FLANGE', 'FLANGE-BLIND'):
        f1 = fl(q1) or fl(q2)
        R = (f1.get('od') or od1 * 1.9) / 2
        thk = f1.get('thk') or max(0.012, od1 * 0.12)
        if t == 'FLANGE-BLIND' or p2 is None:
            if p1 is None:
                return items, 'approximate', notes
            ax = unit(X) if X is not None else None
            if ax is None:
                return items, 'approximate', notes
            if p2 is not None:
                ax = unit(p2 - p1)
            items.append(W.cyl(p1, p1 + ax * thk, R, None))
            return items, 'parametric' if f1 else 'approximate', notes
        a = p2 - p1; L = np.linalg.norm(a)
        if L < 1e-5:
            return items, 'approximate', notes
        a = a / L
        bore = max(od1 / 2 - (wall or od1 * 0.06), od1 * 0.3)
        thk = min(thk, L)
        items.append(W.cyl(p1, p1 + a * thk, R, R - bore))
        if L - thk > 1e-3:
            hub0 = min(R * 0.95, od1 / 2 + (R - od1 / 2) * 0.35)
            items.append(W.frustum(p1 + a * thk, p2, hub0, od1 / 2, (od1 / 2 - bore)))
            notes.append('hub profile approximated')
        if p3 is not None:
            items.append(W.cyl(p1 + a * thk / 2, p3, 0.008, None))
        return items, 'parametric' if f1 else 'approximate', notes
    if t == 'CAP':
        if p1 is not None:
            ax = unit(X) if X is not None else None
            if ax is not None:
                L = ff or od1 * 0.5
                items.append(W.frustum(p1, p1 + ax * L, od1 / 2, od1 / 2 * 0.55))
        return items, 'approximate', notes
    # ---- valves, instruments, specialties, misc: symbol-only bodies -> approximate
    if p1 is None and p2 is None:
        return items, 'approximate', notes
    if p1 is None or p2 is None:
        pk = p1 if p1 is not None else p2
        ax = unit(X) if X is not None else None
        if ax is None:
            return items, 'approximate', notes
        L = ff or od1 * 0.6
        items.append(W.cyl(pk, pk + ax * (L if p1 is not None else -L), od1 / 2 * 1.3, None))
        return items, 'approximate', notes
    a = p2 - p1; L = np.linalg.norm(a)
    if L < 1e-5:
        return items, 'approximate', notes
    a = a / L
    mid = _v(C.get('cp')) if C.get('cp') is not None else (p1 + p2) / 2
    mid = p1 + a * float(np.clip((mid - p1) @ a, 0.1 * L, 0.9 * L))
    f1, f2 = fl(q1), fl(q2)
    if t == 'VALVE':
        rb = max(od1, od2) / 2 * 1.25
        e1 = p1; e2 = p2
        if f1:
            th = min(f1.get('thk') or 0.02, L / 4); items.append(W.cyl(p1, p1 + a * th, f1['od'] / 2)); e1 = p1 + a * th
        if f2:
            th = min(f2.get('thk') or 0.02, L / 4); items.append(W.cyl(p2 - a * th, p2, f2['od'] / 2)); e2 = p2 - a * th
        items.append(W.frustum(e1, mid, od1 / 2 * 1.05, rb))
        items.append(W.frustum(mid, e2, rb, od2 / 2 * 1.05))
        ct = (C.get('commodity_type') or '').upper(); pc = (C.get('part_class') or '').lower()
        if Y is not None and not ('check' in pc or ct.startswith('CHK') or 'strainer' in pc):
            s = unit(Y - a * (Y @ a))
            if s is not None:
                hs = max(od1, 0.05) * 1.6 + 0.10
                items.append(W.cyl(mid, mid + s * hs, max(rb * 0.25, 0.008)))
                hw = min(max(od1 * 1.3, 0.15), 0.9) / 2
                items.append(W.cyl(mid + s * hs, mid + s * (hs + 0.03), hw, hw * 0.25))
                notes.append('stem/handwheel along symbol +Y (assumed)')
        return items, 'approximate', notes
    if t == 'INSTRUMENT':
        oa = C.get('occ_attrs') or {}
        rb = max(od1, od2) / 2 * 1.2
        items.append(W.cyl(p1, p2, rb))
        adia = oa.get('IJUAInstrumentActuator.ActuatorDiameter'); ah = oa.get('IJUAInstrumentActuator.ActuatorHeight') or oa.get('IJUAInstrumentCylinderHeight.CylHeight')
        if Y is not None and adia and ah:
            s = unit(Y - a * (Y @ a))
            if s is not None:
                items.append(W.cyl(mid, mid + s * ah, min(adia, 1.5) / 2 * 0.2))
                items.append(W.cyl(mid + s * ah, mid + s * (ah + min(adia, 1.5) * 0.35), min(adia, 1.5) / 2))
        if p3 is not None:
            items.append(W.cyl(mid, p3, od1 / 2 * 0.5))
        return items, 'approximate', notes
    rb = max(od1, od2) / 2 * (1.15 if t != 'MISC-COMPONENT' else 1.0)
    items.append(W.cyl(p1, p2, rb))
    if p3 is not None:
        items.append(W.cyl(mid, p3, od1 / 2 * 0.6))
    return items, 'approximate', notes


IFC_PIPE_CLASS = {
    'PIPE': ('IfcPipeSegment', 'RIGIDSEGMENT', 'PIPE'), 'PIPE-FIXED': ('IfcPipeSegment', 'RIGIDSEGMENT', 'PIPE'),
    'ELBOW': ('IfcPipeFitting', 'BEND', 'FITTING'), 'BEND': ('IfcPipeFitting', 'BEND', 'FITTING'),
    'TEE': ('IfcPipeFitting', 'JUNCTION', 'FITTING'), 'OLET': ('IfcPipeFitting', 'JUNCTION', 'FITTING'),
    'REDUCER-CONCENTRIC': ('IfcPipeFitting', 'TRANSITION', 'FITTING'), 'REDUCER-ECCENTRIC': ('IfcPipeFitting', 'TRANSITION', 'FITTING'),
    'FLANGE': ('IfcPipeFitting', 'CONNECTOR', 'FLANGE'), 'FLANGE-BLIND': ('IfcPipeFitting', 'OBSTRUCTION', 'FLANGE'),
    'CAP': ('IfcPipeFitting', 'EXIT', 'FITTING'), 'COUPLING': ('IfcPipeFitting', 'CONNECTOR', 'FITTING'),
    'UNION': ('IfcPipeFitting', 'CONNECTOR', 'FITTING'), 'VALVE': ('IfcValve', 'ISOLATING', 'VALVE'),
    'INSTRUMENT': ('IfcFlowInstrument', 'USERDEFINED', 'INSTRUMENT'), 'FILTER': ('IfcFilter', 'STRAINER', 'MISC'),
    'MISC-COMPONENT': ('IfcPipeFitting', 'USERDEFINED', 'MISC'),
}
VALVE_TYPE = [('CHK', 'CHECK'), ('CHECK', 'CHECK'), ('GLO', 'REGULATING'), ('GLOBE', 'REGULATING'), ('GAT', 'ISOLATING'), ('GATE', 'ISOLATING'),
              ('BAL', 'ISOLATING'), ('BTF', 'ISOLATING'), ('BUTTERFLY', 'ISOLATING'), ('PLUG', 'ISOLATING'), ('RELIEF', 'PRESSURERELIEF'),
              ('PSV', 'PRESSURERELIEF'), ('NEEDLE', 'REGULATING'), ('CONTROL', 'REGULATING'), ('STEAMTRAP', 'STEAMTRAP')]


def add_pipeline(W, J):
    """add one pipeline JSON (s3d-pipeline/1) to the writer; returns counts"""
    line = J.get('name') or J['source']['oid']
    runs = {r['oid']: r for r in J.get('runs', [])}
    cnt = collections.Counter()
    # wall hint for fittings: most common pipe wall per bore
    wall_by_bore = {}
    for C in J['components']:
        if C['pcf_type'] == 'PIPE':
            for q in C['ports']:
                if q.get('wall') and q.get('bore_mm'):
                    wall_by_bore.setdefault(q['bore_mm'], q['wall'])
    for C in J['components']:
        t = C['pcf_type']
        cls, pdt, sty = IFC_PIPE_CLASS.get(t, ('IfcPipeFitting', 'USERDEFINED', 'MISC'))
        b1 = C.get('bore1_mm')
        wall = wall_by_bore.get(b1) or (((C['ports'] or [{}])[0].get('od') or 0.05) * 0.06)
        try:
            items, method, notes = comp_geometry(W, C, wall)
        except Exception as e:
            items, method, notes = [], 'failed', ['%s: %s' % (type(e).__name__, e)]
        if not [i for i in items if i is not None]:
            cnt['no_geometry'] += 1
            continue
        if cls == 'IfcValve':
            s = ((C.get('commodity_type') or '') + ' ' + (C.get('part_class') or '')).upper()
            pdt = next((v for k, v in VALVE_TYPE if k in s), 'USERDEFINED')
        run = runs.get(C.get('run'), {})
        ps = {'S3D_Common': {'OID': C['oid'], 'OccurrenceClass': C.get('occ_class'), 'Name': C.get('name'), 'Area': J.get('area'),
                             'SystemPath': '/'.join(J.get('system_path') or []), 'GeometryMethod': method,
                             'Approximate': method != 'exact' and method != 'parametric', 'GeometryNotes': '; '.join(notes) or None},
              'S3D_Piping': {'LineNumber': line, 'PipeRun': run.get('name'), 'Spec': run.get('spec'), 'PCFType': t, 'SKEY': C.get('skey'),
                             'ItemCode': C.get('item_code'), 'IndustryCommodityCode': C.get('industry_commodity_code'), 'PartNumber': C.get('part_number'),
                             'CatalogPart': C.get('catalog_part'), 'PartClass': C.get('part_class'), 'CommodityType': C.get('commodity_type'),
                             'CommodityClass': C.get('commodity_class'), 'Description': C.get('description'), 'Material': C.get('material'),
                             'Tag': C.get('tag'), 'Size1': C.get('size1'), 'Size2': C.get('size2'), 'SizeUnit': C.get('size_unit'),
                             'Bore1_mm': b1, 'Bore2_mm': C.get('bore2_mm'), 'Schedule1': C.get('schedule1'), 'Schedule2': C.get('schedule2'),
                             'OD1_m': (C['ports'][0].get('od') if C['ports'] else None), 'Wall_m': (C['ports'][0].get('wall') if C['ports'] else None),
                             'EndPrep1': (C['ports'][0].get('end_prep') if C['ports'] else None),
                             'EndPrep2': (C['ports'][1].get('end_prep') if len(C['ports']) > 1 else None),
                             'Rating1': (C['ports'][0].get('rating') if C['ports'] else None),
                             'BendRadius_m': (C.get('bend') or {}).get('radius'), 'BendAngle_deg': (C.get('bend') or {}).get('angle_deg'),
                             'Length_m': C.get('length'), 'Weight_kg': C.get('weight'), 'Insulated': C.get('insulated')}}
        W.element(cls, C.get('name') or t, items, oid=C['oid'], style=sty, predefined=pdt,
                  object_type=t if pdt == 'USERDEFINED' else None, psets=ps, group=line)
        cnt[method] += 1
    # supports: component boxes (approximate)
    for S in J.get('supports', []):
        for k, comp in enumerate(S.get('components') or []):
            bb = comp.get('bbox')
            if not bb:
                continue
            lo, hi = np.array(bb[:3]), np.array(bb[3:])
            ext = hi - lo
            if (ext <= 0).any() or ext.max() > 20:
                continue
            item = W.box((lo + hi) / 2, (1, 0, 0), (0, 1, 0), (0, 0, 1), ext[0], ext[1], ext[2])
            W.element('IfcDiscreteAccessory', comp.get('bom') or comp.get('role') or S.get('name'), [item], oid=comp['oid'], style='SUPPORT',
                      predefined='USERDEFINED', object_type='PIPE SUPPORT COMPONENT',
                      psets={'S3D_Common': {'OID': comp['oid'], 'Area': J.get('area'), 'GeometryMethod': 'approximate',
                                            'Approximate': True, 'GeometryNotes': 'axis-aligned bounding box of the hanger part'},
                             'S3D_Support': {'Support': S.get('name'), 'SupportOID': S['oid'], 'BOM': S.get('bom'), 'CatalogAssembly': S.get('catalog_assembly'),
                                             'Role': comp.get('role'), 'ComponentBOM': comp.get('bom'), 'CatalogPart': comp.get('catalog_part'),
                                             'LineNumber': line}},
                      group=line)
            cnt['support_parts'] += 1
    return cnt


# ============================================================== structure
def section_profile(W, sec, mirror=False):
    """-> (profile, width, depth, method)"""
    if not sec:
        return None, None, None, 'none'
    d = sec.get('dims') or {}
    typ = (sec.get('type') or '').upper()
    D = d.get('d') or d.get('Depth'); B = d.get('bf') or d.get('Width')
    tf = d.get('tf'); tw = d.get('tw')
    tn = d.get('tdes') or d.get('tnom') or d.get('t')
    f = W.f
    key = ('sec', sec.get('moniker'), bool(mirror))

    def mk():
        if typ in ('W', 'S', 'HP', 'M') and D and B and tf and tw:
            return f.createIfcIShapeProfileDef('AREA', sec['name'], W.p2, B, D, tw, tf, None, None, None), 'exact'
        if typ in ('C', 'MC') and D and B and tf and tw:
            pos = W.p2 if not mirror else f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0., 0.)), f.createIfcDirection((-1., 0.)))
            return f.createIfcUShapeProfileDef('AREA', sec['name'], pos, D, B, tw, tf, None, None, None), 'exact'
        if typ == 'L' and D and B:
            t = tf or tw or tn or min(D, B) * 0.1
            pos = W.p2 if not mirror else f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0., 0.)), f.createIfcDirection((-1., 0.)))
            return f.createIfcLShapeProfileDef('AREA', sec['name'], pos, D, B, t, None, None, None), 'exact'
        if typ in ('WT', 'ST', 'MT') and D and B and tf and tw:
            return f.createIfcTShapeProfileDef('AREA', sec['name'], W.p2, D, B, tw, tf, None, None, None, None, None), 'exact'
        if typ == 'HSSR' and D and B and tn:
            return f.createIfcRectangleHollowProfileDef('AREA', sec['name'], W.p2, B, D, tn, None, None), 'exact'
        if typ in ('HSSC', 'PIPE') and D:
            if tn and tn < D / 2:
                return f.createIfcCircleHollowProfileDef('AREA', sec['name'], W.p2, D / 2, tn), 'exact'
            return f.createIfcCircleProfileDef('AREA', sec['name'], W.p2, D / 2), 'exact'
        if typ == 'CS' and D:
            return f.createIfcCircleProfileDef('AREA', sec['name'], W.p2, D / 2), 'exact'
        if typ == 'RS' and D and B:
            return f.createIfcRectangleProfileDef('AREA', sec['name'], W.p2, B, D), 'exact'
        if typ == '2L' and D and B:
            # two angles back to back (legs down), gap from catalog spacing if present
            t = tf or tw or tn or min(D, B) * 0.1
            half = B / 2
            g = d.get('LongLegSpacing') or d.get('ShortLegSpacing') or d.get('bb') or 0.0
            pts = [(-half, D / 2), (-g / 2, D / 2), (-g / 2, -D / 2), (-g / 2 - t, -D / 2), (-g / 2 - t, D / 2 - t), (-half, D / 2 - t)]
            pts2 = [(-x, y) for x, y in pts][::-1]
            c1 = f.createIfcArbitraryClosedProfileDef('AREA', sec['name'], f.createIfcPolyline([f.createIfcCartesianPoint(p) for p in pts + [pts[0]]]))
            c2 = f.createIfcArbitraryClosedProfileDef('AREA', sec['name'], f.createIfcPolyline([f.createIfcCartesianPoint(p) for p in pts2 + [pts2[0]]]))
            return f.createIfcCompositeProfileDef('AREA', sec['name'], [c1, c2], None), 'approximate'
        if D and B:
            return f.createIfcRectangleProfileDef('AREA', sec['name'], W.p2, B, D), 'approximate'
        return None, 'none'
    if key not in W._prof:
        W._prof[key] = mk()
    prof, method = W._prof[key]
    return prof, B, D, method


def cardinal_offset(cp, B, D):
    """S3D cardinal point -> (x, y) of that point in profile coordinates (profile bbox centre at origin)."""
    if not cp or cp in (5, 10, 11) or cp > 15:
        return 0.0, 0.0
    if cp <= 9:
        col = (cp - 1) % 3; row = (cp - 1) // 3
        return (-B / 2, 0.0, B / 2)[col], (-D / 2, 0.0, D / 2)[row]
    return 0.0, 0.0


def add_member(W, m):
    import memberfit
    if not m.get('start') or not m.get('end'):
        return None
    fr = memberfit.frame(m)
    if fr is None:
        return None
    s, a, L, u, y = fr
    prof, B, D, method = section_profile(W, m.get('section'), False)
    if prof is None:
        return None
    ext = m.get('extent') or memberfit.fit_extent(m)
    enote = None
    if ext and ext.get('ok'):
        t0, t1 = ext['t0'], ext['t1']
        if abs(t0) > 1e-4 or abs(t1 - L) > 1e-4:
            enote = 'physical extent from bbox+cutLength fit (t0=%.4f, t1-L=%.4f)' % (t0, t1 - L)
    else:
        t0, t1 = 0.0, L
        if m.get('cut_length') and abs(m['cut_length'] - L) > 0.004:
            enote = 'cutLength %.4f differs from axis %.4f; axis used' % (m['cut_length'], L)
    L = t1 - t0
    if L < 1e-4:
        return None
    ag = m.get('_acis')
    if ag and ag.get('complete') and len(ag['f']) >= 4:
        item = W.brep(np.asarray(ag['v']), ag['f'], True)
        if item is not None:
            return _member_element(W, m, item, W.lp0(), 'exact', B, D,
                                   'ACIS solid from GEOTOPSolidBody (includes end cuts/copes); ' + ('; '.join(ag.get('flags') or []) or 'all faces exact'),
                                   rep_type='Brep')
    # S3D section frame (verified against CORESpatialIndex bboxes): width axis u = a x up, flipped when mirror=1.
    # IFC frame must be right-handed with profile x = u, profile y = up: extrude from the end (Z=-a) when
    # mirror=0, from the start (Z=+a) when mirror=1.
    mir = bool(m.get('mirror'))
    cx, cy = cardinal_offset(m.get('cardinal_point'), B or 0, D or 0)
    ps0, pe0 = s + a * t0, s + a * t1
    org, z = (ps0, a) if mir else (pe0, -a)
    base = org - u * cx - y * cy
    pl = W.lp(base, z, u)
    onote = None
    item = W.extrude(prof, L)
    return _member_element(W, m, item, pl, method, B, D, '; '.join(x for x in ('end cuts/copes not included (no complete ACIS solid)', onote, enote) if x))


def _member_element(W, m, item, pl, method, B, D, notes, rep_type='SweptSolid'):
    cat = m.get('category') or 'Member'
    if cat == 'Column':
        cls, pdt, sty = 'IfcColumn', 'COLUMN', 'Column'
    elif cat == 'Beam':
        cls, pdt, sty = 'IfcBeam', 'BEAM', 'Beam'
    elif cat == 'Brace':
        cls, pdt, sty = 'IfcMember', 'BRACE', 'Brace'
    elif cat and 'Handrail' in cat:
        cls, pdt, sty = 'IfcMember', ('POST' if 'post' in (m.get('type') or '').lower() else 'MEMBER'), 'Handrail'
    else:
        cls, pdt, sty = 'IfcMember', 'MEMBER', 'MEMBER'
    sec = m.get('section') or {}
    ps = {'S3D_Common': {'OID': m['oid'], 'Name': m.get('name'), 'Area': m.get('area'), 'SystemPath': '/'.join(m.get('system_path') or []),
                         'GeometryMethod': method, 'Approximate': method not in ('exact',),
                         'GeometryNotes': notes},
          'S3D_Member': {'Category': cat, 'MemberType': m.get('type'), 'Section': sec.get('moniker'), 'SectionType': sec.get('type'),
                         'SectionStandard': sec.get('standard'), 'CardinalPoint': m.get('cardinal_point'), 'Roll_deg': m.get('roll_deg'),
                         'Mirror': m.get('mirror'), 'CutLength_m': m.get('cut_length'), 'Weight_kg': m.get('weight'), 'Material': m.get('material'),
                         'Depth_m': D, 'Width_m': B}}
    grp = (m.get('system_path') or ['?'])[-1] or 'structure'
    return W.element(cls, m.get('name') or sec.get('name'), [item], placement=pl, oid=m['oid'], style=sty, predefined=pdt,
                     psets=ps, group=grp, rep_type=rep_type)


def add_acis_object(W, r):
    """curved members and slabs: geometry only exists as the ACIS solid"""
    ag = r.get('_acis')
    if not ag or not ag['f']:
        return None
    complete = bool(ag.get('complete'))
    item = W.brep(np.asarray(ag['v']), ag['f'], complete)
    if item is None:
        return None
    fl = '; '.join(ag.get('flags') or [])
    notes = 'ACIS solid from GEOTOPSolidBody' + ('' if complete else ' (open shell: some curved faces could not be tessellated)') + ('; ' + fl if fl else '')
    method = 'exact' if complete and not any(x.endswith('_approx') or x.startswith('chorded') for x in ag.get('flags') or []) else 'approximate'
    common = {'OID': r['oid'], 'Name': r.get('name'), 'Area': r.get('area'), 'SystemPath': '/'.join(r.get('system_path') or []),
              'GeometryMethod': method, 'Approximate': method != 'exact', 'GeometryNotes': notes}
    if r['kind'] == 'slab':
        ps = {'S3D_Common': common, 'S3D_Slab': {'Weight_kg': r.get('weight'), 'Volume_m3': r.get('volume'), 'NetVolume_m3': r.get('net_volume'),
                                                  'Area_m2': r.get('area_m2'), 'TopOfConcrete_m': r.get('toc'), 'BottomOfConcrete_m': r.get('boc'),
                                                  'Openings': r.get('openings')}}
        return W.element('IfcSlab', r.get('name') or 'Slab', [item], oid=r['oid'], style='MEMBER', predefined='FLOOR', psets=ps,
                         group=(r.get('system_path') or ['slabs'])[-1] or 'slabs', rep_type='Brep' if complete else 'SurfaceModel')
    sec = r.get('section') or {}
    ps = {'S3D_Common': common, 'S3D_Member': {'Category': r.get('category'), 'MemberType': r.get('type'), 'Section': sec.get('moniker'),
                                               'SectionType': sec.get('type'), 'CardinalPoint': r.get('cardinal_point'), 'Curved': True,
                                               'CutLength_m': r.get('cut_length'), 'Weight_kg': r.get('weight'), 'Material': r.get('material')}}
    return W.element('IfcMember', r.get('name') or sec.get('name') or 'Curved member', [item], oid=r['oid'], style='Brace', predefined='MEMBER',
                     psets=ps, group=(r.get('system_path') or ['structure'])[-1] or 'structure', rep_type='Brep' if complete else 'SurfaceModel')


# ============================================================== equipment
EQUIP_CLASS = [('pump', 'IfcPump'), ('compressor', 'IfcCompressor'), ('exchanger', 'IfcHeatExchanger'), ('cooler', 'IfcHeatExchanger'),
               ('heater', 'IfcHeatExchanger'), ('tank', 'IfcTank'), ('vessel', 'IfcTank'), ('drum', 'IfcTank'), ('column', 'IfcTank'),
               ('tower', 'IfcTank'), ('fan', 'IfcFan'), ('blower', 'IfcFan'), ('filter', 'IfcFilter'), ('motor', 'IfcElectricMotor')]


def shape_items(W, s):
    """S3D equipment shape symbol -> IFC items (parametric). Frame: matrix rows = local X, Y, Z images; origin."""
    M = s.get('matrix'); p = s.get('params') or {}
    if not M:
        return [], 'none'
    X, Y, Z, O = _v(M[0:3]), _v(M[3:6]), _v(M[6:9]), _v(M[9:12])
    typ = (s.get('shape_type') or '').split(' ')[0]
    vals = {k.split('.')[-1]: v for k, v in p.items() if isinstance(v, (int, float))}
    A, Bv, Cv, Dv, Ev = (vals.get(k) for k in ('A', 'B', 'C', 'D', 'E'))
    it = []
    cal = SHAPE_CAL.get(typ)
    if cal:
        return cal(W, X, Y, Z, O, A, Bv, Cv, Dv, Ev), 'parametric'
    return [], 'unsupported'


def _box_c(W, X, Y, Z, O, dx, dy, dz):
    return [W.box(O, X, Y, Z, dx, dy, dz)] if dx and dy and dz else []


# Conventions calibrated against CORESpatialIndex bboxes of world-aligned shape samples (local frame = CORESymbol
# rows X,Y,Z + origin): every symbol extends from the origin along local +X.
def _rect(W, X, Y, Z, O, A, B, C, D, E):          # A along X (0..A), B along Y, C along Z (centred)
    return [W.box(O + X * A / 2, Y, Z, X, B, C, A)] if (A and B and C) else []


def _cyl(W, X, Y, Z, O, A, B, C, D, E):           # A = length along X, B = diameter
    return [W.cyl(O, O + X * A, B / 2)] if (A and B) else []


def _cone(W, X, Y, Z, O, A, B, C, D, E):          # A = length along X, B = diameter at origin, C = diameter at end
    return [W.frustum(O, O + X * A, B / 2, (C or 0) / 2)] if (A and B) else []


def _head(W, X, Y, Z, O, A, B, C, D, E):          # A = diameter, B = height along X (base at origin)
    if not (A and B):
        return []
    r, h = A / 2, B
    pts = [(r * math.cos(t), h * math.sin(t)) for t in np.linspace(0, math.pi / 2, 10)]
    return [W.revolve_rh(O, X, pts)]


def _tprism(W, X, Y, Z, O, A, B, C, D, E, ecc=False):   # base A(z) x B(y) at x=0, top C(z) x D(y) at x=E
    if not (A and B and E):
        return []
    C = C or A; D = D or B
    y0, y1 = (-B / 2, -B / 2 + D) if ecc else (-D / 2, D / 2)
    q = [(0, -B / 2, -A / 2), (0, B / 2, -A / 2), (0, B / 2, A / 2), (0, -B / 2, A / 2),
         (E, y0, -C / 2), (E, y1, -C / 2), (E, y1, C / 2), (E, y0, C / 2)]
    V = [O + X * x + Y * y + Z * z for x, y, z in q]
    T = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [W.mesh(V, T)]


def _ecc_tprism(W, X, Y, Z, O, A, B, C, D, E):
    return _tprism(W, X, Y, Z, O, A, B, C, D, E, ecc=True)


def _octo(W, X, Y, Z, O, A, B, C, D, E):          # A = length along X, B (y) x C (z) across flats, D = side length
    if not (A and B and C):
        return []
    D = D if D and D < min(B, C) else min(B, C) / (1 + 2 ** 0.5)
    cy, cz = (B - D) / 2, (C - D) / 2
    oy, oz = B / 2, C / 2
    pts = [(-oy + cy, -oz), (oy - cy, -oz), (oy, -oz + cz), (oy, oz - cz), (oy - cy, oz), (-oy + cy, oz), (-oy, oz - cz), (-oy, -oz + cz)]
    f = W.f
    prof = f.createIfcArbitraryClosedProfileDef('AREA', None, f.createIfcPolyline([f.createIfcCartesianPoint((float(a), float(b))) for a, b in pts + [pts[0]]]))
    return [W.extrude(prof, A, W.ax(O, X, Y))]


def _ctorus(W, X, Y, Z, O, A, B, C, D, E):        # tube dia A, bend radius B, angle C; starts at origin along +X, bends toward -Y
    if not (A and B and C):
        return []
    return [W.torus_bend(O, X, -Y, B, C, A / 2)]


def _rtorus(W, X, Y, Z, O, A, B, C, D, E):        # radial width A, height B (Z), centreline radius C, angle D
    if not (A and B and C and D):
        return []
    f = W.f
    prof = W.prof(('r', round(A, 5), round(B, 5)), lambda: f.createIfcRectangleProfileDef('AREA', None, W.p2, float(A), float(B)))
    pos = W.ax(O, X, -Y)
    axis = f.createIfcAxis1Placement(f.createIfcCartesianPoint((float(C), 0., 0.)), W.D((0, 1, 0)))
    return [f.createIfcRevolvedAreaSolid(prof, pos, axis, float(D))]


SHAPE_CAL = {'RectangularSolid': _rect, 'RtCircularCylinder': _cyl, 'RtCircularCone': _cone, 'SemiEllipticalHead': _head,
             'TruncatedRectangularPrism': _tprism, 'EccentricRectangularPrism': _ecc_tprism, 'OctogonalSolid': _octo,
             'EccentricCone': _cone, 'CircularTori': _ctorus, 'RectangularTorus': _rtorus}


def oriented_envelope(W, s):
    """unsupported shape: box of its bbox, oriented in the shape frame when the frame is world-aligned"""
    M, bb = s.get('matrix'), s.get('bbox')
    if not bb or any(v is None for v in bb):
        return None
    lo, hi = np.array(bb[:3]), np.array(bb[3:]); ext = hi - lo
    if (ext <= 0).any() or ext.max() > 200:
        return None
    return W.box((lo + hi) / 2, (1, 0, 0), (0, 1, 0), (0, 0, 1), *ext)


def add_equipment(W, E):
    cnt = collections.Counter()
    items = []; methods = collections.Counter(); unsup = collections.Counter()
    for s in E.get('shapes') or []:
        try:
            its, m = shape_items(W, s)
        except Exception as ex:
            its, m = [], 'failed'
        its = [i for i in its if i is not None]
        if its:
            items += its; methods[m] += 1
        else:
            unsup[s.get('shape_type')] += 1
            env = oriented_envelope(W, s)
            if env is not None:
                items.append(env); methods['bbox'] += 1
    method = 'parametric' if items and not methods['bbox'] else ('approximate' if items else 'approximate')
    notes = []
    if not items:
        bb = E.get('bbox')
        if bb and all(v is not None for v in bb):
            lo, hi = np.array(bb[:3]), np.array(bb[3:]); ext = hi - lo
            if (ext > 0).all() and ext.max() < 300:
                items.append(W.box((lo + hi) / 2, (1, 0, 0), (0, 1, 0), (0, 0, 1), *ext))
                notes.append('symbol-only equipment: bounding box')
                method = 'approximate'
    if unsup:
        notes.append('unsupported shapes as bbox: ' + ', '.join('%s x%d' % kv for kv in unsup.items()))
    s = ((E.get('catalog_class') or '') + ' ' + (E.get('name') or '') + ' ' + (E.get('description') or '')).lower()
    cls = next((c for k, c in EQUIP_CLASS if k in s), 'IfcBuildingElementProxy')
    ps = {'S3D_Common': {'OID': E['oid'], 'Name': E.get('name'), 'Area': E.get('area'), 'SystemPath': '/'.join(E.get('system_path') or []),
                         'GeometryMethod': method, 'Approximate': method != 'parametric', 'GeometryNotes': '; '.join(notes) or None},
          'S3D_Equipment': {'CatalogClass': E.get('catalog_class'), 'Description': E.get('description'), 'DryWeight_kg': E.get('dry_weight'),
                            'WetWeight_kg': E.get('wet_weight'), 'Shapes': len(E.get('shapes') or []), 'Nozzles': len(E.get('nozzles') or [])}}
    if items:
        W.element(cls, E.get('name'), items, oid=E['oid'], style='EQUIPMENT' if method == 'parametric' else 'EQUIP_BBOX',
                  predefined='USERDEFINED' if cls != 'IfcBuildingElementProxy' else 'ELEMENT',
                  object_type=E.get('catalog_class') if cls != 'IfcBuildingElementProxy' else None, psets=ps,
                  group=E.get('name') or E['oid'])
        cnt['equipment_' + method] += 1
    for z in E.get('nozzles') or []:
        p, d = _v(z.get('xyz')), _v(z.get('dir'))
        if p is None or d is None or np.linalg.norm(d) < 0.5:
            continue
        d = unit(d)
        od = z.get('od') or 0.05; L = z.get('length') or od * 2
        its = [W.cyl(p - d * L, p, od / 2, z.get('wall'))]
        if z.get('flange_od') and z.get('flange_thk'):
            its.append(W.cyl(p - d * z['flange_thk'], p, z['flange_od'] / 2, (z['flange_od'] - od) / 2 + (z.get('wall') or od * 0.06)))
        W.element('IfcPipeFitting', '%s %s' % (E.get('name') or '', z.get('label') or ''), its, oid=z['oid'], style='NOZZLE',
                  predefined='USERDEFINED', object_type='NOZZLE',
                  psets={'S3D_Common': {'OID': z['oid'], 'Area': E.get('area'), 'GeometryMethod': 'exact', 'Approximate': False},
                         'S3D_Nozzle': {'Equipment': E.get('name'), 'EquipmentOID': E['oid'], 'Label': z.get('label'), 'NPD': z.get('npd'),
                                        'NPDUnit': z.get('npd_unit'), 'Bore_mm': z.get('bore_mm'), 'EndPrep': z.get('end_prep'),
                                        'Rating': z.get('rating'), 'OD_m': od, 'FlangeOD_m': z.get('flange_od'), 'FlangeThk_m': z.get('flange_thk'),
                                        'Length_m': z.get('length')}},
                  group=E.get('name') or E['oid'])
        cnt['nozzles'] += 1
    return cnt
