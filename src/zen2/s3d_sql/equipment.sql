/* Equipment without blobs: placement matrix, bbox, catalog class, system, nozzles, primitive shapes.
   Run in MLNG@1_MDB. $(TOPN) = sample size. */
SET NOCOUNT ON;
DECLARE @HasEqpAsChild uniqueidentifier='795C63BB-2BB5-480D-AE62-FE999C446645',  -- System -> Equipment
        @SOtoSI        uniqueidentifier='A3B0F642-C087-4C77-A64B-23D322ED5C37',  -- Equipment -> model-resident part (REFDATSmartEquipmentPartVirtual)
        @PartClassParts uniqueidentifier='7FAA6155-07BE-11D2-BC6B-0800360DCD02',
        @DistribPorts  uniqueidentifier='BFE914B5-978E-11D3-BFF3-080036B8A403',  -- Equipment -> nozzle (RelationName = nozzle label)
        @HasShapes     uniqueidentifier='B6BBA674-B690-422F-9471-0F50934271F8',  -- Equipment -> EQUIPShape
        @ShapeDefinedFrom uniqueidentifier='80E8EAB6-2D26-44C4-ACCF-1F13DDE339F4',-- EQUIPShape -> catalog shape proxy
        @ProxyOwner    uniqueidentifier='5280312B-E69C-11D1-A966-080036069A02';

SELECT TOP ($(TOPN)) e.oid INTO #eq FROM dbo.EQUIPSmartEquipment e
WHERE EXISTS (SELECT 1 FROM dbo.CORERelationOrigin r WHERE r.oid = e.oid AND r.RelationType = @DistribPorts)
ORDER BY e.oid;

/* A. equipment header */
SELECT CAST(e.oid AS char(36)) Equipment, n.strName, sysn.strName ParentSystem, pcn.RelationName CatalogPartClass,
       m.o0 PosX, m.o1 PosY, m.o2 PosZ, m.x0 XAxisX, m.x1 XAxisY, m.x2 XAxisZ, m.z0 ZAxisX, m.z1 ZAxisY, m.z2 ZAxisZ,
       si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax,
       (SELECT COUNT(*) FROM dbo.CORERelationOrigin r WHERE r.oid=e.oid AND r.RelationType=@HasShapes) nShapes,
       (SELECT COUNT(*) FROM dbo.CORERelationOrigin r WHERE r.oid=e.oid AND r.RelationType=@DistribPorts) nNozzles
FROM #eq q JOIN dbo.JEquipment m ON m.oid = q.oid
JOIN dbo.EQUIPSmartEquipment e ON e.oid = q.oid
LEFT JOIN dbo.CORENamedItem n ON n.oid = e.oid
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = e.oid
OUTER APPLY (SELECT TOP 1 sn.strName FROM dbo.CORERelationOrigin r JOIN dbo.CORENamedItem sn ON sn.oid = r.oid
             WHERE r.oidTarget = e.oid AND r.RelationType = @HasEqpAsChild) sysn
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin s
             JOIN dbo.CORERelationOrigin pc ON pc.oidTarget = s.oidTarget AND pc.RelationType = @PartClassParts
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = pc.oid AND po.RelationType = @ProxyOwner
             WHERE s.oid = e.oid AND s.RelationType = @SOtoSI) pcn;

/* B. nozzles (global coordinates) */
SELECT CAST(r.oid AS char(36)) Equipment, r.RelationName NozzleLabel, z.dNPD NPD, z.strNPDUnitType NPDUnit,
       ep.ShortStringValue EndPrep, pr.ShortStringValue Rating,
       z.gposPlacePointX X, z.gposPlacePointY Y, z.gposPlacePointZ Z,
       z.gvecOrientationX DX, z.gvecOrientationY DY, z.gvecOrientationZ DZ,
       z.dPipingOutsideDiameter OD, z.dFlangeOrHubOutsideDiameter FlangeOD, z.dFlangeOrHubThickness FlangeThk, z.dLength NozzleLength
FROM #eq q JOIN dbo.CORERelationOrigin r ON r.oid = q.oid AND r.RelationType = @DistribPorts
JOIN dbo.EQUIPPipeNozzle z ON z.oid = r.oidTarget
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ep ON ep.TableName='EndPreparation' AND ep.ValueID = z.lEndPrep
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView pr ON pr.TableName='PressureRating' AND pr.ValueID = z.lPressureRating;

/* C. primitive shapes: catalog shape name + parameters (m / rad) + placement matrix from CORESymbol */
SELECT CAST(q.oid AS char(36)) Equipment, CAST(h.oidTarget AS char(36)) Shape, sp.RelationName ShapeType,
       prm.Params, s.ServerToClient12 OX, s.ServerToClient13 OY, s.ServerToClient14 OZ,
       s.ServerToClient0 m0, s.ServerToClient1 m1, s.ServerToClient2 m2, s.ServerToClient8 m8, s.ServerToClient9 m9, s.ServerToClient10 m10
FROM #eq q JOIN dbo.CORERelationOrigin h ON h.oid = q.oid AND h.RelationType = @HasShapes
LEFT JOIN dbo.CORESymbol s ON s.oid = h.oidTarget
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin d
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = d.oidTarget AND po.RelationType = @ProxyOwner
             WHERE d.oid = h.oidTarget AND d.RelationType = @ShapeDefinedFrom) sp
OUTER APPLY (SELECT STRING_AGG(pn.Name + '=' + CAST(CAST(a.value AS decimal(12,4)) AS varchar(20)), ' ') Params
             FROM dbo.COREDoubleAttribute a
             JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceDef idf ON idf.IID = a.iid
             JOIN [MLNG@1_CDB_SCHEMA].dbo.JInterface_Has_JMembers jm ON jm.oidOrg = idf.oid
             JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceMember im ON im.oid = jm.oidDst AND im.DispatchID = a.dispid
             JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject pn ON pn.oid = jm.oidDst
             WHERE a.oid = h.oidTarget) prm
ORDER BY 1, 3;
