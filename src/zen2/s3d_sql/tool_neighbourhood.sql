SET NOCOUNT ON;
DECLARE @o uniqueidentifier = '$(OID)';
SELECT 'OUT' dir, rn.Name rel, COUNT(*) n, MIN(b.ClassId) cls, MAX(j.TableName) tbl, MIN(CAST(r.oidTarget AS varchar(36))) sample, LEFT(MIN(r.RelationName),60) rname
FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget LEFT JOIN dbo.COREJPOSchema j ON j.class_id=b.ClassId
WHERE r.oid=@o GROUP BY rn.Name, j.TableName
UNION ALL
SELECT 'IN', rn.Name, COUNT(*), MIN(b.ClassId), MAX(j.TableName), MIN(CAST(r.oid AS varchar(36))), LEFT(MIN(r.RelationName),60)
FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid LEFT JOIN dbo.COREJPOSchema j ON j.class_id=b.ClassId
WHERE r.oidTarget=@o GROUP BY rn.Name, j.TableName
ORDER BY 1,2;
