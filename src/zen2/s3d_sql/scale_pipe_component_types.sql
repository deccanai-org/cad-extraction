SET NOCOUNT ON;
SELECT mf.oidTarget proxy, LEFT(CAST(mf.oid AS char(36)),8) occcls, COUNT(*) n INTO #mf
FROM dbo.CORERelationOrigin mf WHERE mf.RelationType='B0E39EC4-0141-11D2-8FF2-080036E94503'
GROUP BY mf.oidTarget, LEFT(CAST(mf.oid AS char(36)),8);
SELECT m.occcls, m.n, po.RelationName moniker INTO #mn FROM #mf m
LEFT JOIN dbo.CORERelationOrigin po ON po.oidTarget=m.proxy AND po.RelationType='5280312B-E69C-11D1-A966-080036069A02' AND LEFT(CAST(po.oid AS char(36)),8)='0000000C';
SELECT m.occcls, COALESCE(sk.PCFComponentID, ct.ShortStringValue, pc.Name, '?') pcftype, SUM(m.n) n
FROM #mn m
LEFT JOIN [MLNG@1_CDB].dbo.CORENamedObjects c ON c.ObjectName=m.moniker
LEFT JOIN [MLNG@1_CDB].dbo.REFDATPipeComponent k ON k.oid=c.ObjectOid
OUTER APPLY (SELECT TOP 1 p.Name FROM [MLNG@1_CDB].dbo.CORERelationOrigin r JOIN [MLNG@1_CDB].dbo.REFDATPartClass p ON p.oid=r.oid WHERE r.oidTarget=c.ObjectOid AND r.RelationType='7FAA6155-07BE-11D2-BC6B-0800360DCD02') pc
OUTER APPLY (SELECT TOP 1 PCFComponentID FROM [MLNG@1_CDB].dbo.REFDATPipeMfgMapSymbol s WHERE s.MapType=0 AND s.PartClassName=pc.Name) sk
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ct ON ct.TableName='PipingCommodityType' AND ct.ValueID=k.CommodityType AND sk.PCFComponentID IS NULL
GROUP BY m.occcls, COALESCE(sk.PCFComponentID, ct.ShortStringValue, pc.Name, '?')
ORDER BY n DESC;
