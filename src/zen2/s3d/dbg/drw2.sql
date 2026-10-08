SET NOCOUNT ON;
SELECT TOP 12 CAST(oid AS char(36)) oid, FileName, FileType, RelationID, LEFT(Description,60) descr, FileSize, FileCompressed FROM dbo.DRAWNGDocumentData ORDER BY oid;
SELECT FileType, COUNT(*) n, SUM(CAST(FileSize AS bigint))/1000000 mb FROM dbo.DRAWNGDocumentData GROUP BY FileType ORDER BY 2 DESC;
SELECT LEFT(CAST(oid AS char(36)),8) cls, COUNT(*) FROM dbo.DRAWNGDocumentData GROUP BY LEFT(CAST(oid AS char(36)),8);
SELECT TOP 5 CAST(strViewDBID AS char(36)) v, CAST(str3D_DBID AS char(36)) o3, str2D_DBID FROM dbo.DRAWNGDrawingMap;
SELECT TOP 5 CAST(oid AS char(36)) oid, FileName, Path, TimeLastUpdated FROM dbo.DRAWNGDrawingSheet;
SELECT TOP 5 CAST(oid AS char(36)) oid, RevMark, RevDate, LEFT(RevDesc,40) RevDesc, RevRecordType, RevVersion FROM dbo.DRAWNGDwgRevision;
SELECT TOP 5 CAST(oid AS char(36)) oid, Location, TimeCreated, TimeModified FROM dbo.DRAWNGPropertyObject;
SELECT LEFT(CAST(oid AS char(36)),8) cls, COUNT(*) FROM dbo.DRAWNGPropertyObject GROUP BY LEFT(CAST(oid AS char(36)),8);
