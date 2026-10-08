"""Prefetch global (catalog + schema + system tree) data into /data/s3d/work/meta/*.pkl.

All reads; runs in ~minutes. Every later stage only does MDB seeks per batch and maps
catalog data in Python from these tables.
"""
import sys, time, collections
from common import *

T = time.time()


def q(conn, sql, **kw):
    t = time.time()
    cols, rows = query(conn, sql % dict(R, MDB=MDB, CDB=CDB, SCH=SCH, **kw))
    log('  %d rows %.1fs  %s' % (len(rows), time.time() - t, sql.strip().split('\n')[0][:90]))
    return cols, rows


def main(only=None):
    c = connect(MDB)

    def want(n):
        return only is None or n in only

    # ---- (iid, dispid) -> (interface, property, codelist) for generic attributes
    if want('attrmap'):
        cols, rows = q(c, """
SELECT ii.IID, ai.InterfaceName, ai.DispatchID, ai.Name, ai.CodeListTableOID, ai.UnitsType, ai.PrimaryUnits
FROM [%(SCH)s].dbo.AttributeInfoView ai
JOIN [%(SCH)s].dbo.InterfaceInfoView ii ON ii.Name = ai.InterfaceName""")
        cl_tab = {}
        cols2, rows2 = q(c, "SELECT DISTINCT TableID, TableName FROM [%(SCH)s].dbo.CodelistValueView")
        for tid, tn in rows2:
            cl_tab[str(tid).upper()] = tn
        cols3, rows3 = q(c, """SELECT DISTINCT CAST(ai.CodeListTableOID AS char(36)) o, n.Name FROM [%(SCH)s].dbo.AttributeInfoView ai
                              JOIN [%(SCH)s].dbo.IJNamedObject n ON n.oid = ai.CodeListTableOID""")
        cl_named = {str(o).upper(): nm for o, nm in rows3}
        amap = {}
        for iid, iface, disp, name, cltab, ut, pu in rows:
            cl = None
            if cltab is not None:
                k = str(cltab).upper()
                cl = cl_named.get(k) or cl_tab.get(k)
            amap[(str(iid).upper(), int(disp))] = (iface, name, cl)
        save_pkl('attrmap', amap)
        log('attrmap %d entries, %d with codelist' % (len(amap), sum(1 for v in amap.values() if v[2])))

    # ---- codelists
    if want('codelists'):
        cols, rows = q(c, "SELECT TableName, ValueID, ShortStringValue, LongStringValue FROM [%(SCH)s].dbo.CodelistValueView")
        cl = collections.defaultdict(dict)
        for tn, vid, s, l in rows:
            cl[tn][int(vid)] = (s, l)
        save_pkl('codelists', dict(cl))

    # ---- model proxies owned by a CORESite -> moniker -> catalog oid
    if want('proxies'):
        cols, rows = q(c, """
SELECT CAST(r.oidTarget AS char(36)) proxy, r.RelationName moniker, CAST(cn.ObjectOid AS char(36)) catoid
FROM dbo.CORESite s
JOIN dbo.CORERelationOrigin r ON r.oid = s.oid AND r.RelationType = '%(ProxyOwner)s'
LEFT JOIN [%(CDB)s].dbo.CORENamedObjects cn ON cn.ObjectName = r.RelationName""")
        px = {}
        for p, m, co in rows:
            if co is None and m and m.startswith('{') and m.endswith('}') and GUID_RE.match(m[1:-1]):
                co = m[1:-1].upper()
            px[p.upper()] = (m, co.upper() if co else None)
        save_pkl('proxies', px)
        log('proxies %d, resolved %d' % (len(px), sum(1 for v in px.values() if v[1])))

    # ---- catalog pipe components (CDB) + part class
    pcols = ("k.PartNumber, k.PartDescription, k.IndustryCommodityCode, k.FirstSizeSchedule, k.SecondSizeSchedule, k.PrimarySize, "
             "k.PriSizeNPDUnits, k.SecondarySize, k.SecSizeNPDUnits, k.MaterialGrade, k.MaterialCategory, k.CommodityType, "
             "k.CommoditySubClass, k.CommodityClass, k.BendRadius, k.BendRadiusMultiplier, k.GeometryType, k.DryWeight, "
             "k.FirstSizeOutsideDiameter, k.SecondSizeOutsideDiameter, k.GeometricIndustryStandard, k.ValvePortOption, k.ValveFlowPattern")
    if want('catparts'):
        cols, rows = q(c, """
SELECT CAST(k.oid AS char(36)) oid, %(pc)s, pc.Name PartClass, pc.SymbolDefinitionName
FROM [%(CDB)s].dbo.REFDATPipeComponent k
OUTER APPLY (SELECT TOP 1 p.Name, p.SymbolDefinitionName FROM [%(CDB)s].dbo.CORERelationOrigin r JOIN [%(CDB)s].dbo.REFDATPartClass p ON p.oid = r.oid
             WHERE r.oidTarget = k.oid AND r.RelationType = '%(PartClassParts)s') pc""", pc=pcols)
        cp = {r[0].upper(): dict(zip(cols[1:], r[1:])) for r in rows}
        # model-resident parts (instruments / specialties)
        cols, rows = q(c, """
SELECT CAST(k.oid AS char(36)) oid, %(pc)s, pcm.Name PartClass
FROM dbo.REFDATPipeComponent k
OUTER APPLY (SELECT TOP 1 COALESCE(pc.Name, px.RelationName) AS Name FROM dbo.CORERelationOrigin r
             LEFT JOIN dbo.REFDATPartClass pc ON pc.oid = r.oid
             LEFT JOIN dbo.CORERelationOrigin px ON px.oidTarget = r.oid AND px.RelationType = '%(ProxyOwner)s'
             WHERE r.oidTarget = k.oid AND r.RelationType = '%(PartClassParts)s') pcm""", pc=pcols)
        mp = {r[0].upper(): dict(zip(cols[1:], r[1:]), _mdb=True) for r in rows}
        # tag data of model-resident parts
        cols, rows = q(c, """
SELECT CAST(k.oid AS char(36)) oid, COALESCE(i.TagNumber, s.TagNumber) TagNumber,
       COALESCE(i.ContractorCommodityCode, s.ContractorCommodityCode) TagCommodityCode,
       COALESCE(i.ShortMaterialDescription, s.ShortMaterialDescription) TagDescription,
       CASE WHEN i.oid IS NOT NULL THEN 'INSTRUMENT' WHEN s.oid IS NOT NULL THEN 'SPECIALTY' END TagKind
FROM dbo.REFDATPipeComponent k
JOIN dbo.CORERelationOrigin r ON r.oid = k.oid AND r.RelationType = '%(MatCtlForComp)s'
LEFT JOIN dbo.REFDATInstrumentClass i ON i.oid = r.oidTarget
LEFT JOIN dbo.REFDATPipingSpecialtyClass s ON s.oid = r.oidTarget""")
        for r in rows:
            d = mp.get(r[0].upper())
            if d is not None:
                d.update(dict(zip(cols[1:], r[1:])))
        cp.update(mp)
        save_pkl('catparts', cp)
        log('catparts %d (mdb %d)' % (len(cp), len(mp)))

    if want('catports'):
        ports = collections.defaultdict(list)
        for db in (CDB, MDB):
            cols, rows = q(c, """
SELECT CAST(r.oid AS char(36)) part, pp.PortIndex, pp.Npd, pp.NpdUnitType, pp.EndPrep, pp.EndStandard, pp.PressureRating,
       pp.ScheduleThickness, pp.TerminationClass, pp.FlowDirection
FROM [%(db)s].dbo.CORERelationOrigin r JOIN [%(db)s].dbo.REFDATPipePort pp ON pp.oid = r.oidTarget
WHERE r.RelationType = '%(PartNozzles)s'""", db=db)
            for r in rows:
                ports[r[0].upper()].append(dict(zip(cols[1:], r[1:])))
        save_pkl('catports', dict(ports))

    if want('catattrs'):
        # generic double/long/string attributes of catalog + model-resident pipe parts and valve operators
        amap = load_pkl('attrmap')
        att = collections.defaultdict(dict)
        miss = collections.Counter()
        for db in (CDB, MDB):
            for tab in ('COREDoubleAttribute', 'CORELongAttribute', 'COREBstrAttribute'):
                cols, rows = q(c, """
SELECT CAST(a.oid AS char(36)) oid, CAST(a.iid AS char(36)) iid, a.dispid, a.value
FROM [%(db)s].dbo.%(tab)s a JOIN [%(db)s].dbo.REFDATPipeComponent k ON k.oid = a.oid""", db=db, tab=tab)
                for o, iid, disp, v in rows:
                    nm = amap.get((iid.upper(), int(disp)))
                    if nm is None:
                        miss[(iid, disp)] += 1
                        key = '%s:%s' % (iid[:8], disp)
                    else:
                        key = '%s.%s' % (nm[0], nm[1])
                    att[o.upper()][key] = v if not isinstance(v, float) else round(v, 7)
        save_pkl('catattrs', dict(att))
        log('catattrs: %d parts, %d unmapped (iid,dispid)' % (len(att), len(miss)))

    if want('matctl'):
        cols, rows = q(c, """
SELECT CAST(m.oid AS char(36)) oid, m.ContractorCommodityCode, m.IndustryCommodityCode, m.ClientCommodityCode, m.ShortMaterialDescription,
       m.LongMaterialDescription, m.ValveOperatorPartNumber, m.ValveOperatorType, m.GasketRequirements, m.BoltRequirements,
       m.FabricationCategory, m.FabricationClass, m.ReportingRequirements, m.SupplyResponsibility, m.Vendor, m.Manufacturer
FROM [%(CDB)s].dbo.REFDATCommodityMatlCtrlData m""")
        save_pkl('matctl', {r[0].upper(): dict(zip(cols[1:], r[1:])) for r in rows})

    if want('skey'):
        cols, rows = q(c, "SELECT CodeList, SKEY, PartClassName, PCFComponentID, MapType FROM [%(CDB)s].dbo.REFDATPipeMfgMapSymbol")
        save_pkl('skey', [dict(zip(cols, r)) for r in rows])

    if want('enddata'):
        cols, rows = q(c, "SELECT * FROM [%(CDB)s].dbo.REFDATBoltedEndData")
        bolted = [dict(zip(cols, r)) for r in rows]
        cols, rows = q(c, "SELECT * FROM [%(CDB)s].dbo.REFDATFemaleEndData")
        female = [dict(zip(cols, r)) for r in rows]
        for L in (bolted, female):
            for d in L:
                d.pop('oid', None)
        save_pkl('enddata', dict(bolted=bolted, female=female))

    if want('valveops'):
        cols, rows = q(c, "SELECT CAST(o.oid AS char(36)) oid, o.* FROM [%(CDB)s].dbo.REFDATValveOperator o")
        save_pkl('valveops', [dict(zip(cols, r)) for r in rows])

    if want('sections'):
        amap = load_pkl('attrmap')
        cols, rows = q(c, """
SELECT cno.ObjectName, CAST(a.iid AS char(36)) iid, a.dispid, a.value
FROM [%(CDB)s].dbo.CORENamedObjects cno
JOIN [%(CDB)s].dbo.COREBaseClass b ON b.oid = cno.ObjectOid AND b.ClassId = 60035
JOIN [%(CDB)s].dbo.COREDoubleAttribute a ON a.oid = cno.ObjectOid""")
        sec = collections.defaultdict(dict)
        for nm, iid, disp, v in rows:
            m = amap.get((iid.upper(), int(disp)))
            key = m[1] if m else '%s:%s' % (iid[:8], disp)
            if m and m[0] in ('IStructCrossSectionDesignProperties',):
                key = 'design.' + key
            sec[nm][key] = v
        save_pkl('sections', dict(sec))
        log('sections %d' % len(sec))

    if want('systree'):
        cols, rows = q(c, """
SELECT CAST(r.oid AS char(36)) parent, CAST(r.oidTarget AS char(36)) child, bc.ClassId ccls, n.strName cname
FROM dbo.CORERelationOrigin r WITH (INDEX(CORERelationOriginTypeIndex))
JOIN dbo.COREBaseClass bc ON bc.oid = r.oidTarget
LEFT JOIN dbo.CORENamedItem n ON n.oid = r.oidTarget
WHERE r.RelationType = '%(SystemHierarchy)s' AND LEFT(CAST(r.oidTarget AS char(36)),8) <> '0001388D'""")
        par, name, cls = {}, {}, {}
        for p, ch, cc, cn in rows:
            p, ch = p.upper(), ch.upper()
            par[ch] = p; name[ch] = (cn or '').strip(); cls[ch] = cc
        roots = set(par.values()) - set(par)
        cols, rows = q(c, "SELECT CAST(b.oid AS char(36)), b.ClassId, n.strName FROM dbo.COREBaseClass b LEFT JOIN dbo.CORENamedItem n ON n.oid=b.oid WHERE b.oid IN (%s)" % guid_list(roots))
        for o, cc, nm in rows:
            name[o.upper()] = (nm or '').strip(); cls[o.upper()] = cc
        save_pkl('systree', dict(par=par, name=name, cls=cls))
        log('systree %d nodes' % len(par))

    if want('pipelines'):
        cols, rows = q(c, """
SELECT CAST(p.oid AS char(36)) oid, n.strName, p.Description, p.SequenceNumber, p.FluidSystem, p.FluidCode, b.persistentFlag
FROM dbo.SHPCONPipelineSystem p LEFT JOIN dbo.CORENamedItem n ON n.oid = p.oid LEFT JOIN dbo.COREBaseClass b ON b.oid = p.oid""")
        save_pkl('pipelines', [dict(zip(cols, r)) for r in rows])
        log('pipelines %d' % len(rows))
    log('meta done %.0fs' % (time.time() - T))


if __name__ == '__main__':
    main(set(sys.argv[1:]) or None)
