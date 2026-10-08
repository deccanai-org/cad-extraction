SET NOCOUNT ON;
DECLARE @d uniqueidentifier = (SELECT TOP 1 oid FROM dbo.DRAWNGDocumentData WHERE FileType='pcf' ORDER BY oid);
DECLARE @s uniqueidentifier = (SELECT TOP 1 oid FROM dbo.DRAWNGDrawingSheet ORDER BY oid);
SELECT 'doc' what, CAST(@d AS char(36)) oid, (SELECT FileName FROM dbo.DRAWNGDocumentData WHERE oid=@d) fn;
SELECT 'DOC-OUT' dir, rn.Name rel, CAST(r.oidTarget AS char(36)) other, b.ClassId, r.RelationName FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget WHERE r.oid=@d
UNION ALL SELECT 'DOC-IN', rn.Name, CAST(r.oid AS char(36)), b.ClassId, r.RelationName FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid WHERE r.oidTarget=@d;
SELECT 'SHEET-OUT' dir, rn.Name rel, CAST(r.oidTarget AS char(36)) other, b.ClassId, r.RelationName FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget WHERE r.oid=@s
UNION ALL SELECT 'SHEET-IN', rn.Name, CAST(r.oid AS char(36)), b.ClassId, r.RelationName FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid WHERE r.oidTarget=@s;
SELECT j.class_id, j.TableName, c.Name FROM dbo.COREJPOSchema j LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.ClassInfoView c ON c.CLSID=j.BOClsid WHERE j.class_id IN (110050,110051,110052,110053,110054,110055,110056,110057,110058,110059,110060,110061,110062,110063,110064,110066,110067,110068,110069,110070,110071,110080,110014,110015,110016,110017,110018,110019,110020,110021,110022,110023,110024,110025,110026,110027,110028,110029,110030) OR j.TableName LIKE 'DRAWNG%';
