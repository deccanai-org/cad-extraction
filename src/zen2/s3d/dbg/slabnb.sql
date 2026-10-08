SET NOCOUNT ON;
DECLARE @o uniqueidentifier = (SELECT TOP 1 oid FROM dbo.STRUCTSPSSlabEntity ORDER BY entityTotalArea DESC);
SELECT CAST(@o AS char(36)) slab;
SELECT 'OUT' dir, rn.Name rel, COUNT(*) n, MIN(b.ClassId) cls, MIN(CAST(r.oidTarget AS char(36))) sample FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget WHERE r.oid=@o GROUP BY rn.Name
UNION ALL
SELECT 'IN', rn.Name, COUNT(*), MIN(b.ClassId), MIN(CAST(r.oid AS char(36))) FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid WHERE r.oidTarget=@o GROUP BY rn.Name;
SELECT CAST(g.oid AS char(36)) oid, g.blobSize, DATALENGTH(g.blob) stored, g.isCompressed FROM dbo.GEOTOPSolidBody g WHERE g.oid = @o;
