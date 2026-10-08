SET NOCOUNT ON;
DECLARE @o uniqueidentifier = (SELECT TOP 1 oid FROM dbo.COREBaseClass WITH (INDEX(COREBaseClassClassIdIndex)) WHERE ClassId=10027 AND (persistentFlag & 1024)=0);
SELECT CAST(@o AS char(36)) op;
SELECT 'OUT' dir, rn.Name rel, CAST(r.oidTarget AS char(36)) other, b.ClassId, r.RelationName FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget WHERE r.oid=@o
UNION ALL
SELECT 'IN', rn.Name, CAST(r.oid AS char(36)), b.ClassId, r.RelationName FROM dbo.CORERelationOrigin r
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid WHERE r.oidTarget=@o;
SELECT CAST(RelationType AS char(36)) rt FROM dbo.CORERelationOrigin WHERE oidTarget=@o;
SELECT ServerToClient0,ServerToClient1,ServerToClient2,ServerToClient4,ServerToClient5,ServerToClient6,ServerToClient8,ServerToClient9,ServerToClient10,ServerToClient12,ServerToClient13,ServerToClient14 FROM dbo.CORESymbol WHERE oid=@o;
