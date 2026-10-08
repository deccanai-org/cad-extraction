/* Connection items (welds, gaskets, bolt sets) and pipe supports for ONE pipeline. $(PL) = pipeline oid */
SET NOCOUNT ON;
DECLARE @pl uniqueidentifier = '$(PL)';
DECLARE @SystemHierarchy uniqueidentifier='A8CE36E7-A53F-4558-8DF9-F0BCE6583327',
        @OwnsDistConn    uniqueidentifier='67E1D32D-38B0-4885-8F1A-784627305608',
        @GenConnItems    uniqueidentifier='95A02A64-195B-46D4-BE9E-2A4A15A9F90D',
        @SystemHasSupport uniqueidentifier='F2B9B39A-909D-4F1B-9ED5-2E66D26EAFEC',
        @SupportHasComponents uniqueidentifier='1781C544-33A0-4982-ACE1-BCBCBAEA5006',
        @SupportHasCS    uniqueidentifier='0E77B4AF-2DEB-4D45-953F-F59D0D36A601',
        @ProxyOwner      uniqueidentifier='5280312B-E69C-11D1-A966-080036069A02',
        @OccAssyHasPart  uniqueidentifier='1613374A-A8F0-11D4-BA3D-009027955FAD';

/* A. distribution connections of every run + generated items */
SELECT rn.strName PipeRun, CAST(dc.oid AS char(36)) Conn, ct.ShortStringValue ConnType,
       dc.LocationX, dc.LocationY, dc.LocationZ, dc.ConnectionSize,
       j.TableName ItemTable, w.Type WeldTypeCode, wt.ShortStringValue WeldType,
       g.GasketSizedCommodityCode, COALESCE(g.ShortMaterialDescription, bs.ShortMaterialDescription) ItemDescription,
       bs.BoltQuantity, bs.Diameter BoltDia, bs.RoundedLength BoltLength
FROM dbo.CORERelationOrigin r1
JOIN dbo.CORERelationOrigin r2 ON r2.oid = r1.oidTarget AND r2.RelationType = @OwnsDistConn
JOIN dbo.ROUTEDistribConnection dc ON dc.oid = r2.oidTarget
LEFT JOIN dbo.CORENamedItem rn ON rn.oid = r1.oidTarget
LEFT JOIN dbo.CORERelationOrigin gi ON gi.oid = dc.oid AND gi.RelationType = @GenConnItems
LEFT JOIN dbo.COREBaseClass b ON b.oid = gi.oidTarget
LEFT JOIN dbo.COREJPOSchema j ON j.class_id = b.ClassId
LEFT JOIN dbo.ROUTEPipeWeld w ON w.oid = gi.oidTarget
LEFT JOIN dbo.ROUTEPipeGasket g ON g.oid = gi.oidTarget
LEFT JOIN dbo.ROUTEPipeBoltSet bs ON bs.oid = gi.oidTarget
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ct ON ct.TableName='ConnectionType' AND ct.ValueID = dc.ConnectionType
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView wt ON wt.TableName='WeldType' AND wt.ValueID = w.Type
WHERE r1.oid = @pl AND r1.RelationType = @SystemHierarchy
ORDER BY rn.strName, dc.LocationX, dc.LocationY, dc.LocationZ;

/* B. pipe supports: name, BOM text, catalog assembly (proxy moniker), CS origin, bbox, components */
SELECT CAST(s.oid AS char(36)) Support, n.strName, s.BOMdescription, asy.RelationName CatalogAssembly,
       cs.o0 OriginX, cs.o1 OriginY, cs.o2 OriginZ, cs.z0 AxisZx, cs.z1 AxisZy, cs.z2 AxisZz,
       si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax,
       (SELECT COUNT(*) FROM dbo.CORERelationOrigin c WHERE c.oid = s.oid AND c.RelationType = @SupportHasComponents) nComponents
FROM dbo.CORERelationOrigin r
JOIN dbo.HNGSUPHgrPipeSupport s ON s.oid = r.oidTarget
LEFT JOIN dbo.CORENamedItem n ON n.oid = s.oid
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = s.oid
OUTER APPLY (SELECT TOP 1 c.* FROM dbo.CORERelationOrigin x JOIN dbo.GRDSYSSPGCoordinateSystem c ON c.oid = x.oidTarget
             WHERE x.oid = s.oid AND x.RelationType = @SupportHasCS) cs
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = @ProxyOwner
             WHERE x.oid = s.oid AND x.RelationType = @OccAssyHasPart) asy
WHERE r.oid = @pl AND r.RelationType = @SystemHasSupport;
