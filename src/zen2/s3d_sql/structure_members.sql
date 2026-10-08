/* S3D v13 structural members -> axis, orientation, section, type.  Run in MLNG@1_MDB.
   $(TOPN) = number of members (sample); remove TOP for full export (880k linear members). */
SET NOCOUNT ON;
DECLARE @MemberToXS   uniqueidentifier='11E4BF30-95B6-4996-82FE-5CEDABBC5359',  -- PrismaticGen -> MemberPartPrismatic
        @DefinitionXS uniqueidentifier='A1471E95-F9E0-409F-8BCB-6B2AF3132017',  -- PrismaticGen -> COREProxy(catalog cross-section)
        @Operand      uniqueidentifier='93F52989-9504-11D4-9D40-00105AA5BAEB',  -- PrismaticGen -> MemberPartAxisLin
        @Material     uniqueidentifier='78A872D0-953C-11D4-9D40-00105AA5BAEB',  -- PrismaticGen -> COREProxy(material)
        @DesignParent uniqueidentifier='E679D79A-0661-4802-990C-7DC0B8799D06',  -- MemberSystem -> MemberPart
        @SysParent    uniqueidentifier='07F5F6E2-8377-4F1B-93A2-3CB33D95F87F',  -- StructuralSystem -> MemberSystem
        @ProxyOwner   uniqueidentifier='5280312B-E69C-11D1-A966-080036069A02';
SELECT TOP ($(TOPN))
  CAST(mp.oid AS char(36)) MemberPart, pn.strName PartName, ssn.strName StructSystem,
  tc.ShortStringValue TypeCategory, ty.ShortStringValue MemberType,
  ax.startx, ax.starty, ax.startz, ax.endx, ax.endy, ax.endz,
  ax.betaAngle * 180 / PI() AS RollDeg, ax.OVectorx, ax.OVectory, ax.OVectorz, ax.mirror,
  pg.cardinalPoint, mp.cutLength, mp.weight,
  xs.RelationName AS SectionMoniker, mat.RelationName AS Material,
  d.Depth, d.Width, d.tf, d.tw, d.Area, d.UnitWeight
FROM dbo.STRUCTMemberPartPris mp
JOIN dbo.CORERelationOrigin g   ON g.oidTarget = mp.oid AND g.RelationType = @MemberToXS
JOIN dbo.STRUCTPartPrismaticGen pg ON pg.oid = g.oid
LEFT JOIN dbo.CORERelationOrigin ao ON ao.oid = g.oid AND ao.RelationType = @Operand
LEFT JOIN dbo.STRUCTMemberPartAxisLin ax ON ax.oid = ao.oidTarget
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = @ProxyOwner
             WHERE x.oid = g.oid AND x.RelationType = @DefinitionXS) xs
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = @ProxyOwner
             WHERE x.oid = g.oid AND x.RelationType = @Material) mat
LEFT JOIN dbo.CORERelationOrigin ms ON ms.oidTarget = mp.oid AND ms.RelationType = @DesignParent
LEFT JOIN dbo.CORERelationOrigin ss ON ss.oidTarget = ms.oid AND ss.RelationType = @SysParent
LEFT JOIN dbo.CORENamedItem pn  ON pn.oid = mp.oid
LEFT JOIN dbo.CORENamedItem ssn ON ssn.oid = ss.oid
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView tc ON tc.TableName='StructuralMemberTypeCategory' AND tc.ValueID = mp.typeCategory
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ty ON ty.TableName='StructuralMemberType' AND ty.ValueID = mp.type
/* catalog section dimensions: moniker -> CDB CORENamedObjects -> generic double attributes (metres) */
OUTER APPLY (
  SELECT MAX(CASE WHEN pnm.Name='Depth' THEN a.value END) Depth, MAX(CASE WHEN pnm.Name='Width' THEN a.value END) Width,
         MAX(CASE WHEN pnm.Name='tf' THEN a.value END) tf,       MAX(CASE WHEN pnm.Name='tw' THEN a.value END) tw,
         MAX(CASE WHEN pnm.Name='Area' THEN a.value END) Area,   MAX(CASE WHEN pnm.Name='UnitWeight' THEN a.value END) UnitWeight
  FROM [MLNG@1_CDB].dbo.CORENamedObjects cno
  JOIN [MLNG@1_CDB].dbo.COREDoubleAttribute a ON a.oid = cno.ObjectOid
  JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceDef idf ON idf.IID = a.iid
  JOIN [MLNG@1_CDB_SCHEMA].dbo.JInterface_Has_JMembers jm ON jm.oidOrg = idf.oid
  JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceMember im ON im.oid = jm.oidDst AND im.DispatchID = a.dispid
  JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject pnm ON pnm.oid = jm.oidDst
  WHERE cno.ObjectName = xs.RelationName) d
ORDER BY mp.oid;
