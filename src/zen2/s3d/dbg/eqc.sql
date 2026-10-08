SET NOCOUNT ON;
DECLARE @o uniqueidentifier = (SELECT TOP 1 e.oid FROM dbo.EQUIPEquipmentComponent e JOIN dbo.CORERelationOrigin r ON r.oid=e.oid AND r.RelationType='B6BBA674-B690-422F-9471-0F50934271F8');
SELECT CAST(@o AS char(36)) eqcomp;
SELECT 'OUT' dir, rn.Name rel, COUNT(*) n, MIN(b.ClassId) cls FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget WHERE r.oid=@o GROUP BY rn.Name
UNION ALL
SELECT 'IN', rn.Name, COUNT(*), MIN(b.ClassId) FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid WHERE r.oidTarget=@o GROUP BY rn.Name;
SELECT TABLE_NAME, STRING_AGG(COLUMN_NAME, ',') FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME IN ('STRUCTMembPartAxisCurve','STRUCTSPSSlabEntity','STRUCTFooting','EQUIPShape') GROUP BY TABLE_NAME;
SELECT COUNT(*) nEqComp FROM dbo.EQUIPEquipmentComponent;
SELECT COUNT(*) nEqWithShapes FROM (SELECT DISTINCT r.oid FROM dbo.CORERelationOrigin r WITH (INDEX(CORERelationOriginTypeIndex)) WHERE r.RelationType='B6BBA674-B690-422F-9471-0F50934271F8') x;
