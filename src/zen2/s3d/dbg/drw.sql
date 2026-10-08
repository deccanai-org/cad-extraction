SET NOCOUNT ON;
SELECT t.name tbl, SUM(p.rows) nrows, (SELECT STRING_AGG(c.name + ':' + ty.name, ', ') FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id WHERE c.object_id=t.object_id) cols
FROM sys.tables t JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0,1)
WHERE t.name LIKE 'DRAWNG%' GROUP BY t.name, t.object_id ORDER BY 2 DESC;
