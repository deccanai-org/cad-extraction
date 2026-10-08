"""Batch SQL for piping: one round trip per batch of pipelines, MDB seeks only.
Result sets are consumed by name in ex_piping.py (order matters)."""
from common import R

BATCH_SQL = """
SET NOCOUNT ON;
CREATE TABLE #pl (oid uniqueidentifier PRIMARY KEY);
INSERT INTO #pl VALUES %(PL)s;

SELECT r1.oid AS pl, r1.oidTarget AS run INTO #runs
FROM #pl p JOIN dbo.CORERelationOrigin r1 ON r1.oid = p.oid AND r1.RelationType = '%(SystemHierarchy)s'
WHERE LEFT(CAST(r1.oidTarget AS char(36)), 8) = '0001388D';
CREATE CLUSTERED INDEX ix_runs ON #runs(run);

SELECT r.pl, r.run, r2.oidTarget AS part, b.ClassId AS cls INTO #parts
FROM #runs r JOIN dbo.CORERelationOrigin r2 ON r2.oid = r.run AND r2.RelationType = '%(OwnsParts)s'
JOIN dbo.COREBaseClass b ON b.oid = r2.oidTarget;
CREATE CLUSTERED INDEX ix_parts ON #parts(part);

/* RS pipelines: generic attributes */
SELECT 'plattr' AS rs, CAST(p.oid AS char(36)) oid, CAST(a.iid AS char(36)) iid, a.dispid, a.d, a.l, a.s
FROM #pl p CROSS APPLY (
  SELECT iid, dispid, value d, CAST(NULL AS int) l, CAST(NULL AS nvarchar(400)) s FROM dbo.COREDoubleAttribute WHERE oid = p.oid
  UNION ALL SELECT iid, dispid, NULL, value, NULL FROM dbo.CORELongAttribute WHERE oid = p.oid
  UNION ALL SELECT iid, dispid, NULL, NULL, CAST(value AS nvarchar(400)) FROM dbo.COREBstrAttribute WHERE oid = p.oid
  UNION ALL SELECT iid, dispid, NULL, CAST(value AS int), NULL FROM dbo.COREBoolAttribute WHERE oid = p.oid) a;

/* RS runs */
SELECT 'runs' AS rs, CAST(r.pl AS char(36)) pl, CAST(r.run AS char(36)) run, n.strName, pr.NomDiaSize, pr.NPDUnitType, pr.IsInsulated,
       pr.InsulationThickness, pr.InsulationPurpose, pr.InsulationMaterial, pr.InsulationTemperature, pr.FlowDirection, pr.PipeRunType,
       pr.MinSlope, CAST(sp.oidTarget AS char(36)) specproxy
FROM #runs r LEFT JOIN dbo.ROUTEPipeRun pr ON pr.oid = r.run LEFT JOIN dbo.CORENamedItem n ON n.oid = r.run
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = r.run AND x.RelationType = '%(PathRunUsesSpec)s') sp;

/* RS parts */
SELECT 'parts' AS rs, CAST(p.run AS char(36)) run, CAST(p.part AS char(36)) part, p.cls, n.strName,
       CAST(mf.oidTarget AS char(36)) madefrom, CAST(mc.oidTarget AS char(36)) matctl,
       po.PipeLength, po.CutLength, po.bIsPlainPiping,
       COALESCE(po.ShortMaterialDescription, oc.ShortMaterialDescription, io.ShortMaterialDescription, so.ShortMaterialDescription) descr,
       oc.ShortCode, oc.PartType, oc.OptionCode, oc.IsBasePart,
       COALESCE(po.DryWeight, oc.DryWeight, io.DryWeight, so.DryWeight) wt,
       COALESCE(po.IsInsulated, oc.IsInsulated, io.IsInsulated, so.IsInsulated) ins
FROM #parts p LEFT JOIN dbo.CORENamedItem n ON n.oid = p.part
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = p.part AND x.RelationType = '%(madeFrom)s') mf
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = p.part AND x.RelationType = '%(MatCtl)s') mc
LEFT JOIN dbo.ROUTEPipeOccur po ON po.oid = p.part
LEFT JOIN dbo.ROUTEPipeComponentOcc oc ON oc.oid = p.part
LEFT JOIN dbo.ROUTEPipeInstrumentOcc io ON io.oid = p.part
LEFT JOIN dbo.ROUTEPipeSpecialtyOcc so ON so.oid = p.part;

/* ports + the distribution connection each sits on */
SELECT p.part, dp.oidTarget AS port, pp.PortIndex, pn.RelationName pname, conn.oid AS conn,
       pp.PlacePointX, pp.PlacePointY, pp.PlacePointZ, pp.OrientationX, pp.OrientationY, pp.OrientationZ,
       pp.NPD, pp.NPDUnitType, pp.PipingOutsideDiameter, pp.WallThicknessOrGrooveSetback, pp.ScheduleThickness, pp.EndPreparation,
       pp.PressureRating, pp.EndStandard, pp.FlangeOrHubOutsideDiameter, pp.FlangeOrHubThickness
INTO #ports
FROM #parts p JOIN dbo.CORERelationOrigin dp ON dp.oid = p.part AND dp.RelationType = '%(DistribPorts)s'
LEFT JOIN dbo.ROUTEPipePort pp ON pp.oid = dp.oidTarget
LEFT JOIN dbo.CORERelationOrigin pn ON pn.oidTarget = dp.oidTarget AND pn.RelationType = '%(ProxyOwner)s' AND pp.oid IS NULL
LEFT JOIN dbo.CORERelationOrigin conn ON conn.oidTarget = dp.oidTarget AND conn.RelationType = '%(FlowPorts)s';

SELECT DISTINCT conn INTO #conn FROM (
  SELECT conn FROM #ports WHERE conn IS NOT NULL
  UNION SELECT x.oidTarget FROM #runs r JOIN dbo.CORERelationOrigin x ON x.oid = r.run AND x.RelationType = '%(OwnsDistConn)s') u;
CREATE CLUSTERED INDEX ix_conn ON #conn(conn);

SELECT 'ports' AS rs, CAST(p.part AS char(36)) part, CAST(p.port AS char(36)) port, p.PortIndex, p.pname, CAST(p.conn AS char(36)) conn,
       p.PlacePointX, p.PlacePointY, p.PlacePointZ, p.OrientationX, p.OrientationY, p.OrientationZ,
       p.NPD, p.NPDUnitType, p.PipingOutsideDiameter, p.WallThicknessOrGrooveSetback, p.ScheduleThickness, p.EndPreparation,
       p.PressureRating, p.EndStandard, p.FlangeOrHubOutsideDiameter, p.FlangeOrHubThickness
FROM #ports p;

/* RS connections: location/type, owner run, joined parts and ports (with equipment nozzle owner) */
SELECT 'conns' AS rs, CAST(c.conn AS char(36)) conn, dc.LocationX, dc.LocationY, dc.LocationZ, dc.ConnectionSize, dc.ConnectionType, dc.IsParent,
       CAST(ow.oid AS char(36)) ownerrun
FROM #conn c JOIN dbo.ROUTEDistribConnection dc ON dc.oid = c.conn
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = c.conn AND x.RelationType = '%(OwnsDistConn)s') ow;

SELECT 'connparts' AS rs, CAST(c.conn AS char(36)) conn, CAST(x.oidTarget AS char(36)) part, b.ClassId,
       CAST(orun.oid AS char(36)) otherrun, CAST(opl.oid AS char(36)) otherpl, opn.strName otherplname
FROM #conn c JOIN dbo.CORERelationOrigin x ON x.oid = c.conn AND x.RelationType = '%(RelConnPart)s'
JOIN dbo.COREBaseClass b ON b.oid = x.oidTarget
LEFT JOIN #parts mine ON mine.part = x.oidTarget
OUTER APPLY (SELECT TOP 1 y.oid FROM dbo.CORERelationOrigin y WHERE mine.part IS NULL AND y.oidTarget = x.oidTarget AND y.RelationType = '%(OwnsParts)s') orun
OUTER APPLY (SELECT TOP 1 z.oid FROM dbo.CORERelationOrigin z WHERE orun.oid IS NOT NULL AND z.oidTarget = orun.oid AND z.RelationType = '%(SystemHierarchy)s') opl
LEFT JOIN dbo.CORENamedItem opn ON opn.oid = opl.oid;

SELECT 'connports' AS rs, CAST(c.conn AS char(36)) conn, CAST(x.oidTarget AS char(36)) port, LEFT(CAST(x.oidTarget AS char(36)), 8) pcls,
       CAST(eq.oid AS char(36)) equip, eq.RelationName nozzle, en.strName equipname
FROM #conn c JOIN dbo.CORERelationOrigin x ON x.oid = c.conn AND x.RelationType = '%(FlowPorts)s'
OUTER APPLY (SELECT TOP 1 e.oid, e.RelationName FROM dbo.CORERelationOrigin e
             WHERE LEFT(CAST(x.oidTarget AS char(36)), 8) NOT IN ('0001388E', '00000009') AND e.oidTarget = x.oidTarget
               AND e.RelationType = '%(DistribPorts)s') eq
LEFT JOIN dbo.CORENamedItem en ON en.oid = eq.oid;

SELECT 'extpipes' AS rs, CAST(x.oidTarget AS char(36)) part, pp.PortIndex, pp.PlacePointX X, pp.PlacePointY Y, pp.PlacePointZ Z
FROM #conn c JOIN dbo.CORERelationOrigin x ON x.oid = c.conn AND x.RelationType = '%(RelConnPart)s'
LEFT JOIN #parts mine ON mine.part = x.oidTarget
JOIN dbo.CORERelationOrigin dp ON mine.part IS NULL AND LEFT(CAST(x.oidTarget AS char(36)), 8) = '0001388C'
     AND dp.oid = x.oidTarget AND dp.RelationType = '%(DistribPorts)s'
JOIN dbo.ROUTEPipePort pp ON pp.oid = dp.oidTarget
ORDER BY 2, 3;

/* RS connection items: welds, gaskets, bolt sets (generated at connections this batch owns or touches) */
SELECT 'items' AS rs, CAST(c.conn AS char(36)) conn, CAST(gi.oidTarget AS char(36)) item, b.ClassId,
       w.Type WeldType, w.Class WeldClass, w.LocationX wx, w.LocationY wy, w.LocationZ wz, w.WeldThickness, w.WeldGap, w.FieldFitLength, w.WPSNumber,
       g.GasketSizedCommodityCode, COALESCE(g.ShortMaterialDescription, bs.ShortMaterialDescription) ItemDescription,
       bs.BoltQuantity, bs.Diameter BoltDia, bs.RoundedLength BoltLength, bs.CalculatedLength BoltCalcLength, bs.NutQuantity, bs.WasherQuantity,
       bs.NutSizedCommodityCode, bs.WasherSizedCommodityCode, n.strName
FROM #conn c JOIN dbo.CORERelationOrigin gi ON gi.oid = c.conn AND gi.RelationType = '%(GenConnItems)s'
LEFT JOIN dbo.COREBaseClass b ON b.oid = gi.oidTarget
LEFT JOIN dbo.ROUTEPipeWeld w ON w.oid = gi.oidTarget
LEFT JOIN dbo.ROUTEPipeGasket g ON g.oid = gi.oidTarget
LEFT JOIN dbo.ROUTEPipeBoltSet bs ON bs.oid = gi.oidTarget
LEFT JOIN dbo.CORENamedItem n ON n.oid = gi.oidTarget;

/* RS generating path features */
SELECT 'feats' AS rs, CAST(p.part AS char(36)) part, CAST(f.oid AS char(36)) feat, b.ClassId featcls,
  COALESCE(t.LocationX, br.LocationX, s.LocationX, a.LocationX, e.LocationX) CPX,
  COALESCE(t.LocationY, br.LocationY, s.LocationY, a.LocationY, e.LocationY) CPY,
  COALESCE(t.LocationZ, br.LocationZ, s.LocationZ, a.LocationZ, e.LocationZ) CPZ,
  t.BendAngle, t.BendRadius, t.TurnType, t.NoOfMiters, t.ThroatRadius, br.Angle BranchAngle,
  br.BranchOffsetX, br.BranchOffsetY, br.BranchOffsetZ,
  COALESCE(t.NomDiam, br.NomDiam, s.NomDiam, a.NomDiam, e.NomDiam) NomDiam,
  COALESCE(t.NPDUnitType, br.NPDUnitType, s.NPDUnitType, a.NPDUnitType, e.NPDUnitType) NPDUnit,
  COALESCE(t.OuterDiameter, br.OuterDiameter, s.OuterDiameter, a.OuterDiameter, e.OuterDiameter) FeatOD,
  COALESCE(t.ShortCode, br.ShortCode, s.ShortCode, a.ShortCode, e.ShortCode) FeatShortCode,
  COALESCE(t.Tag, br.Tag, s.Tag, a.Tag, e.Tag) Tag,
  COALESCE(t.IsInsulated, br.IsInsulated, s.IsInsulated, a.IsInsulated, e.IsInsulated) FIns,
  COALESCE(t.InsulationThickness, br.InsulationThickness, s.InsulationThickness, a.InsulationThickness, e.InsulationThickness) FInsThk,
  a.UVectorX, a.UVectorY, a.UVectorZ, a.RotateAngle
FROM #parts p
JOIN dbo.CORERelationOrigin f ON f.oidTarget = p.part AND f.RelationType = '%(PathGenParts)s'
JOIN dbo.COREBaseClass b ON b.oid = f.oid
LEFT JOIN dbo.ROUTEPipeTurnPathFeat t     ON t.oid = f.oid
LEFT JOIN dbo.ROUTEPipeBranchPathFeat br  ON br.oid = f.oid
LEFT JOIN dbo.ROUTEPipeStraightPathFeat s ON s.oid = f.oid
LEFT JOIN dbo.ROUTEPipeAlongLegPathFeat a ON a.oid = f.oid
LEFT JOIN dbo.ROUTEPipeEndPathFeat e      ON e.oid = f.oid;

/* RS placement matrices of non-pipe parts */
SELECT 'syms' AS rs, CAST(p.part AS char(36)) part, s.ServerToClient0 m0, s.ServerToClient1 m1, s.ServerToClient2 m2,
       s.ServerToClient4 m4, s.ServerToClient5 m5, s.ServerToClient6 m6, s.ServerToClient8 m8, s.ServerToClient9 m9, s.ServerToClient10 m10,
       s.ServerToClient12 m12, s.ServerToClient13 m13, s.ServerToClient14 m14
FROM #parts p JOIN dbo.CORESymbol s ON s.oid = p.part WHERE p.cls <> 80012;

/* RS occurrence attributes of instruments / specialties / components (face-to-face, actuator dims, overrides) */
SELECT 'occattr' AS rs, CAST(p.part AS char(36)) part, CAST(a.iid AS char(36)) iid, a.dispid, a.d, a.l, a.s
FROM #parts p CROSS APPLY (
  SELECT iid, dispid, value d, CAST(NULL AS int) l, CAST(NULL AS nvarchar(400)) s FROM dbo.COREDoubleAttribute WHERE oid = p.part
  UNION ALL SELECT iid, dispid, NULL, value, NULL FROM dbo.CORELongAttribute WHERE oid = p.part
  UNION ALL SELECT iid, dispid, NULL, NULL, CAST(value AS nvarchar(400)) FROM dbo.COREBstrAttribute WHERE oid = p.part) a
WHERE p.cls <> 80012;

/* RS supports */
SELECT 'supports' AS rs, CAST(r.oid AS char(36)) pl, CAST(s.oid AS char(36)) support, n.strName, s.BOMdescription, s.SupportStatus, s.MaxLoad,
       asy.RelationName CatalogAssembly,
       cs.o0, cs.o1, cs.o2, cs.x0, cs.x1, cs.x2, cs.z0, cs.z1, cs.z2,
       si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax, CAST(cf.oidTarget AS char(36)) feat
FROM #pl p JOIN dbo.CORERelationOrigin r ON r.oid = p.oid AND r.RelationType = '%(SystemHasSupport)s'
JOIN dbo.HNGSUPHgrPipeSupport s ON s.oid = r.oidTarget
LEFT JOIN dbo.CORENamedItem n ON n.oid = s.oid
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = s.oid
OUTER APPLY (SELECT TOP 1 c.* FROM dbo.CORERelationOrigin x JOIN dbo.GRDSYSSPGCoordinateSystem c ON c.oid = x.oidTarget
             WHERE x.oid = s.oid AND x.RelationType = '%(SupportHasCS)s') cs
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = '%(ProxyOwner)s'
             WHERE x.oid = s.oid AND x.RelationType = '%(OccAssyHasPart)s') asy
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = s.oid AND x.RelationType = '%(ConnHasPorts)s') cf;

SELECT 'supcomps' AS rs, CAST(r.oidTarget AS char(36)) support, CAST(c.oidTarget AS char(36)) comp, b.ClassId, c.RelationName role,
       COALESCE(sc.BOMdescription, cc.BOMdescription) BOM, CAST(mf.oidTarget AS char(36)) madefrom,
       si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax,
       sy.ServerToClient0 m0, sy.ServerToClient1 m1, sy.ServerToClient2 m2, sy.ServerToClient4 m4, sy.ServerToClient5 m5, sy.ServerToClient6 m6,
       sy.ServerToClient8 m8, sy.ServerToClient9 m9, sy.ServerToClient10 m10, sy.ServerToClient12 m12, sy.ServerToClient13 m13, sy.ServerToClient14 m14
FROM #pl p JOIN dbo.CORERelationOrigin r ON r.oid = p.oid AND r.RelationType = '%(SystemHasSupport)s'
JOIN dbo.CORERelationOrigin c ON c.oid = r.oidTarget AND c.RelationType = '%(SupportHasComponents)s'
LEFT JOIN dbo.COREBaseClass b ON b.oid = c.oidTarget
LEFT JOIN dbo.HNGSUPHgrStdComponent sc ON sc.oid = c.oidTarget
LEFT JOIN dbo.HNGSUPHgrConnComponent cc ON cc.oid = c.oidTarget
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = c.oidTarget
LEFT JOIN dbo.CORESymbol sy ON sy.oid = c.oidTarget
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = c.oidTarget AND x.RelationType = '%(madeFrom)s') mf;

DROP TABLE #conn; DROP TABLE #ports; DROP TABLE #parts; DROP TABLE #runs; DROP TABLE #pl;
"""


def batch_sql(pl_values):
    return BATCH_SQL % dict(R, PL=pl_values)
