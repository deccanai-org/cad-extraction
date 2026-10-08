/* ============================================================================
   S3D v13 -> ordered component list for ONE pipeline (PCF-ready)
   Run in MLNG@1_MDB. Read-only (temp tables only). Parameter: $(PL) = pipeline oid
   ============================================================================ */
SET NOCOUNT ON;
DECLARE @pl uniqueidentifier = '$(PL)';
DECLARE @SystemHierarchy uniqueidentifier='A8CE36E7-A53F-4558-8DF9-F0BCE6583327',
        @OwnsParts       uniqueidentifier='3C9A3EEE-3F54-441F-A3D4-DCFC4615E88D',
        @madeFrom        uniqueidentifier='B0E39EC4-0141-11D2-8FF2-080036E94503',
        @ProxyOwner      uniqueidentifier='5280312B-E69C-11D1-A966-080036069A02',
        @PathGenParts    uniqueidentifier='C9820593-3838-11D2-BE94-080036B8A403',
        @RelConnPart     uniqueidentifier='71EEA3EB-F909-48B8-92A3-E04ED3E6E780',
        @FlowPorts       uniqueidentifier='42188F92-332B-11D4-93F0-080036B9BD03',
        @DistribPorts    uniqueidentifier='BFE914B5-978E-11D3-BFF3-080036B8A403',
        @MatCtl          uniqueidentifier='ED1D6AE6-1E81-42F7-A101-D79DD9F18096',
        @PartClassParts  uniqueidentifier='7FAA6155-07BE-11D2-BC6B-0800360DCD02',
        @PartNozzles     uniqueidentifier='F6AD318F-4BE0-11D2-BC7F-0800360DCD02',
        @MatCtlForComp   uniqueidentifier='33F05030-A9D7-4687-A7E0-43431A7EE452';

/* 1. pipeline -> runs -> parts */
SELECT r1.oidTarget AS run, r2.oidTarget AS part, b.ClassId AS cls
INTO #parts
FROM dbo.CORERelationOrigin r1
JOIN dbo.CORERelationOrigin r2 ON r2.oid = r1.oidTarget AND r2.RelationType = @OwnsParts
JOIN dbo.COREBaseClass b       ON b.oid = r2.oidTarget
WHERE r1.oid = @pl AND r1.RelationType = @SystemHierarchy;
CREATE CLUSTERED INDEX ix ON #parts(part);

/* 2. catalog part: madeFrom -> COREProxy -> ProxyOwner.RelationName (moniker) -> CDB CORENamedObjects
      (instrument/specialty parts are model-resident: madeFrom points straight at MDB REFDATPipeComponent) */
SELECT p.part, mf.oidTarget AS proxy, po.RelationName AS moniker,
       COALESCE(cno.ObjectOid, oidname.oid, CASE WHEN mdbpc.oid IS NOT NULL THEN mf.oidTarget END) AS catoid,
       CASE WHEN COALESCE(cno.ObjectOid, oidname.oid) IS NOT NULL THEN 'CDB' WHEN mdbpc.oid IS NOT NULL THEN 'MDB' END AS catdb
INTO #cat
FROM #parts p
JOIN dbo.CORERelationOrigin mf ON mf.oid = p.part AND mf.RelationType = @madeFrom
LEFT JOIN dbo.CORERelationOrigin po ON po.oidTarget = mf.oidTarget AND po.RelationType = @ProxyOwner
                                    AND po.oid IN (SELECT oid FROM dbo.CORESite)
LEFT JOIN [MLNG@1_CDB].dbo.CORENamedObjects cno ON cno.ObjectName = po.RelationName
LEFT JOIN [MLNG@1_CDB].dbo.COREBaseClass oidname                        -- some monikers are '{catalog-oid}'
       ON po.RelationName LIKE '{%}' AND oidname.oid = TRY_CAST(SUBSTRING(po.RelationName, 2, 36) AS uniqueidentifier)
LEFT JOIN dbo.REFDATPipeComponent mdbpc ON mdbpc.oid = mf.oidTarget;

SELECT c.part, c.catdb, c.moniker,
       COALESCE(k.PartNumber, m.PartNumber) PartNumber,
       COALESCE(k.IndustryCommodityCode, m.IndustryCommodityCode) IndustryCommodityCode,
       COALESCE(k.CommodityType, m.CommodityType) CommodityType, COALESCE(k.CommodityClass, m.CommodityClass) CommodityClass,
       COALESCE(k.GeometryType, m.GeometryType) GeometryType,
       COALESCE(k.MaterialGrade, m.MaterialGrade) MaterialGrade,
       COALESCE(k.PrimarySize, m.PrimarySize) PrimarySize, COALESCE(k.PriSizeNPDUnits, m.PriSizeNPDUnits) PriUnits,
       COALESCE(k.SecondarySize, m.SecondarySize) SecondarySize,
       COALESCE(k.FirstSizeSchedule, m.FirstSizeSchedule) Sched1, COALESCE(k.SecondSizeSchedule, m.SecondSizeSchedule) Sched2,
       COALESCE(k.FirstSizeOutsideDiameter, m.FirstSizeOutsideDiameter) OD1, COALESCE(k.SecondSizeOutsideDiameter, m.SecondSizeOutsideDiameter) OD2,
       COALESCE(k.BendRadius, m.BendRadius) CatBendRadius,
       COALESCE(pck.Name, pcm.Name) PartClass
INTO #catp
FROM #cat c
LEFT JOIN [MLNG@1_CDB].dbo.REFDATPipeComponent k ON c.catdb='CDB' AND k.oid = c.catoid
LEFT JOIN dbo.REFDATPipeComponent m              ON c.catdb='MDB' AND m.oid = c.catoid
OUTER APPLY (SELECT TOP 1 pc.Name FROM [MLNG@1_CDB].dbo.CORERelationOrigin r JOIN [MLNG@1_CDB].dbo.REFDATPartClass pc ON pc.oid=r.oid
             WHERE c.catdb='CDB' AND r.oidTarget=c.catoid AND r.RelationType=@PartClassParts) pck
OUTER APPLY (SELECT TOP 1 COALESCE(pc.Name, px.RelationName) AS Name     -- model-resident part: part class is a catalog proxy
             FROM dbo.CORERelationOrigin r
             LEFT JOIN dbo.REFDATPartClass pc ON pc.oid = r.oid
             LEFT JOIN dbo.CORERelationOrigin px ON px.oidTarget = r.oid AND px.RelationType = @ProxyOwner
             WHERE c.catdb='MDB' AND r.oidTarget=c.catoid AND r.RelationType=@PartClassParts) pcm;

/* 2b. catalog port definitions (end prep / rating / schedule per PortIndex) and instrument/specialty tag data */
SELECT c.part, cp.PortIndex, cp.Npd, cp.NpdUnitType, cp.EndPrep, cp.PressureRating, cp.ScheduleThickness
INTO #cport
FROM #cat c
JOIN [MLNG@1_CDB].dbo.CORERelationOrigin r ON c.catdb='CDB' AND r.oid = c.catoid AND r.RelationType = @PartNozzles
JOIN [MLNG@1_CDB].dbo.REFDATPipePort cp ON cp.oid = r.oidTarget
UNION ALL
SELECT c.part, cp.PortIndex, cp.Npd, cp.NpdUnitType, cp.EndPrep, cp.PressureRating, cp.ScheduleThickness
FROM #cat c
JOIN dbo.CORERelationOrigin r ON c.catdb='MDB' AND r.oid = c.catoid AND r.RelationType = @PartNozzles
JOIN dbo.REFDATPipePort cp ON cp.oid = r.oidTarget;

SELECT c.part, COALESCE(i.TagNumber, s.TagNumber) TagNumber,
       COALESCE(i.ContractorCommodityCode, s.ContractorCommodityCode) TagCommodityCode,
       COALESCE(i.ShortMaterialDescription, s.ShortMaterialDescription) TagDescription,
       CASE WHEN i.oid IS NOT NULL THEN 'INSTRUMENT' WHEN s.oid IS NOT NULL THEN 'SPECIALTY' END TagKind
INTO #tag
FROM #cat c
JOIN dbo.CORERelationOrigin r ON c.catdb='MDB' AND r.oid = c.catoid AND r.RelationType = @MatCtlForComp
LEFT JOIN dbo.REFDATInstrumentClass i ON i.oid = r.oidTarget
LEFT JOIN dbo.REFDATPipingSpecialtyClass s ON s.oid = r.oidTarget;

/* 3. material control data (commodity code, material description) via proxy */
SELECT p.part, md.ContractorCommodityCode, md.ShortMaterialDescription
INTO #mat
FROM #parts p
JOIN dbo.CORERelationOrigin mc ON mc.oid = p.part AND mc.RelationType = @MatCtl
JOIN dbo.CORERelationOrigin po ON po.oidTarget = mc.oidTarget AND po.RelationType = @ProxyOwner AND po.oid IN (SELECT oid FROM dbo.CORESite)
JOIN [MLNG@1_CDB].dbo.CORENamedObjects cno ON cno.ObjectName = po.RelationName
JOIN [MLNG@1_CDB].dbo.REFDATCommodityMatlCtrlData md ON md.oid = cno.ObjectOid;

/* 4. end points: every port of every part, with the distribution connection it sits on.
      pipes own real ROUTEPipePort rows; fittings own reference proxies named PNoz1..n / Nozzle1..n (trailing digits = catalog PortIndex) */
SELECT p.part, dp.oidTarget AS port,
       COALESCE(pp.PortIndex, TRY_CAST(RIGHT(pn.RelationName, PATINDEX('%[^0-9]%', REVERSE(pn.RelationName) + 'x') - 1) AS int)) AS PortIndex,  -- 'PNoz2'/'Nozzle2' -> 2
       conn.oid AS conn, dc.ConnectionType,
       COALESCE(pp.PlacePointX, dc.LocationX) X, COALESCE(pp.PlacePointY, dc.LocationY) Y, COALESCE(pp.PlacePointZ, dc.LocationZ) Z,
       pp.NPD, pp.NPDUnitType, pp.PipingOutsideDiameter OD, pp.WallThicknessOrGrooveSetback WallThk, pp.ScheduleThickness, pp.EndPreparation
INTO #ends
FROM #parts p
JOIN dbo.CORERelationOrigin dp ON dp.oid = p.part AND dp.RelationType = @DistribPorts
LEFT JOIN dbo.ROUTEPipePort pp ON pp.oid = dp.oidTarget
LEFT JOIN dbo.CORERelationOrigin pn ON pn.oidTarget = dp.oidTarget AND pn.RelationType = @ProxyOwner AND pp.oid IS NULL
LEFT JOIN dbo.CORERelationOrigin conn ON conn.oidTarget = dp.oidTarget AND conn.RelationType = @FlowPorts
LEFT JOIN dbo.ROUTEDistribConnection dc ON dc.oid = conn.oid;

/* 5. generating path feature (centre point, bend data) */
SELECT p.part, f.oid AS feat, b.ClassId featcls,
       COALESCE(t.LocationX, br.LocationX, s.LocationX, a.LocationX, e.LocationX) CPX,
       COALESCE(t.LocationY, br.LocationY, s.LocationY, a.LocationY, e.LocationY) CPY,
       COALESCE(t.LocationZ, br.LocationZ, s.LocationZ, a.LocationZ, e.LocationZ) CPZ,
       t.BendAngle, t.BendRadius, t.TurnType,
       COALESCE(t.NomDiam, br.NomDiam, s.NomDiam, a.NomDiam, e.NomDiam) NomDiam,
       COALESCE(t.NPDUnitType, br.NPDUnitType, s.NPDUnitType, a.NPDUnitType, e.NPDUnitType) NPDUnit,
       COALESCE(t.OuterDiameter, br.OuterDiameter, s.OuterDiameter, a.OuterDiameter, e.OuterDiameter) FeatOD,
       COALESCE(t.ShortCode, br.ShortCode, s.ShortCode, a.ShortCode, e.ShortCode) FeatShortCode,
       COALESCE(t.Tag, br.Tag, s.Tag, a.Tag, e.Tag) Tag
INTO #feat
FROM #parts p
JOIN dbo.CORERelationOrigin f ON f.oidTarget = p.part AND f.RelationType = @PathGenParts
JOIN dbo.COREBaseClass b ON b.oid = f.oid
LEFT JOIN dbo.ROUTEPipeTurnPathFeat t     ON t.oid = f.oid
LEFT JOIN dbo.ROUTEPipeBranchPathFeat br  ON br.oid = f.oid
LEFT JOIN dbo.ROUTEPipeStraightPathFeat s ON s.oid = f.oid
LEFT JOIN dbo.ROUTEPipeAlongLegPathFeat a ON a.oid = f.oid
LEFT JOIN dbo.ROUTEPipeEndPathFeat e      ON e.oid = f.oid;

/* 6. ordering: iterative BFS (hop count) from a run end = part with <=1 in-run neighbour */
SELECT DISTINCT e1.part a, e2.part b INTO #adj
FROM #ends e1 JOIN #ends e2 ON e2.conn = e1.conn AND e2.part <> e1.part
JOIN #parts p1 ON p1.part = e1.part JOIN #parts p2 ON p2.part = e2.part AND p2.run = p1.run;
CREATE TABLE #ord (part uniqueidentifier PRIMARY KEY, hop int);
INSERT #ord (part, hop)
SELECT CAST(MIN(CAST(p.part AS char(36))) AS uniqueidentifier), 0
FROM #parts p WHERE (SELECT COUNT(*) FROM #adj WHERE a = p.part) <= 1 GROUP BY p.run;
DECLARE @h int = 0;
WHILE @h < 5000
BEGIN
  INSERT #ord (part, hop)
  SELECT DISTINCT j.b, @h + 1 FROM #ord o JOIN #adj j ON j.a = o.part
  WHERE o.hop = @h AND NOT EXISTS (SELECT 1 FROM #ord x WHERE x.part = j.b);
  IF @@ROWCOUNT = 0 BREAK;
  SET @h += 1;
END;

/* 7. final component list */
SELECT
  pln.strName AS LineNumber, rn.strName AS PipeRun, CAST(p.part AS char(36)) AS PartOid, pn.strName AS PartName,
  COALESCE(o.hop, 9999) AS SeqInRun, j.TableName AS OccTable,
  COALESCE(sk.PCFComponentID, CASE p.cls WHEN 80012 THEN 'PIPE' WHEN 80054 THEN 'INSTRUMENT' WHEN 80055 THEN 'MISC-COMPONENT' ELSE 'MISC-COMPONENT' END) AS PCFType,
  sk.SKEY AS SKEY_Type, ct.ShortStringValue AS CommodityType, cc.ShortStringValue AS CommodityClass, cp.PartClass,
  COALESCE(mt.ContractorCommodityCode, tg.TagCommodityCode, cp.IndustryCommodityCode) AS ItemCode, cp.PartNumber, tg.TagNumber,
  COALESCE(mt.ShortMaterialDescription, tg.TagDescription, oc.ShortMaterialDescription, po.ShortMaterialDescription) AS Description,
  mg.ShortStringValue AS Material,
  cp.PrimarySize, cp.SecondarySize, cp.PriUnits, s1.ShortStringValue Sched1, s2.ShortStringValue Sched2,
  f.FeatOD, f.BendRadius, f.BendAngle * 180.0 / PI() AS BendAngleDeg, po.PipeLength,
  e1.X EP1X, e1.Y EP1Y, e1.Z EP1Z, e2.X EP2X, e2.Y EP2Y, e2.Z EP2Z, e3.X EP3X, e3.Y EP3Y, e3.Z EP3Z,
  f.CPX, f.CPY, f.CPZ,
  COALESCE(e1.WallThk, e2.WallThk) WallThk, COALESCE(e1.OD, e2.OD, f.FeatOD) OD, ep1.ShortStringValue EndPrep1, pr1.ShortStringValue Rating1, ct1.ShortStringValue Conn1, ct2.ShortStringValue Conn2
FROM #parts p
JOIN dbo.COREJPOSchema j ON j.class_id = p.cls
LEFT JOIN dbo.CORENamedItem pln ON pln.oid = @pl
LEFT JOIN dbo.CORENamedItem rn  ON rn.oid = p.run
LEFT JOIN dbo.CORENamedItem pn  ON pn.oid = p.part
LEFT JOIN #ord o  ON o.part = p.part
LEFT JOIN #catp cp ON cp.part = p.part
LEFT JOIN #mat mt ON mt.part = p.part
LEFT JOIN dbo.ROUTEPipeComponentOcc oc ON oc.oid = p.part
LEFT JOIN dbo.ROUTEPipeOccur po        ON po.oid = p.part
OUTER APPLY (SELECT TOP 1 * FROM #feat f WHERE f.part = p.part ORDER BY CASE WHEN f.BendAngle IS NOT NULL THEN 0 WHEN f.featcls=80035 THEN 1 ELSE 2 END) f
OUTER APPLY (SELECT TOP 1 * FROM #ends e WHERE e.part = p.part AND e.PortIndex = 1 ORDER BY e.conn DESC) e1
OUTER APPLY (SELECT TOP 1 * FROM #ends e WHERE e.part = p.part AND e.PortIndex = 2 ORDER BY e.conn DESC) e2
OUTER APPLY (SELECT TOP 1 * FROM #ends e WHERE e.part = p.part AND e.PortIndex = 3 ORDER BY e.conn DESC) e3
OUTER APPLY (SELECT TOP 1 c1.EndPrep FROM #cport c1 WHERE c1.part = p.part ORDER BY c1.PortIndex) cpe
OUTER APPLY (SELECT TOP 1 m0.SKEY, m0.PCFComponentID
             FROM [MLNG@1_CDB].dbo.REFDATPipeMfgMapSymbol m0
             LEFT JOIN [MLNG@1_CDB].dbo.REFDATPipeMfgMapSymbol m2 ON m2.MapType = 2 AND m2.CodeList = cpe.EndPrep
             WHERE m0.MapType = 0 AND m0.PartClassName = cp.PartClass
             ORDER BY CASE WHEN RIGHT(m0.SKEY, 2) = m2.SKEY THEN 0 ELSE 1 END, m0.oid) sk
LEFT JOIN #tag tg ON tg.part = p.part
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ct  ON ct.TableName='PipingCommodityType' AND ct.ValueID = cp.CommodityType
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView mg  ON mg.TableName='MaterialsGrade'      AND mg.ValueID = cp.MaterialGrade
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView cc  ON cc.TableName='PipingCommodityClass' AND cc.ValueID = cp.CommodityClass
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView s1  ON s1.TableName='ScheduleThickness'   AND s1.ValueID = cp.Sched1
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView s2  ON s2.TableName='ScheduleThickness'   AND s2.ValueID = cp.Sched2
OUTER APPLY (SELECT TOP 1 c1.PressureRating, c1.EndPrep FROM #cport c1 WHERE c1.part = p.part AND c1.PortIndex = 1) cp1
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ep1 ON ep1.TableName='EndPreparation'     AND ep1.ValueID = COALESCE(e1.EndPreparation, cp1.EndPrep)
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView pr1 ON pr1.TableName='PressureRating'     AND pr1.ValueID = cp1.PressureRating
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ct1 ON ct1.TableName='ConnectionType'     AND ct1.ValueID = e1.ConnectionType
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ct2 ON ct2.TableName='ConnectionType'     AND ct2.ValueID = e2.ConnectionType
ORDER BY rn.strName, COALESCE(o.hop, 9999), pn.strName;
