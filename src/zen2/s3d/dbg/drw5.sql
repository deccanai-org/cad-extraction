SET NOCOUNT ON;
DECLARE @x uniqueidentifier = '0001ADD6-0000-0000-D018-0B7EFA595B04';
SELECT 'IN' dir, rn.Name rel, COUNT(*) n, MIN(b.ClassId) cls, MIN(CAST(r.oid AS char(36))) s FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid WHERE r.oidTarget=@x GROUP BY rn.Name
UNION ALL SELECT 'OUT', rn.Name, COUNT(*), MIN(b.ClassId), MIN(CAST(r.oidTarget AS char(36))) FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget WHERE r.oid=@x GROUP BY rn.Name;
SELECT j.class_id, c.Name FROM dbo.COREJPOSchema j LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.ClassInfoView c ON c.CLSID=j.BOClsid WHERE j.class_id IN (110038, 110067, 110051);
SELECT (SELECT RelationGUID FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView WHERE RelationName='PropertiesHasRevisions') g;
