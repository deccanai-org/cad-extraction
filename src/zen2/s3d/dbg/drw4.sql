SET NOCOUNT ON;
DECLARE @r uniqueidentifier = (SELECT TOP 1 oid FROM dbo.DRAWNGDwgRevision ORDER BY oid);
SELECT 'REV-IN' dir, rn.Name rel, CAST(r.oid AS char(36)) other, b.ClassId FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oid WHERE r.oidTarget=@r
UNION ALL SELECT 'REV-OUT', rn.Name, CAST(r.oidTarget AS char(36)), b.ClassId FROM dbo.CORERelationOrigin r
 LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJRelationDef rd ON rd.RelationGUID=r.RelationType LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject rn ON rn.oid=rd.oid
 LEFT JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget WHERE r.oid=@r;
/* what do sheets target */
SELECT b.ClassId tcls, COUNT(*) n FROM dbo.DRAWNGDrawingSheet s JOIN dbo.CORERelationOrigin r ON r.oid=s.oid AND r.RelationType=(SELECT TOP 1 RelationGUID FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView WHERE RelationName='SheetToDrawingTarget')
JOIN dbo.COREBaseClass b ON b.oid=r.oidTarget GROUP BY b.ClassId ORDER BY 2 DESC;
SELECT COUNT(*) sheets FROM dbo.DRAWNGDrawingSheet;
SELECT RelationGUID, RelationName FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView WHERE RelationName IN ('SheetToDrawingTarget','ObjectHasOutput','MgrHasDataDocuments','SheetHasProperty','SheetHasViews','SnapInHasSheets','SheetToIsoStyle','ObjectHasTemplates');
