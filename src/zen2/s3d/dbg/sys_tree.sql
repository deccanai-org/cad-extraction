SET NOCOUNT ON;
SELECT CAST(r.oid AS char(36)) parent, CAST(r.oidTarget AS char(36)) child, bp.ClassId pcls, bc.ClassId ccls, n.strName cname
FROM dbo.CORERelationOrigin r WITH (INDEX(CORERelationOriginTypeIndex))
JOIN dbo.COREBaseClass bc ON bc.oid = r.oidTarget
JOIN dbo.COREBaseClass bp ON bp.oid = r.oid
LEFT JOIN dbo.CORENamedItem n ON n.oid = r.oidTarget
WHERE r.RelationType='A8CE36E7-A53F-4558-8DF9-F0BCE6583327' AND LEFT(CAST(r.oidTarget AS char(36)),8) <> '0001388D';
SELECT '#ROOTS';
SELECT CAST(b.oid AS char(36)) oid, b.ClassId, n.strName FROM dbo.COREBaseClass b LEFT JOIN dbo.CORENamedItem n ON n.oid=b.oid
WHERE b.ClassId IN (SELECT class_id FROM dbo.COREJPOSchema WHERE TableName LIKE 'SHPCON%' OR TableName LIKE '%RootSystem%' OR TableName LIKE 'GSCAD%')
 AND NOT EXISTS (SELECT 1 FROM dbo.CORERelationOrigin r WHERE r.oidTarget=b.oid AND r.RelationType='A8CE36E7-A53F-4558-8DF9-F0BCE6583327');
SELECT '#CLASSES';
SELECT class_id, TableName FROM dbo.COREJPOSchema WHERE TableName LIKE 'SHPCON%' OR TableName LIKE '%System%';
