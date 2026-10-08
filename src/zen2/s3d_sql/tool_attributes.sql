SET NOCOUNT ON;
DECLARE @o uniqueidentifier = '$(OID)';
WITH a AS (
 SELECT iid, dispid, CAST(value AS nvarchar(200)) v, 'D' t FROM dbo.COREDoubleAttribute WHERE oid=@o
 UNION ALL SELECT iid, dispid, CAST(value AS nvarchar(200)), 'L' FROM dbo.CORELongAttribute WHERE oid=@o
 UNION ALL SELECT iid, dispid, CAST(value AS nvarchar(200)), 'S' FROM dbo.COREBstrAttribute WHERE oid=@o
 UNION ALL SELECT iid, dispid, CAST(value AS nvarchar(200)), 'B' FROM dbo.COREBoolAttribute WHERE oid=@o)
SELECT a.t, ifn.Name iface, pn.Name prop, a.v
FROM a
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceDef id ON id.IID=a.iid
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject ifn ON ifn.oid=id.oid
OUTER APPLY (SELECT TOP 1 pn.Name FROM [MLNG@1_CDB_SCHEMA].dbo.JInterface_Has_JMembers m JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceMember im ON im.oid=m.oidDst AND im.DispatchID=a.dispid JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject pn ON pn.oid=m.oidDst WHERE m.oidOrg=id.oid) pn
ORDER BY 2,3;
