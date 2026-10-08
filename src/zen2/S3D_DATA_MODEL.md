# S3D v13 (MLNG@1) — licence-free data-model mapping for geometry / PCF / JSON extraction

Status: research complete, all SQL below was executed read-only against the restored databases on
`i-02c20241cf997b48d` (SQL Server 2022, Linux) on 2026-09-29. Only SELECT and temp tables in tempdb were used.
Raw outputs are in `s3://annotationprod/cad-disk-extract/zenitude-data-2/db/s3dmap/`, and the runnable SQL files are in
`/Users/dhiren/Downloads/Deccan/zen2/s3d_sql/`.

## 0. TL;DR

* **You can reconstruct almost everything from plain columns. Nothing needs an S3D licence.** Every business object
  row has global coordinates in metres (ports, path features, connections, member axes, nozzle points, placement matrices).
  Catalog dimensions sit in the catalog DB as typed columns plus generic attribute tables. All names come from the
  `*_SCHEMA` metadata.
* **How relations are stored:** `CORERelationOrigin(oid → oidTarget, RelationType GUID, RelationName)`. The GUID maps to a
  relation name in `MLNG@1_CDB_SCHEMA.dbo.RelationInfoView`. The MDB `X*` views are one-line filters on it.
  The first 4 bytes of every OID hold the **class id** (for example `0001388C-…` = 80012 = `ROUTEPipeOccur`).
* **How model objects point at the catalog:** relations in the model point at a `COREProxy`. The proxy's
  `ProxyOwner` row (owner = the `CORESite` with moniker `catalog{d11ba59e…}`) stores the catalog object's **moniker name**
  in `RelationName`. That name is the unique key of `MLNG@1_CDB.dbo.CORENamedObjects.ObjectName`, which gives the catalog oid.
  99.3 % of catalog proxies resolve, and only 298 of 1.95 M part occurrences don't.
* **Piping:** the chain pipeline → runs → parts → ports/connections is fully relational. Pipes have real port rows.
  Fittings have **reference-proxy ports** (`PNoz1..n` / `Nozzle1..n`), whose coordinates come from the
  `ROUTEDistribConnection.Location` each port sits on. Turn/branch path features give CENTRE-POINT, bend radius and angle.
  One query returns a PCF-ready list in under 1 s per pipeline (section 3).
* **Structure:** member axis (start/end), roll angle (`betaAngle`), cardinal point, and a section moniker such as
  `AISC-LRFD-3.1, W, W6X25` that resolves to catalog dimensions (d, bf, tf, tw, tnom …, in m). This gives exact prismatic
  extrusions. End cuts/copes exist only in ACIS solids.
* **Equipment:** placement matrix, bbox, nozzles (global point, direction, NPD, flange OD/thk) and **132 838 primitive
  shapes** (box/cylinder/cone/head/torus … with A–E parameters plus a 4×4 matrix in `CORESymbol`).
* **Blobs:** GEOTOP bodies and compressed graphic caches are a **ZIP central-directory-style header + Deflate64
  (method 9)** stream. Decompressed, each is an **OLE2 compound file**. Its stream `JS_TOPOLOGY_STREAM` is
  **ACIS SAB 23.0** (`"ACIS BinaryFile"`, product `Intergraph S3D v2013`, 1 unit = 1000 mm). Uncompressed
  `COREGraphicDataCache` blobs use a small custom primitive format (for example cylinder base point + axis + radius).
* **Coverage:** about **56 %** of physical objects are exact from columns (pipes, linear members, nozzles). About **34 %**
  are good parametric reconstructions (fittings, valves, instruments, equipment shapes). About **10 %** need approximation or
  ACIS decoding (supports, curved members, slabs, footings, cable trays).

---

## 1. Relationship model

### 1.1 Core tables (MDB)

| table | rows | role |
|---|---|---|
| `COREBaseClass(oid, ClassId, persistentFlag, …)` | 51.8 M | one row per object; `ClassId` → `COREJPOSchema.class_id` |
| `CORERelationOrigin(RelationKey, oid, oidTarget, RelationType, RelationName, Predecessor, RelationOid, RelationProperties)` | 97.4 M | all relations except 5 "simple" types |
| `CORESimpleRelationOrigin` (same columns) | 4.9 M | `EntityNamingRule` (4.8 M), `TypeRel`, `ViewHasCoordSys`, `ProxyStopperToSiteProxy`, `BelongsToProject` |
| `CORENamedItem(oid, strName)` | 9.1 M | object names (line numbers, run names, member names …) |
| `CORESpatialIndex(oid, xmin..zmax)` | 12.6 M | float32 world bbox |
| `COREDoubleAttribute / CORELongAttribute / COREBstrAttribute / COREBoolAttribute (oid, iid, dispid, value)` | 7.0 M / 25.2 M / 1.3 M / 0.5 M | generic (user/catalog-class) properties |
| `CORESymbol(oid, …, ServerToClient0..15)` | 4.8 M | **4×4 placement matrix** (row-major, translation in 12..14) of every symbol occurrence: pipe components, nozzles, equipment shapes, hanger parts, frame connections … |
| `COREJPOSchema(class_id, JPOClsid, BOClsid, TableName)` | 1 101 | class id → CLSID → class name |

Indexes (checked in `sys.indexes`):
* `pk_CORERelationOrigin` is clustered on `(oid, RelationType, oidTarget, RelationKey)`, so seeks from the origin are cheap.
* `CORERelationDestinationIndex` is on `(oidTarget)` and INCLUDEs every other column, so seeks from the target are cheap.
* `CORERelationOriginTypeIndex` is on `(RelationType)` and covers the clustering key, so a whole relation type can be scanned cheaply.

Every query below uses only seeks on these indexes. The full `GROUP BY RelationType` histogram took 1 m 44 s. Run it once only.

**OID layout.** `CAST(oid AS char(36))` → `XXXXXXXX-0000-0000-…`. The first 8 hex digits are the class id:
* `00033457` = 210007 `SHPCONPipelineSystem`
* `0001388D` = 80013 `ROUTEPipeRun`
* `00013885` = 80005 `ROUTEPipeComponentOcc`
* `0001388C` = 80012 `ROUTEPipeOccur`
* `0001388E` = 80014 `ROUTEPipePort`
* `00000008` = COREProxy, `00000009` = COREReferenceProxy, `0000000C` = CORESite
* `0003A98C` = 240012 `STRUCTMemberPartPris`
* `00004E2E` = 20014 `EQUIPSmartEquipment`
* `0000EA74` = 60020 `REFDATPipeComponent`

`LEFT(CAST(oid AS char(36)),8)` is therefore a class filter that needs no join. The GUID sort order is not class-contiguous, so it can't be used as a range seek.

**`persistentFlag & 1024`** marks owned, internal objects: symbol outputs, cached geometry (all GEOTOP bodies,
417 k of the 456 k `EQUIPPipeNozzle` rows, which sit in symbol-local coordinates), projections and so on. Most S3D J-views filter
`persistentFlag & 1024 = 0`. Do the same for business objects.

### 1.2 Resolving class ids and relation GUIDs to names (via `MLNG@1_CDB_SCHEMA`)

The model uses the catalog schema DB. The SDB_SCHEMA is identical and there is no MDB_SCHEMA. `PRJMGTDatabase` in the SDB
confirms `Model … PMSchema = MLNG@1_CDB_SCHEMA`.

```sql
-- class id -> table / class name
SELECT j.class_id, j.TableName, c.Name AS ClassName, c.DBViewName
FROM [MLNG@1_MDB].dbo.COREJPOSchema j
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.ClassInfoView c ON c.CLSID = j.BOClsid
ORDER BY j.class_id;

-- relation GUID -> relation name, collection names (origin collection name is the collection ON the origin object)
SELECT RelationGUID, RelationName, DBViewName, OriginCollectionName, DestinationCollectionName
FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView;

-- object histogram (uses COREBaseClassClassIdIndex; ~30 s)
SELECT ClassId, persistentFlag, COUNT_BIG(*) n
FROM dbo.COREBaseClass WITH (INDEX(COREBaseClassClassIdIndex)) GROUP BY ClassId, persistentFlag;

-- relation histogram (uses CORERelationOriginTypeIndex; 1 m 44 s, run once)
SELECT RelationType, COUNT_BIG(*) n FROM dbo.CORERelationOrigin WITH (INDEX(CORERelationOriginTypeIndex))
GROUP BY RelationType OPTION (MAXDOP 4);
```

All 285 relation types present resolve to names. Largest (sample):

| RelationName | rows | | RelationName | rows |
|---|---|---|---|---|
| ProxyOwner | 5 095 653 | | PathGeneratedParts | 1 955 427 |
| DistribPorts | 3 685 646 | | madeFrom | 1 951 981 |
| FlowPorts | 3 159 040 | | OwnsParts | 1 758 793 |
| RelConnectionAndPartOcc | 3 159 027 | | PartOccToMaterialControlData | 1 758 755 |
| AlongLeg | 3 054 411 | | OwnsDistributionConnection | 1 579 530 |
| PathSpecification | 2 784 175 | | SPSMemberToCrossSectionRln | 924 320 |
| SPSPartHasPortsRln | 2 772 960 | | SystemHierarchy | 732 244 |

Several relations that the view names suggest are **empty in this model**:
`PipelineToPipeRun`, `PipeRunToPipePart`, `PathRunFeatures`, `HasPorts`, `EquipmentNozzle`, `NozzleToEquipment`.
The model uses `SystemHierarchy`, `OwnsParts`, `PathSpecification`, `DistribPorts` and `AssemblyHierarchy` instead.

**Direction convention.** Verified on data. The row's `oid` is the object that *owns the origin collection*. For
`SystemHierarchy` (origin collection `SystemChildren`), `oid` = parent system and `oidTarget` = child.

### 1.3 Generic attributes and codelists

```sql
-- all generic properties of one object with interface/property names (tool_attributes.sql; run in MDB or CDB)
WITH a AS (SELECT iid, dispid, CAST(value AS nvarchar(200)) v, 'D' t FROM dbo.COREDoubleAttribute WHERE oid=@o
 UNION ALL SELECT iid, dispid, CAST(value AS nvarchar(200)), 'L' FROM dbo.CORELongAttribute WHERE oid=@o
 UNION ALL SELECT iid, dispid, CAST(value AS nvarchar(200)), 'S' FROM dbo.COREBstrAttribute WHERE oid=@o
 UNION ALL SELECT iid, dispid, CAST(value AS nvarchar(200)), 'B' FROM dbo.COREBoolAttribute WHERE oid=@o)
SELECT a.t, ifn.Name iface, pn.Name prop, a.v
FROM a
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceDef id ON id.IID=a.iid
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject ifn ON ifn.oid=id.oid
OUTER APPLY (SELECT TOP 1 pn.Name FROM [MLNG@1_CDB_SCHEMA].dbo.JInterface_Has_JMembers m
             JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceMember im ON im.oid=m.oidDst AND im.DispatchID=a.dispid
             JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject pn ON pn.oid=m.oidDst WHERE m.oidOrg=id.oid) pn;

-- codelist decode
SELECT ValueID, ShortStringValue, LongStringValue FROM [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView
WHERE TableName = 'PipingCommodityType';     -- also EndPreparation, ScheduleThickness, PressureRating, MaterialsGrade,
                                             -- ConnectionType, WeldType, StructuralMemberType(Category), GeometryType, PipingCommodityClass
```
The property → codelist link is `AttributeInfoView.CodeListTableOID`. Sample decodes:
* PipingCommodityType 1405 = `E90LR` (90° elbow, long radius)
* EndPreparation 301 = `BE`, 21 = `RFFE`
* ScheduleThickness 100 = `S-STD`
* ConnectionType 1 = Bolted, 3 = Welded
* StructuralMemberTypeCategory 1 = Beam, 2 = Column, 3 = Brace, 6 = Handrail Element

Sample: the catalog elbow `E90LR_AEA_AAE_S80_BES-80S-805050` has `IJFaceToCenter.FacetoCenter = 0.076` and
`IJUABendAngle.BendAngle = 1.5708`. An instrument occurrence carries `IJFaceToFace.FacetoFace = 0.6`,
`IJDynamicPipePort1.EndPreparation1 = 21`, `Npd1 = 100 mm` and `IJUAInstrumentActuator.ActuatorDiameter = 0.4`.

### 1.4 Cross-database references (model → catalog): proxies

```sql
-- proxy -> catalog oid  (99.3 % of 83 953 catalog proxies resolve; 298 / 1.95 M madeFrom occurrences unresolved)
SELECT r.oidTarget AS proxy, CAST(s.ObjectMoniker AS nvarchar(100)) AS site, r.RelationName AS moniker, c.ObjectOid AS catalog_oid
FROM [MLNG@1_MDB].dbo.CORERelationOrigin r
JOIN [MLNG@1_MDB].dbo.CORESite s ON s.oid = r.oid                 -- ObjectMoniker = 'catalog{d11ba59e-…}' (UTF-16 in varbinary)
LEFT JOIN [MLNG@1_CDB].dbo.CORENamedObjects c ON c.ObjectName = r.RelationName   -- ObjectName is the PK (unique)
WHERE r.RelationType = '5280312B-E69C-11D1-A966-080036069A02'     -- ProxyOwner
  AND r.oidTarget = @proxy;
```
Observed monikers:
* part: `E90LR_AEA_AAE_S80_BES-80S-805050`
* cross-section: `AISC-LRFD-3.1, L, L2-1/2X2X1/4`
* material: `Steel - Carbon-A`
* hanger assembly: `Assy_SH_CL_6`
* equipment shape: `RtCircularCylinder 001`

A few monikers are `{catalog-oid}`. For those, cast the text to a uniqueidentifier and look it up in CDB `COREBaseClass`.
The site `pdsforeigndatamodel{6354aeea…}` (7 761 proxies) is the model's own foreign/PDS data and does not resolve in the CDB.
Reference-proxy *ports* of fittings (`COREReferenceProxy`) are owned (ProxyOwner) by a holder proxy named `Physical`,
and their `RelationName` is the symbol port name (`PNoz1`, `PNoz2`, `Nozzle3` …). The trailing digits are the catalog `PortIndex`.

Instrument and specialty parts are **model-resident**. `madeFrom` points at MDB `REFDATPipeComponent` (0000EA74…), which points
via `DefinesMaterialControlDataForComponent` at `REFDATInstrumentClass` / `REFDATPipingSpecialtyClass`. Their part class
is again a catalog proxy.

### 1.5 The chains (relation GUID, direction origin → target)

**Piping**
```
SHPCONPipingSystem ─SystemHierarchy(A8CE36E7-A53F-4558-8DF9-F0BCE6583327)→ SHPCONPipelineSystem (name = line number)
SHPCONPipelineSystem ─SystemHierarchy→ ROUTEPipeRun            (also SystemHasSupport F2B9B39A-… → HNGSUPHgrPipeSupport)
ROUTEPipeRun ─OwnsParts(3C9A3EEE-3F54-441F-A3D4-DCFC4615E88D)→ ROUTEPipeOccur | ROUTEPipeComponentOcc | ROUTEPipeInstrumentOcc | ROUTEPipeSpecialtyOcc
ROUTEPipeRun ─PathSpecification(34DE4F55-7853-4540-846F-2FA80CCF8B5F)→ ROUTEPipe{Straight,Turn,Branch,AlongLeg,End}PathFeat
ROUTEPipeRun ─OwnsDistributionConnection(67E1D32D-38B0-4885-8F1A-784627305608)→ ROUTEDistribConnection (LocationX/Y/Z, ConnectionType)
ROUTEPipeRun ─PathRunUsesSpec(A53D19B6-…)→ COREProxy (pipe spec)
path feature ─PathGeneratedParts(C9820593-3838-11D2-BE94-080036B8A403)→ part
path leg (ROUTEPathLeg) ─AlongLeg(B075C7A3-…)→ feature
part ─DistribPorts(BFE914B5-978E-11D3-BFF3-080036B8A403)→ ROUTEPipePort (pipes) | COREReferenceProxy 'PNozN' (fittings) | EQUIPPipeNozzle (equipment)
ROUTEDistribConnection ─FlowPorts(42188F92-332B-11D4-93F0-080036B9BD03)→ the 2 ports it joins
ROUTEDistribConnection ─RelConnectionAndPartOcc(71EEA3EB-F909-48B8-92A3-E04ED3E6E780)→ the 2 parts it joins
ROUTEDistribConnection ─GeneratesConnectionItems(95A02A64-195B-46D4-BE9E-2A4A15A9F90D)→ ROUTEPipeWeld | ROUTEPipeGasket | ROUTEPipeBoltSet
part ─OwnsImpliedItems(4C06EC05-…)→ weld/gasket/bolt set
part ─madeFrom(B0E39EC4-0141-11D2-8FF2-080036E94503)→ COREProxy (catalog part)   | MDB REFDATPipeComponent for instruments/specialties
part ─PartOccToMaterialControlData(ED1D6AE6-1E81-42F7-A101-D79DD9F18096)→ COREProxy (REFDATCommodityMatlCtrlData: commodity code, description)
```
**Catalog (run in MLNG@1_CDB)**
```
REFDATPartClass ─PartClassContainsParts(7FAA6155-07BE-11D2-BC6B-0800360DCD02)→ REFDATPipeComponent (PartNumber, IndustryCommodityCode, CommodityType,
                                                  GeometryType, PrimarySize/SecondarySize, schedules, FirstSize/SecondSizeOutsideDiameter, BendRadius, MaterialGrade)
REFDATPipeComponent ─PartContainsNozzles(F6AD318F-4BE0-11D2-BC7F-0800360DCD02)→ REFDATPipePort (PortIndex, Npd, EndPrep, PressureRating, ScheduleThickness)
REFDATPipeComponent ─DefinesMaterialControlDataForComponent(33F05030-…)→ REFDATCommodityMatlCtrlData
class-specific dimensions (FacetoCenter, FacetoFace, …) → COREDoubleAttribute of the part oid (names via schema, section 1.3)
SKEY / PCF type: REFDATPipeMfgMapSymbol (MapType 0: PartClassName → SKEY, PCFComponentID; MapType 2: EndPreparation → end suffix FL/BW/SW…)
```
**Structure**
```
SHPCONStructuralSystem ─SPSMemberSystemSysParentRln(07F5F6E2-8377-4F1B-93A2-3CB33D95F87F)→ STRUCTMemberSysLinear (logical member, StartX..EndZ, rotationAngle)
STRUCTMemberSysLinear ─SPSMemberDesignParentRln(E679D79A-0661-4802-990C-7DC0B8799D06)→ STRUCTMemberPartPris (typeCategory, type, cutLength, weight)
STRUCTMemberSysLinear ─StructSplitResult(A39F5A5C-…)→ STRUCTMemberPartAxisLin (startx..endz, betaAngle, OVector, mirror)
STRUCTPartPrismaticGen (cardinalPoint) ─SPSMemberToCrossSectionRln(11E4BF30-95B6-4996-82FE-5CEDABBC5359)→ STRUCTMemberPartPris
STRUCTPartPrismaticGen ─StructOperand(93F52989-9504-11D4-9D40-00105AA5BAEB)→ STRUCTMemberPartAxisLin
STRUCTPartPrismaticGen ─SPSDefinitionCrossSectionRln(A1471E95-F9E0-409F-8BCB-6B2AF3132017)→ COREProxy (catalog CPCrossSection, class 60035)
STRUCTPartPrismaticGen ─StructEntityMaterial(78A872D0-953C-11D4-9D40-00105AA5BAEB)→ COREProxy (material)
STRUCTPartPrismaticGen ─StructResult→ CMemberGeometry (240007) → GEOTOPSolidBody (ACIS solid with end cuts)
```
**Equipment**
```
SHPCON*System ─HasEqpAsChild(795C63BB-2BB5-480D-AE62-FE999C446645)→ EQUIPSmartEquipment (matrix in JEquipment / CORESymbol)
EQUIPSmartEquipment ─DistribPorts (RelationName = nozzle label 'N1') / AssemblyHierarchy(017E453B-…)→ EQUIPPipeNozzle (global point, direction, NPD, flange)
EQUIPSmartEquipment ─HasShapes(B6BBA674-B690-422F-9471-0F50934271F8)→ EQUIPShape ─ShapeDefinedFrom(80E8EAB6-…)→ COREProxy ('RtCircularCylinder 001' …)
EQUIPSmartEquipment ─SOtoSI_R(A3B0F642-…)→ REFDATSmartEquipmentPartVirtual ─PartClassContainsParts← COREProxy (catalog class, e.g. 'StorageTankAsm')
EQUIPSmartEquipment ─HasCSystem(D7683A21-…)→ GRDSYSSPGCoordinateSystem
```
**Supports**: `HNGSUPHgrPipeSupport` ─SupportHasComponents→ `HNGSUPHgrStdComponent` / `HgrConnComponent`
(CG + CORESymbol matrix). ─SupportHasCS→ `GRDSYSSPGCoordinateSystem` (origin `o0,o1,o2` = point on the pipe centreline).
─OccAssyHasPart→ proxy (catalog assembly). ─ConnHasPorts→ the supported path feature.

### 1.6 Report-style views

* MDB has 15 266 views: 6 894 `J*` (interface views), 4 036 `C*`, 1 393 `X*` (relation views), 1 294 `E*`, 958 `S*` (Smart-Interop), 478 `R*`.
  * **X views** are literally `SELECT oid, oidTarget, RelationName FROM CORERelationOrigin WHERE RelationType='…'`. 1 374 read CORERelationOrigin and 12 read the simple table.
  * **J views** are UNION ALLs over the base tables plus the `persistentFlag & 1024 = 0` filter. Examples: `JDistribPort` (all port types with PlacePoint/orientation), `JRtePipePathFeat`, `JEquipment` (4×4 matrix), `JPipelineSystem`, `JDPipeComponent`.
* No view flattens a BOM or isometric data. The Reports DB (`MLNG@1_RDB`, listed in SDB `PRJMGTDatabase`) was not supplied.
* The queries below therefore join base tables directly. That is equivalent to the J/X views and avoids their UNION overhead.

---

## 2. Units and coordinate frame

* **All lengths are metres, angles are radians, weights kg.** NPD is stored with its own unit column (`NPDUnitType` = `mm`/`in`).
  * 4" pipe: `PipingOutsideDiameter = 0.1143` and `WallThicknessOrGrooveSetback = 0.006020` (4" Sch40 = 6.02 mm).
  * 4" LR elbow: turn feature `BendRadius = 0.152` (1.5 D).
  * 2" LR elbow catalog: `FacetoCenter = 0.076`.
  * W6X25 catalog: d = 0.162052, bf = 0.154432, tf = 0.011557, tw = 0.008128 (AISC: 6.38/6.08/0.455/0.320 in).
  * Pipe length 7.8474 m equals the distance between its two `ROUTEPipePort` points.
  * ACIS header: 1 unit = 1000 mm.
* **One global Cartesian frame, Z up**: support CS z-axis (0,0,1), elevations 8–40 m. Named user CSs (`CS_JETTY 2/4`, `CS_LNG NEW` …) are
  merely local frames stored with their global origin and axes in `GRDSYSSPGCoordinateSystem`. Stored coordinates are always global.

```sql
SELECT COUNT(*) n, MIN(PlacePointX), MAX(PlacePointX), MIN(PlacePointY), MAX(PlacePointY), MIN(PlacePointZ), MAX(PlacePointZ),
       AVG(PlacePointX), AVG(PlacePointY), AVG(PlacePointZ) FROM dbo.ROUTEPipePort;
-- 1725332 | -7.07 | 7354.97 | -141.32 | 1487.04 | -44.56 | 73.25 | 3042.2 | 638.7 | 9.30
SELECT MIN(xmin), MAX(xmax), MIN(ymin), MAX(ymax), MIN(zmin), MAX(zmax) FROM dbo.CORESpatialIndex;
-- -27.36 | 242332.1 | -1578.2 | 16518089728 | -25678238 | 34504832      <-- garbage outliers exist
SELECT DISTINCT PERCENTILE_CONT(0.001) WITHIN GROUP (ORDER BY xmin) OVER (), PERCENTILE_CONT(0.999) WITHIN GROUP (ORDER BY xmax) OVER (), …
FROM dbo.CORESpatialIndex TABLESAMPLE (1 PERCENT);
-- x: -0.001 .. 7933.9 | y: -967.2 .. 1415.9 | z: -1.08 .. 60.0
```
The site is about 7.4 km × 1.6 km. glTF/float32 needs a local origin offset (for example subtract (5900, 1000, 0) or use a per-tile RTC centre).
`CORESpatialIndex` is float32 and contains outliers, so clip it to the percentile box.

---

## 3. One pipeline → ordered, PCF-ready component list

Pipeline chosen: **`4"-W60522-NGXE1`** (`00033457-0000-0000-231E-0173D05A6004`). It has 7 runs and 66 parts: 21 pipes, 25 WN
flanges, 9 LR elbows, 1 tee, 5 concentric reducers, 1 blind flange, 2 specialty valve items and 2 instruments. A second check was
run on `14''-1P11040-NGB1` (`00033457-0000-0000-6804-002FEC583E04`, 72 parts: gate/globe valves, weldolets, nipolets,
eccentric reducers, orifice flanges). The query takes 0.3–0.7 s per pipeline.

Pipelines with 20–200 parts can be found with this query (it uses loop joins and takes 0.3 s for 400 pipelines):
```sql
DECLARE @pl TABLE (oid uniqueidentifier PRIMARY KEY);
INSERT @pl SELECT TOP 400 oid FROM dbo.SHPCONPipelineSystem ORDER BY oid;
SELECT n.strName, p.oid, COUNT(DISTINCT r1.oidTarget) nruns, COUNT(r2.oidTarget) nparts
FROM @pl p
JOIN dbo.CORERelationOrigin r1 ON r1.oid=p.oid AND r1.RelationType='A8CE36E7-A53F-4558-8DF9-F0BCE6583327'
JOIN dbo.CORERelationOrigin r2 ON r2.oid=r1.oidTarget AND r2.RelationType='3C9A3EEE-3F54-441F-A3D4-DCFC4615E88D'
JOIN dbo.CORENamedItem n ON n.oid=p.oid
GROUP BY n.strName, p.oid HAVING COUNT(r2.oidTarget) BETWEEN 20 AND 200 OPTION (LOOP JOIN);
```

### 3.1 Component query (`s3d_sql/pipeline_components.sql`, run with `sqlcmd -v PL=<oid>`)

Where each value comes from:
* **End points:** pipes use their own `ROUTEPipePort` rows. Fittings use the `ROUTEDistribConnection.Location` of the connection each
  proxy port sits on, and the port number comes from the proxy name's trailing digits.
* **CENTRE-POINT:** the generating path feature's `Location`. For turns this is the tangent intersection (checked: both elbow
  ends are exactly `BendRadius` = 0.152 from it).
* **Bend data:** `ROUTEPipeTurnPathFeat.BendRadius/BendAngle`.
* **Catalog data:** commodity code, SKEY, sizes and schedules come through the proxy (section 1.4).
* **Order:** BFS hop count inside each run, starting at a part with at most one in-run neighbour.

```sql
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

```

### 3.2 Actual rows (coordinates in m; SeqInRun = BFS order; EP3 = branch/tap port)

#### Pipeline 4"-W60522-NGXE1 (00033457-0000-0000-231E-0173D05A6004) — first 24 of 66 rows (run -0001) and all branch/reducer rows
|Run|Seq|PCFType|SKEY|CommodityType|ItemCode|Size1xSize2|Sched|OD|Wall|BendR/Angle|Material|EP1|EP2|EP3|CP|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|100-Undefined-0001-NGBE1|0|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6081.129,691.993,18.084|6081.053,691.993,18.084||6081.129,691.993,18.084|
|100-Undefined-0001-NGBE1|1|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6081.129,691.993,18.084|6081.206,691.993,18.084||6081.129,691.993,18.084|
|100-Undefined-0001-NGBE1|2|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6081.206,691.993,18.084|6089.054,691.993,18.084||6085.130,691.993,18.084|
|100-Undefined-0001-NGBE1|3|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6089.130,691.993,18.084|6089.054,691.993,18.084||6089.130,691.993,18.084|
|100-Undefined-0001-NGBE1|4|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6089.130,691.993,18.084|6089.207,691.993,18.084||6089.130,691.993,18.084|
|100-Undefined-0001-NGBE1|5|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6089.207,691.993,18.084|6097.106,691.993,18.084||6093.156,691.993,18.084|
|100-Undefined-0001-NGBE1|6|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6097.182,691.993,18.084|6097.106,691.993,18.084||6097.182,691.993,18.084|
|100-Undefined-0001-NGBE1|7|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6097.182,691.993,18.084|6097.259,691.993,18.084||6097.182,691.993,18.084|
|100-Undefined-0001-NGBE1|8|ELBOW|ELBW|E90LR|E90LR_ADC_AAE_S40_BE|100x100 mm|S-40|0.114||0.152 / 90°|ASTM A234-WPB|6097.411,691.993,17.932|6097.259,691.993,18.084||6097.411,691.993,18.084|
|100-Undefined-0001-NGBE1|9|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6097.411,691.993,17.932|6097.411,691.993,16.808||6097.411,691.993,17.370|
|100-Undefined-0001-NGBE1|10|ELBOW|ELBW|E90LR|E90LR_ADC_AAE_S40_BE|100x100 mm|S-40|0.114||0.152 / 90°|ASTM A234-WPB|6097.411,691.841,16.656|6097.411,691.993,16.808||6097.411,691.993,16.656|
|100-Undefined-0001-NGBE1|11|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6097.411,691.841,16.656|6097.411,691.169,16.656||6097.411,691.505,16.656|
|100-Undefined-0001-NGBE1|12|ELBOW|ELBW|E90LR|E90LR_ADC_AAE_S40_BE|100x100 mm|S-40|0.114||0.152 / 90°|ASTM A234-WPB|6097.563,691.017,16.656|6097.411,691.169,16.656||6097.411,691.017,16.656|
|100-Undefined-0001-NGBE1|13|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6097.563,691.017,16.656|6100.647,691.017,16.656||6099.105,691.017,16.656|
|100-Undefined-0001-NGBE1|14|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6100.724,691.017,16.656|6100.647,691.017,16.656||6100.723,691.017,16.656|
|100-Undefined-0001-NGBE1|15|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6100.724,691.017,16.656|6100.801,691.017,16.656||6100.723,691.017,16.656|
|100-Undefined-0001-NGBE1|16|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6100.801,691.017,16.656|6100.862,691.017,16.656||6100.832,691.017,16.656|
|100-Undefined-0001-NGBE1|17|ELBOW|ELBW|E90LR|E90LR_ADC_AAE_S40_BE|100x100 mm|S-40|0.114||0.152 / 90°|ASTM A234-WPB|6101.014,691.169,16.656|6100.862,691.017,16.656||6101.014,691.017,16.656|
|100-Undefined-0001-NGBE1|18|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6101.014,691.169,16.656|6101.014,691.896,16.656||6101.014,691.533,16.656|
|100-Undefined-0001-NGBE1|19|ELBOW|ELBW|E90LR|E90LR_ADC_AAE_S40_BE|100x100 mm|S-40|0.114||0.152 / 90°|ASTM A234-WPB|6101.014,691.896,16.656|6101.166,692.048,16.656||6101.014,692.048,16.656|
|100-Undefined-0001-NGBE1|20|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6101.166,692.048,16.656|6106.123,692.048,16.656||6103.645,692.048,16.656|
|100-Undefined-0001-NGBE1|21|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6106.199,692.048,16.656|6106.123,692.048,16.656||6106.200,692.048,16.656|
|100-Undefined-0001-NGBE1|22|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6106.199,692.048,16.656|6106.276,692.048,16.656||6106.200,692.048,16.656|
|100-Undefined-0001-NGBE1|23|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6106.276,692.048,16.656|6114.123,692.048,16.656||6110.200,692.048,16.656|

|Run|Seq|PCFType|SKEY|CommodityType|ItemCode|Size1xSize2|Sched|OD|Wall|BendR/Angle|Material|EP1|EP2|EP3|CP|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|100-Undefined-0005-NGBE1|0|TEE|TEFL|T|T_ADC_AAE_S40_BE|100x100 mm|S-40|0.114|||ASTM A234-WPB|6115.185,681.208,12.355|6115.185,681.208,12.145|6115.290,681.208,12.250|6115.185,681.208,12.250|
|100-Undefined-0005-NGBE1|1|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6115.185,681.208,12.437|6115.185,681.208,12.355||6115.185,681.208,12.396|
|100-Undefined-0005-NGBE1|2|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6115.185,681.208,12.570|6115.185,681.208,12.437||6115.185,681.208,12.542|
|100-Undefined-0005-NGBE1|3|MISC-COMPONENT||||4x0 in||0.114||||6115.185,681.208,12.569|6115.185,681.208,12.514||6115.185,681.208,12.542|
|100-Undefined-0005-NGBE1|3|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6115.185,681.208,12.570|6115.185,681.208,12.646||6115.185,681.208,12.542|
|100-Undefined-0005-NGBE1|4|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6115.185,681.208,12.651|6115.185,681.208,12.646||6115.185,681.208,12.649|
|100-Undefined-0005-NGBE1|5|REDUCER-CONCENTRIC|RCBW|REDC|REDC_ADC_AAE_S40XS40_BE|100x80 mm|S-40|0.114|||ASTM A234-WPB|6115.185,681.208,12.651|6115.185,681.208,12.753||6115.185,681.208,12.702|
|100-Undefined-0007-NGBE1|0|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6116.832,681.208,12.250|6116.887,681.208,12.250||6116.860,681.208,12.250|
|100-Undefined-0007-NGBE1|1|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6116.755,681.208,12.250|6116.832,681.208,12.250||6116.455,681.208,12.250|
|100-Undefined-0007-NGBE1|2|INSTRUMENT||GLO||4x0 in||0.114||||6116.154,681.208,12.250|6116.755,681.208,12.250||6116.455,681.208,12.250|
|100-Undefined-0007-NGBE1|3|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6116.154,681.208,12.250|6116.077,681.208,12.250||6116.455,681.208,12.250|
|100-Undefined-0007-NGBE1|4|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6115.591,681.208,12.250|6116.077,681.208,12.250||6115.834,681.208,12.250|
|100-Undefined-0007-NGBE1|5|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6115.514,681.208,12.250|6115.591,681.208,12.250||6115.478,681.208,12.250|
|100-Undefined-0007-NGBE1|6|INSTRUMENT||Generic body v||4x0 in||0.114||||6115.442,681.208,12.250|6115.514,681.208,12.250||6115.478,681.208,12.250|
|100-Undefined-0007-NGBE1|6|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|100x100 mm|S-40|0.114|||ASTM A105|6115.442,681.208,12.250|6115.366,681.208,12.250||6115.478,681.208,12.250|
|100-Undefined-0007-NGBE1|7|PIPE||PIPE|PI_ABH_S40_BE_SMLS|100x100 mm|S-40|0.114|0.006||API 5L Grade B|6115.290,681.208,12.250|6115.366,681.208,12.250||6115.328,681.208,12.250|
|40-Undefined-0003-NGBE1|0|REDUCER-CONCENTRIC|RCBW|REDC|REDC_ADC_AAE_S40XS80_BE|80x40 mm|S-40|0.048|||ASTM A234-WPB|6115.185,681.208,13.630|6115.185,681.208,13.541||6115.185,681.208,13.585|
|40-Undefined-0003-NGBE1|1|PIPE||PIPE|PI_ABH_S80_BE_SMLS|40x40 mm|S-80|0.048|0.005||API 5L Grade B|6115.185,681.208,13.541|6115.185,681.208,12.842||6115.185,681.208,13.191|
|80-Undefined-0002-NGBE1|0|REDUCER-CONCENTRIC|RCBW|REDC|REDC_ADC_AAE_S40XS40_BE|100x80 mm|S-40|0.089|||ASTM A234-WPB|6115.185,681.208,13.732|6115.185,681.208,13.630||6115.185,681.208,13.681|
|80-Undefined-0004-NGBE1|0|REDUCER-CONCENTRIC|RCBW|REDC|REDC_ADC_AAE_S40XS80_BE|80x40 mm|S-40|0.089|||ASTM A234-WPB|6115.185,681.208,12.753|6115.185,681.208,12.842||6115.185,681.208,12.798|
|80-Undefined-0006-NGBE1|0|FLANGE-BLIND|FLBL|FBLD|FBLD_CL150_ABQ_AAD_RF_AV|80x0 mm||0.089|||ASTM A105|6115.185,681.208,11.781|||6115.185,681.208,11.781|
|80-Undefined-0006-NGBE1|1|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|80x80 mm|S-40|0.089|||ASTM A105|6115.185,681.208,11.781|6115.185,681.208,11.852||6115.185,681.208,11.781|
|80-Undefined-0006-NGBE1|2|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|80x80 mm|S-40|0.089|||ASTM A105|6115.185,681.208,11.923|6115.185,681.208,11.852||6115.185,681.208,11.922|
|80-Undefined-0006-NGBE1|3|MISC-COMPONENT||||4x0 in||0.089||||6115.185,681.208,11.972|6115.185,681.208,11.923||6115.185,681.208,11.948|
|80-Undefined-0006-NGBE1|3|FLANGE|FLWN|FWN|FWN_CL150_ABQ_AAD_S40_RF_BE_AV|80x80 mm|S-40|0.089|||ASTM A105|6115.185,681.208,11.973|6115.185,681.208,12.043||6115.185,681.208,11.948|
|80-Undefined-0006-NGBE1|4|REDUCER-CONCENTRIC|RCBW|REDC|REDC_ADC_AAE_S40XS40_BE|100x80 mm|S-40|0.089|||ASTM A234-WPB|6115.185,681.208,12.145|6115.185,681.208,12.043||6115.185,681.208,12.094|

#### Pipeline 14''-1P11040-NGB1 (00033457-0000-0000-6804-002FEC583E04) — valves, olets, eccentric reducers, orifice flanges
|Run|Seq|PCFType|SKEY|CommodityType|ItemCode|Size1xSize2|Sched|OD|Wall|BendR/Angle|Material|EP1|EP2|EP3|CP|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|UNIT 1100-0.5-P-0312-NGB1|1|VALVE|VTSW|GATR|VADAQBVAHAHPABQZZZZUS|0.5x0.5 in||0.021|||ASTM A105|5917.844,1061.281,16.910|5917.844,1061.326,16.865||5917.844,1061.304,16.888|
|UNIT 1100-0.5-P-0313-NGB1|1|VALVE|VTSW|GATR|VADAQBVAHAHPABQZZZZUS|0.5x0.5 in||0.021|||ASTM A105|5917.784,1060.673,16.880|5917.784,1060.628,16.835||5917.784,1060.651,16.858|
|UNIT 1100-0.75-P-0306-NGB1|0|MISC-COMPONENT||NOL|NGB1_NIPOLT_6|350x20 mm|S-30|0.027|||ASTM A105|5907.061,1060.992,12.410|5906.854,1060.992,12.410||5907.061,1060.992,12.410|
|UNIT 1100-0.75-P-0314-NGB1|0|MISC-COMPONENT||NOL|NGB1_NIPOLT_6|350x20 mm|S-30|0.027|||ASTM A105|5921.441,1060.992,13.455|5921.647,1060.992,13.455||5921.441,1060.992,13.455|
|UNIT 1100-14-P-0302-NGB1|0|REDUCER-ECCENTRIC|REBW|REDE|MBJZZBOZZAAEADCZZUS|16x14 in|S-30|0.356|||ASTM A234-WPB|5907.061,1062.382,11.871|5907.061,1062.027,11.846||5907.061,1062.204,11.871|
|UNIT 1100-14-P-0302-NGB1|2|TEE|TEFL|T|MDJZZBOZZAAEADCZZUS|14x14 in|S-30|0.356|||ASTM A234-WPB|5907.061,1061.272,11.846|5907.061,1060.713,11.846|5907.061,1060.992,12.125|5907.061,1060.992,11.846|
|UNIT 1100-14-P-0303-NGB1|0|REDUCER-ECCENTRIC|REBW|REDE|MBJZZBOZZAAEADCZZUS|16x14 in|S-30|0.356|||ASTM A234-WPB|5921.441,1062.476,12.218|5921.441,1062.120,12.193||5921.441,1062.298,12.218|
|UNIT 1100-14-P-0303-NGB1|5|VALVE|VTFL|GAT|VAAAHABAHADJADAZZZZUS|14x14 in||0.356|||ASTM A216-WCB|5921.441,1060.992,12.914|5921.441,1060.992,13.296||5921.441,1060.992,13.105|
|UNIT 1100-14-P-0303-NGB1|10|FLANGE|FOWN|FOWN|FAWAMDCZZAAUABQHNUS|14x14 in|S-30|0.356|||ASTM A105|5917.814,1060.992,17.199|5917.963,1060.992,17.199|5917.844,1061.193,16.998|5917.820,1060.992,17.199|
|UNIT 1100-14-P-0303-NGB1|11|FLANGE|FOWN|FOWN|FAWAMDCZZAAUABQHNUS|14x14 in|S-30|0.356|||ASTM A105|5917.814,1060.992,17.199|5917.665,1060.992,17.199|5917.784,1060.791,16.998|5917.808,1060.992,17.199|
|UNIT 1100-1-P-0305-NGB1|0|MISC-COMPONENT||NOL|NGB1_NIPOLET_PE|14x1 in|S-80|0.033|||ASTM A350-LF2|5907.061,1061.865,11.846|5907.061,1061.865,12.113||5907.061,1061.865,11.846|
|UNIT 1100-1-P-0308-NGB1|2|VALVE|VGSW|GLOR|VANAQBVAEAICABQZZZZUS|1x1 in||0.033|||ASTM A105|5920.632,1060.992,17.503|5920.632,1060.992,17.596||5920.632,1060.992,17.549|
|UNIT 1100-1-P-0308-NGB1|4|MISC-COMPONENT||NOL|NGB1_NIPOLET_PE|14x1 in|S-80|0.033|||ASTM A350-LF2|5920.632,1060.992,17.199|5920.632,1060.992,17.466||5920.632,1060.992,17.199|
|UNIT 1100-1-P-0309-NGB1|0|MISC-COMPONENT||NOL|NGB1_NIPOLET_PE|16x1 in|S-80|0.033|||ASTM A350-LF2|5920.431,1063.086,12.218|5920.431,1063.086,11.926||5920.431,1063.086,12.218|
|UNIT 1100-1-P-0309-NGB1|2|VALVE|VTSW|GATR|VADAQBVAHAHPABQZZZZUS|1x1 in||0.033|||ASTM A105|5920.431,1063.086,11.818|5920.431,1063.086,11.748||5920.431,1063.086,11.783|
|UNIT 1100-2-P-0304-NGB1|0|OLET|WTBW|WOL|NGB1_WELDOLET_22|350x50 mm|S-30|0.060|||ASTM A105|5907.061,1061.616,11.846|5907.061,1061.616,11.630||5907.061,1061.616,11.846|
|UNIT 1100-6-P-0310-NGB1|0|OLET|WTBW|WOL|NGB1_WELDOLET_25|350x150 mm|S-30|0.168|||ASTM A105|5921.441,1060.992,14.682|5921.441,1060.754,14.682||5921.441,1060.992,14.682|
|UNIT 1100-6-P-0311-NGB1|0|OLET|WTBW|WOL|NGB1_WELDOLET_25|350x150 mm|S-30|0.168|||ASTM A105|5921.441,1061.966,12.193|5921.441,1061.966,12.431||5921.441,1061.966,12.193|


Observations:
* Every one of the 66 + 72 rows has EP1 and EP2, except single-port items (blind flange, fusible plugs), which are correct with one end.
* Orifice flanges expose their tap as EP3.
* Instruments and specialties get their catalog data from the model-resident part. Their `TagNumber` is empty in this project, so the
  occurrence name (`CORENamedItem`) is the tag.
* PDS-migrated part classes (`SlipOnFlangePDB15`, `NipoletPDB3377`, `FSO`, `NOL` …) are **not in `REFDATPipeMfgMapSymbol`**. Map them with
  `CommodityType`/`CommodityClass` (see risk 3).

### 3.3 Connection items and supports (`s3d_sql/pipeline_connections_supports.sql`)

```sql
/* Connection items (welds, gaskets, bolt sets) and pipe supports for ONE pipeline. $(PL) = pipeline oid */
SET NOCOUNT ON;
DECLARE @pl uniqueidentifier = '$(PL)';
DECLARE @SystemHierarchy uniqueidentifier='A8CE36E7-A53F-4558-8DF9-F0BCE6583327',
        @OwnsDistConn    uniqueidentifier='67E1D32D-38B0-4885-8F1A-784627305608',
        @GenConnItems    uniqueidentifier='95A02A64-195B-46D4-BE9E-2A4A15A9F90D',
        @SystemHasSupport uniqueidentifier='F2B9B39A-909D-4F1B-9ED5-2E66D26EAFEC',
        @SupportHasComponents uniqueidentifier='1781C544-33A0-4982-ACE1-BCBCBAEA5006',
        @SupportHasCS    uniqueidentifier='0E77B4AF-2DEB-4D45-953F-F59D0D36A601',
        @ProxyOwner      uniqueidentifier='5280312B-E69C-11D1-A966-080036069A02',
        @OccAssyHasPart  uniqueidentifier='1613374A-A8F0-11D4-BA3D-009027955FAD';

/* A. distribution connections of every run + generated items */
SELECT rn.strName PipeRun, CAST(dc.oid AS char(36)) Conn, ct.ShortStringValue ConnType,
       dc.LocationX, dc.LocationY, dc.LocationZ, dc.ConnectionSize,
       j.TableName ItemTable, w.Type WeldTypeCode, wt.ShortStringValue WeldType,
       g.GasketSizedCommodityCode, COALESCE(g.ShortMaterialDescription, bs.ShortMaterialDescription) ItemDescription,
       bs.BoltQuantity, bs.Diameter BoltDia, bs.RoundedLength BoltLength
FROM dbo.CORERelationOrigin r1
JOIN dbo.CORERelationOrigin r2 ON r2.oid = r1.oidTarget AND r2.RelationType = @OwnsDistConn
JOIN dbo.ROUTEDistribConnection dc ON dc.oid = r2.oidTarget
LEFT JOIN dbo.CORENamedItem rn ON rn.oid = r1.oidTarget
LEFT JOIN dbo.CORERelationOrigin gi ON gi.oid = dc.oid AND gi.RelationType = @GenConnItems
LEFT JOIN dbo.COREBaseClass b ON b.oid = gi.oidTarget
LEFT JOIN dbo.COREJPOSchema j ON j.class_id = b.ClassId
LEFT JOIN dbo.ROUTEPipeWeld w ON w.oid = gi.oidTarget
LEFT JOIN dbo.ROUTEPipeGasket g ON g.oid = gi.oidTarget
LEFT JOIN dbo.ROUTEPipeBoltSet bs ON bs.oid = gi.oidTarget
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView ct ON ct.TableName='ConnectionType' AND ct.ValueID = dc.ConnectionType
LEFT JOIN [MLNG@1_CDB_SCHEMA].dbo.CodelistValueView wt ON wt.TableName='WeldType' AND wt.ValueID = w.Type
WHERE r1.oid = @pl AND r1.RelationType = @SystemHierarchy
ORDER BY rn.strName, dc.LocationX, dc.LocationY, dc.LocationZ;

/* B. pipe supports: name, BOM text, catalog assembly (proxy moniker), CS origin, bbox, components */
SELECT CAST(s.oid AS char(36)) Support, n.strName, s.BOMdescription, asy.RelationName CatalogAssembly,
       cs.o0 OriginX, cs.o1 OriginY, cs.o2 OriginZ, cs.z0 AxisZx, cs.z1 AxisZy, cs.z2 AxisZz,
       si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax,
       (SELECT COUNT(*) FROM dbo.CORERelationOrigin c WHERE c.oid = s.oid AND c.RelationType = @SupportHasComponents) nComponents
FROM dbo.CORERelationOrigin r
JOIN dbo.HNGSUPHgrPipeSupport s ON s.oid = r.oidTarget
LEFT JOIN dbo.CORENamedItem n ON n.oid = s.oid
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = s.oid
OUTER APPLY (SELECT TOP 1 c.* FROM dbo.CORERelationOrigin x JOIN dbo.GRDSYSSPGCoordinateSystem c ON c.oid = x.oidTarget
             WHERE x.oid = s.oid AND x.RelationType = @SupportHasCS) cs
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = @ProxyOwner
             WHERE x.oid = s.oid AND x.RelationType = @OccAssyHasPart) asy
WHERE r.oid = @pl AND r.RelationType = @SystemHasSupport;

```
Sample output: 88 connection-item rows and 11 supports for the same pipeline.
```
PipeRun|Conn|ConnType|LocationX|LocationY|LocationZ|ItemTable|WeldType|ItemDescription|BoltQuantity|BoltDia|BoltLength
UNIT 2400-100-Undefined-0001-NGBE1|00013887-…-2A1A-CEFAD35A3204|Bolted Joint|6081.12944|691.99340|18.08351|ROUTEPipeGasket|NULL|GSKT CAF, CL150, ABS, ASME B16.21, OIL RESISTANCE, THK: 1.5mm, RF|||
UNIT 2400-100-Undefined-0001-NGBE1|00013887-…-2A1A-CEFAD35A3204|Bolted Joint|6081.12944|691.99340|18.08351|ROUTEPipeBoltSet|NULL|5/8" X 90mm LG, STUD BOLTS, ASTM A193-B7, … END FLG|8|0.015875|0.09525
UNIT 2400-100-Undefined-0001-NGBE1|00013887-…-291A-CEFAD35A3204|Welded Joint|6081.20619|691.99340|18.08351|ROUTEPipeWeld|Shop weld||||
Support-name|BOMdescription|CatalogAssembly|OriginX|OriginY|OriginZ|AxisZ|nComponents
EXISTING PS|Shoe w/Medium Clamps - WT4X15.5 L = 14|Assy_SH_CL_6|6115.79586|681.20842|12.25015|0,0,1|3
EXISTING PS|Shoe w/Medium Clamps - WT4X15.5 L = 14|Assy_SH_CL_6|6115.58749|689.92695|16.65555|0,0,1|3
```
The support CS origin lies on the pipe centreline (Y = 681.208 and Z = 12.250 match the run axis), so it can be used directly as the
PCF `SUPPORT CO-ORDS`.

### 3.4 Emitting PCF from these rows

Use a header of `ISOGEN-FILES ISOGEN.FLS`, `UNITS-BORE MM`, `UNITS-CO-ORDS MM`, `UNITS-WEIGHT KGS`, `UNITS-BOLT-DIA MM`,
`UNITS-BOLT-LENGTH MM`, then `PIPELINE-REFERENCE <LineNumber>` (CORENamedItem of the pipeline). Coordinates are
`X*1000 Y*1000 Z*1000`. Bore is the NPD in mm: catalog `PrimarySize/SecondarySize` with `PriSizeNPDUnits`, and in → ×25.4 or the
nominal DN table.

| PCF record | from row | notes |
|---|---|---|
| `PIPE` | PCFType=PIPE: `END-POINT` EP1 bore1, `END-POINT` EP2 bore1 | `ITEM-CODE` = ItemCode (contractor commodity code); PipeLength for cut length |
| `ELBOW` / `BEND` | EP1, EP2, `CENTRE-POINT` = CP (turn feature Location), `SKEY` = SKEY_Type (e.g. ELBW), `ANGLE` = BendAngleDeg×100, `BEND-RADIUS` = BendRadius×1000 | CP is the tangent intersection, as PCF expects |
| `TEE` | EP1, EP2 (run), `CENTRE-POINT` = CP (branch feature), `BRANCH1-POINT` = EP3 with bore2 | SKEY TEBW/TEFL… |
| `OLET` (WOL/NOL/FLGOL) | `CENTRE-POINT` = header-side point, `BRANCH1-POINT` = EP2 | CP in the row is the header surface point. Project it onto the header centreline using the header pipe's ports |
| `REDUCER-CONCENTRIC` / `REDUCER-ECCENTRIC` | EP1 bore1, EP2 bore2, SKEY RCBW/REBW | eccentric: `FLAT-DIRECTION` from the CORESymbol matrix of the part |
| `FLANGE`, `FLANGE-BLIND` | EP1 (face), EP2 (weld end); blind has only EP1 | SKEY FLWN/FLSO/FLBL/FOWN; orifice-flange tap → `BRANCH1-POINT` |
| `VALVE` | EP1, EP2, `CENTRE-POINT` = CP, SKEY (VTFL, VGSW …) | `SPINDLE-DIRECTION` from the CORESymbol matrix, or the valve-operator part (class 0000272B, 21 k) placed on the valve |
| `INSTRUMENT` / `MISC-COMPONENT` | EP1, EP2, CP | SKEY from the instrument class or a CommodityType map; `ITEM-CODE` = PartNumber/occurrence name |
| `GASKET`, `BOLT` | connection items at a bolted connection (3.3) | bolt `BOLT-DIA`, `BOLT-LENGTH`, `BOLT-QUANTITY` |
| `WELD` | connection items with ItemTable=ROUTEPipeWeld: `END-POINT` = connection Location | WeldType codelist → shop/field |
| `SUPPORT` | 3.3 support rows: `CO-ORDS` = CS origin, `SKEY 01HG`, `ITEM-CODE` = CatalogAssembly, `NAME` = support name | |
| `END-CONNECTION-PIPELINE` / `END-CONNECTION-EQUIPMENT` | a connection whose other part belongs to another pipeline, or whose FlowPorts include an `EQUIPPipeNozzle` | |
| `MATERIALS` section | `ITEM-CODE` → `DESCRIPTION` (ShortMaterialDescription) + Material (MaterialsGrade) | |

`SKEY` = `REFDATPipeMfgMapSymbol` (MapType 0) row for the part class whose last two characters match the MapType 2 end-prep suffix
of catalog port 1. The same table also provides the PCF keyword (`PCFComponentID`) directly.

---

## 4. Structure: members with axis, roll, section and type

`s3d_sql/structure_members.sql` (run with `-v TOPN=n`; remove TOP for the full 880 k export). `structure_sections.sql` gives section usage.
`section_dimensions.sql` returns every numeric property of a section.

```sql
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

```

Geometry rule: sweep the catalog profile along `start→end` of `STRUCTMemberPartAxisLin`.
* Profile placement relative to the axis: `STRUCTPartPrismaticGen.cardinalPoint` (S3D 1–15 grid; 5 = centre, 1 = bottom-left, 8 = top-centre …).
* Roll: `betaAngle` (rad). `OVector` is the local orientation vector already computed by S3D. Use it directly and fall back to beta only if needed.
* Mirror: `mirror`.
* `STRUCTMemberSysLinear` holds the logical (un-trimmed) axis. The part axis is the physical one; use it.
* `cutLength` = physical length.
* End cuts, copes and web penetrations are not in columns. They exist only in the ACIS solid:
  PrismaticGen ─StructResult→ `CMemberGeometry` (240007) → `GEOTOPSolidBody` row with the same oid.

### 4.1 Actual rows

|PartName|StructSystem|Category/Type|Start x,y,z|End x,y,z|Roll°|CP|CutLen|Section moniker|Depth|Width|tf|tw|Material|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|0001-1714|SUPPORT_140|Beam/Beam|5917.555,1079.692,12.379|5917.812,1079.692,12.379|90.0|5|0.258|AISC-LRFD-3.1, L, L2-1/2X2X1/4|0.064|0.051|0.006|0.006|Steel - Carbon-A|
|0001-33004|SUPPORT_140|Beam/Beam|5917.699,1079.755,11.371|5917.699,1079.755,12.875|-90.0|5|1.504|Misc, CS, CS2.5|0.064|0.064|||Steel - Carbon-A|
|0001-33003|SUPPORT_139|Beam/Beam|5912.740,1071.297,12.265|5912.740,1071.471,12.265|270.0|5|0.174|AISC-LRFD-3.1, L, L2X2X1/4|0.051|0.051|0.006|0.006|Steel - Carbon-A|
|0001-32560|SUPPORT_111|Beam/Beam|5920.315,1061.225,12.767|5920.315,1061.225,12.425|90.0|5|0.373|Misc, CS, CS2.5|0.064|0.064|||Steel - Carbon-A|
|Post-0001-116503|DesignedHandrail-Default|Handrail Element/Post|6807.721,1072.918,33.373|6807.721,1072.918,34.563|180.0|1|1.190|AISC-LRFD-3.1, L, L3X3X1/4|0.076|0.076|0.006|0.006|Steel - Carbon-A|
|Toe Plate-0001-46181|DesignedHandrail-Default|Handrail Element/Toe Plate|6806.428,1086.176,33.553|6806.428,1077.803,33.553|0.0|3|8.373|Misc, RS, RS0.3x3|0.076|0.008|||Steel - Carbon-A|
|Top Rail-0001-72831|DesignedHandrail-Default|Handrail Element/Top Rail|6806.428,1079.487,34.563|6806.428,1077.803,34.563|90.0|1|1.683|AISC-LRFD-3.1, L, L2X2X1/4|0.051|0.051|0.006|0.006|Steel - Carbon-A|
|Toe Plate-0001-46182|DesignedHandrail-Default|Handrail Element/Toe Plate|6806.428,1076.582,33.553|6806.428,1072.918,33.553|0.0|3|3.664|Misc, RS, RS0.3x3|0.076|0.008|||Steel - Carbon-A|
|Top Rail-0001-72835|DesignedHandrail-Default|Handrail Element/Top Rail|6806.428,1076.599,34.563|6806.428,1075.481,34.563|90.0|1|1.118|AISC-LRFD-3.1, L, L2X2X1/4|0.051|0.051|0.006|0.006|Steel - Carbon-A|
|Top Rail-0001-72836|DesignedHandrail-Default|Handrail Element/Top Rail|6806.428,1074.492,34.563|6806.428,1072.918,34.563|90.0|1|1.625|AISC-LRFD-3.1, L, L2X2X1/4|0.051|0.051|0.006|0.006|Steel - Carbon-A|
|Post-0001-116501|DesignedHandrail-Default|Handrail Element/Post|6806.878,1072.918,33.373|6806.878,1072.918,34.563|180.0|1|1.190|AISC-LRFD-3.1, L, L3X3X1/4|0.076|0.076|0.006|0.006|Steel - Carbon-A|
|0001-422137|COLUMN|Column/Column|5949.980,897.996,16.806|5949.980,897.996,17.583|90.0|5|0.777|AISC-LRFD-3.1, W, W6X25|0.162|0.154|0.012|0.008|Steel - Carbon-A|
|0001-422123|COLUMN|Column/Column|5949.980,893.999,16.806|5949.980,893.999,17.583|90.0|5|0.777|AISC-LRFD-3.1, W, W6X25|0.162|0.154|0.012|0.008|Steel - Carbon-A|
|0001-422122|COLUMN|Column/Column|5949.980,893.999,15.314|5949.980,893.999,16.806|90.0|5|1.492|AISC-LRFD-3.1, W, W6X25|0.162|0.154|0.012|0.008|Steel - Carbon-A|
|0001-422141|COLUMN|Column/Column|5949.980,897.996,15.314|5949.980,897.996,16.806|90.0|5|1.492|AISC-LRFD-3.1, W, W6X25|0.162|0.154|0.012|0.008|Steel - Carbon-A|
|0001-422137|COLUMN|Column/Column|5957.980,897.996,16.806|5957.980,897.996,17.583|90.0|5|0.777|AISC-LRFD-3.1, W, W6X25|0.162|0.154|0.012|0.008|Steel - Carbon-A|
|0001-429506|BRACE|Brace/Brace|5953.970,894.234,15.853|5957.980,897.718,15.853|270.0|1|5.312|AISC-LRFD-3.1, L, L3X2-1/2X1/4|0.076|0.064|0.006|0.006|Steel - Carbon-A|
|0001-429505|BRACE|Brace/Brace|5956.059,896.048,15.853|5957.980,894.137,15.853|270.0|1|2.710|AISC-LRFD-3.1, L, L3X2-1/2X1/4|0.076|0.064|0.006|0.006|Steel - Carbon-A|
|0001-429508|BRACE|Brace/Brace|5957.980,894.234,15.853|5961.991,897.739,15.853|0.0|1|5.326|AISC-LRFD-3.1, L, L3X2-1/2X1/4|0.076|0.064|0.006|0.006|Steel - Carbon-A|
|0001-429507|BRACE|Brace/Brace|5957.980,897.847,15.853|5961.991,894.316,15.853|0.0|1|5.343|AISC-LRFD-3.1, L, L3X2-1/2X1/4|0.076|0.064|0.006|0.006|Steel - Carbon-A|
|Unspecified|BRACE|Brace/Brace|5958.099,893.999,15.314|5953.983,893.999,11.519|270.0|8|5.299|AISC-LRFD-3.1, WT, WT3X10|0.079|0.153|0.009|0.007|Steel - Carbon-A|
|0001-541996|SP COLUMN|Column/Column|5788.092,672.568,11.519|5788.092,672.568,11.358|180.0|5|0.162|AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|0.222|0.222|||Steel - Carbon-A|
|0001-541751|SP COLUMN|Column/Column|5809.965,672.672,11.525|5809.965,672.672,11.370|180.0|5|0.155|AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|0.222|0.222|||Steel - Carbon-A|
|0001-542025|SP COLUMN|Column/Column|5789.869,666.048,11.548|5789.869,666.048,11.377|180.0|5|0.171|AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|0.222|0.222|||Steel - Carbon-A|
|0001-541860|SP COLUMN|Column/Column|5807.282,670.315,11.542|5807.282,670.315,11.377|0.0|5|0.165|AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|0.222|0.222|||Steel - Carbon-A|
|0001-541869|SP COLUMN|Column/Column|5807.313,667.325,11.520|5807.313,667.325,11.383|0.0|5|0.137|AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|0.222|0.222|||Steel - Carbon-A|


The W6X25 values match AISC (d 6.38 in, bf 6.08 in, tf 0.455 in, tw 0.320 in). Axis length equals `cutLength`.
Handrail posts and rails are ordinary member parts (type category 6).

### 4.2 Section usage (all 924 320 prismatic generators; 781 distinct catalog sections of 2 220)

```sql
/* section usage histogram (all members) + full dimension list for each used catalog section */
SET NOCOUNT ON;
SELECT po.RelationName SectionMoniker, COUNT(*) nMembers
INTO #xs
FROM dbo.CORERelationOrigin x
JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = '5280312B-E69C-11D1-A966-080036069A02'
WHERE x.RelationType = 'A1471E95-F9E0-409F-8BCB-6B2AF3132017'
GROUP BY po.RelationName;
SELECT PARSENAME(REPLACE(REPLACE(SectionMoniker,'.','~'),', ','.'),2) SectionType, COUNT(*) nSections, SUM(nMembers) nMembers
FROM #xs GROUP BY PARSENAME(REPLACE(REPLACE(SectionMoniker,'.','~'),', ','.'),2) ORDER BY 3 DESC;
SELECT TOP 25 * FROM #xs ORDER BY nMembers DESC;

```
```
SectionType|nSections|nMembers        SectionType|nSections|nMembers
L    |110|305754                      WT   | 83| 13835
RS   |118|267734   (Misc rect. bar)   HSSC | 52| 12244
W    |183|120756                      HSSR | 74|  2651
CS   | 38|113943   (Misc round bar)   S    | 13|  2375
MC   | 30| 34399                      HP/M/ST/2L/MT | 6/7/13/3/2 | 230/220/215/72/7
C    | 37| 34004
PIPE | 12| 15826
Top sections: L2X2X1/4 131003, RS0.5x2 90877, CS1 63897, L3X3X1/4 48440, RS0.5x10 28303, W8X15 14020, C4X7.25 13258, PIPE1/2SCH40 11825
```

### 4.3 Section dimensions (catalog, metres)

```sql
/* All numeric catalog properties (metres, m2, m4, kg/m) of the cross-sections referenced by the model.
   Run in MLNG@1_CDB. Put the monikers you need in the IN-list (or join to the #xs table from structure_sections.sql). */
SET NOCOUNT ON;
SELECT cno.ObjectName AS SectionMoniker, ifn.Name AS Interface, pn.Name AS Property, a.value
FROM dbo.CORENamedObjects cno
JOIN dbo.COREBaseClass b ON b.oid = cno.ObjectOid AND b.ClassId = 60035          -- CPCrossSection
JOIN dbo.COREDoubleAttribute a ON a.oid = cno.ObjectOid
JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceDef idf ON idf.IID = a.iid
JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject ifn ON ifn.oid = idf.oid
JOIN [MLNG@1_CDB_SCHEMA].dbo.JInterface_Has_JMembers jm ON jm.oidOrg = idf.oid
JOIN [MLNG@1_CDB_SCHEMA].dbo.IJInterfaceMember im ON im.oid = jm.oidDst AND im.DispatchID = a.dispid
JOIN [MLNG@1_CDB_SCHEMA].dbo.IJNamedObject pn ON pn.oid = jm.oidDst
WHERE cno.ObjectName IN ('AISC-LRFD-3.1, W, W6X25','AISC-LRFD-3.1, HSSC, HSS8-3/4X.500','AISC-LRFD-3.1, PIPE, PIPE1/2SCH40','Misc, RS, RS0.5x2','Misc, CS, CS2.5')
  AND ifn.Name NOT IN ('IStructCrossSectionDesignProperties','IStructAngleBoltGage','IStructFlangedBoltGage')
ORDER BY 1, 2, 3;
SELECT COUNT(*) AS catalog_sections FROM dbo.COREBaseClass WHERE ClassId = 60035;

```
```
SectionMoniker|Interface|Property|value
--------------|---------|--------|-----
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IJUAHSS|tdes|0.011811
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IJUAHSS|tnom|1.2699999999999999E-2
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IJUAHSSC|D_t|18.800000000000001
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IStructCrossSectionDimensions|Area|7.8064359999999999E-3
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IStructCrossSectionDimensions|Depth|0.22225
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IStructCrossSectionDimensions|Perimeter|0.69850000000000001
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IStructCrossSectionDimensions|Width|0.22225
AISC-LRFD-3.1, HSSC, HSS8-3/4X.500|IStructCrossSectionUnitWeight|UnitWeight|65.628029911417315
AISC-LRFD-3.1, PIPE, PIPE1/2SCH40|IJUAHSS|tdes|0.0027686
AISC-LRFD-3.1, PIPE, PIPE1/2SCH40|IJUAHSS|tnom|0.0027686
AISC-LRFD-3.1, PIPE, PIPE1/2SCH40|IStructCrossSectionDimensions|Area|0.00016129
AISC-LRFD-3.1, PIPE, PIPE1/2SCH40|IStructCrossSectionDimensions|Depth|2.1336000000000001E-2
AISC-LRFD-3.1, PIPE, PIPE1/2SCH40|IStructCrossSectionDimensions|Perimeter|6.7056000000000004E-2
AISC-LRFD-3.1, PIPE, PIPE1/2SCH40|IStructCrossSectionDimensions|Width|2.1336000000000001E-2
AISC-LRFD-3.1, PIPE, PIPE1/2SCH40|IStructCrossSectionUnitWeight|UnitWeight|1.2679156799212599
AISC-LRFD-3.1, W, W6X25|IJUAWideFlangeDesignProps|Fy3p|0.0
AISC-LRFD-3.1, W, W6X25|IJUAWideFlangeDesignProps|Qf|9.8551999999999987E-2
AISC-LRFD-3.1, W, W6X25|IJUAWideFlangeDesignProps|Qw|0.238506
AISC-LRFD-3.1, W, W6X25|IJUAWideFlangeDesignProps|Wno|5.8128915999999999E-3
AISC-LRFD-3.1, W, W6X25|IStructCrossSectionDimensions|Area|0.0047483776
AISC-LRFD-3.1, W, W6X25|IStructCrossSectionDimensions|Depth|0.162052
AISC-LRFD-3.1, W, W6X25|IStructCrossSectionDimensions|Perimeter|0.91185999999999989
AISC-LRFD-3.1, W, W6X25|IStructCrossSectionDimensions|Width|0.15443199999999999
AISC-LRFD-3.1, W, W6X25|IStructCrossSectionUnitWeight|UnitWeight|37.204098589238846
AISC-LRFD-3.1, W, W6X25|IStructFlangedSectionDimensions|bf|0.15443199999999999
AISC-LRFD-3.1, W, W6X25|IStructFlangedSectionDimensions|d|0.162052
AISC-LRFD-3.1, W, W6X25|IStructFlangedSectionDimensions|kdesign|1.9151600000000001E-2
AISC-LRFD-3.1, W, W6X25|IStructFlangedSectionDimensions|kdetail|0.0238125
AISC-LRFD-3.1, W, W6X25|IStructFlangedSectionDimensions|tf|0.011557
AISC-LRFD-3.1, W, W6X25|IStructFlangedSectionDimensions|tw|8.1280000000000015E-3
Misc, CS, CS2.5|IStructCrossSectionDimensions|Area|3.1668283437499998E-3
Misc, CS, CS2.5|IStructCrossSectionDimensions|Depth|6.3500000000000001E-2
Misc, CS, CS2.5|IStructCrossSectionDimensions|Perimeter|0.19949159999999999
Misc, CS, CS2.5|IStructCrossSectionDimensions|Width|6.3500000000000001E-2
Misc, CS, CS2.5|IStructCrossSectionUnitWeight|UnitWeight|24.856653533047897
Misc, RS, RS0.5x2|IStructCrossSectionDimensions|Area|6.4515999999999998E-4
Misc, RS, RS0.5x2|IStructCrossSectionDimensions|Depth|5.0799999999999998E-2
Misc, RS, RS0.5x2|IStructCrossSectionDimensions|Perimeter|0.127
Misc, RS, RS0.5x2|IStructCrossSectionDimensions|Width|1.2699999999999999E-2
Misc, RS, RS0.5x2|IStructCrossSectionUnitWeight|UnitWeight|5.0639242671784777
catalog_sections
----------------
2220
```
Property names by shape:
* I/W/C/L/WT: `IStructFlangedSectionDimensions.{d,bf,tf,tw,kdesign}`; angles also have `IJUAL.{xp,yp}`.
* Tubes/pipes: `IJUAHSS.{tnom,tdes}` plus `IStructCrossSectionDimensions.Depth` (OD).
* Bars: `Depth`/`Width` only.
* All sections: `IStructCrossSectionDimensions.{Depth,Width,Area,Perimeter}`.

---

## 5. Equipment without blobs

`s3d_sql/equipment.sql` has three result sets: header, nozzles, primitive shapes.

```sql
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

```

### 5.1 Actual rows

|Equipment|Name|System|Catalog class|Pos x,y,z|X-axis|bbox min|bbox max|shapes|nozzles|
|---|---|---|---|---|---|---|---|---|---|
|00004E2E-0000…4004|Copy of UNKNOWN EQUIP|UNKNOWN EQUIP|StorageTankAsm|5941.057,1091.611,25.198|1.000,-0.000,-0.000|5940.999,1091.640,24.789|5941.226,1091.831,25.706|9|4|
|00004E2E-0000…4104|7C-91501|7C-91501|StorageTankAsm|6822.467,1037.853,9.505|1.000,-0.000,0.000|6821.090,1036.595,9.406|6823.907,1039.412,29.958|3|23|
|00004E2E-0000…2304|UNKNOWN EQUIPMENT 19|UNKNOWN EQUIPMENT 19|StorageTankAsm|5937.138,1187.092,13.751|1.000,0.000,0.000|5936.559,1186.501,13.366|5937.761,1187.703,14.228|5|4|
|00004E2E-0000…3E06|1C-1103|1C-1103|GenericAidesAsm|5964.007,1073.015,11.594|1.000,0.000,0.000|5960.778,1069.902,11.320|5967.121,1076.611,40.717|23|24|
|00004E2E-0000…3E06|1E-1108|1E-1108|GenericAidesAsm|5946.133,1067.749,22.695|1.000,-0.000,-0.000|5945.295,1067.398,21.857|5946.970,1072.096,23.532|6|8|
|00004E2E-0000…2804|7E-91421|7E-91421|StorageTankAsm|6858.768,1223.077,42.530|1.000,-0.000,0.000|6855.265,1203.246,40.635|6870.922,1225.806,43.273|30|36|

|Equipment|Nozzle|NPD|EndPrep|Rating|X,Y,Z|Direction|OD|FlangeOD|FlangeThk|Length|
|---|---|---|---|---|---|---|---|---|---|---|
|A108-008CDD5A4004|N1|0.75 in|SWE|150|5941.170,1091.745,25.206|1.000,-0.000,-0.000|0.031|0.037|0.014|0.100|
|A108-008CDD5A4004|N2|0.75 in|SWE|150|5941.000,1091.745,25.206|-1.000,0.000,0.000|0.031|0.037|0.014|0.100|
|A108-008CDD5A4004|N3|0.75 in|SWE|150|5941.085,1091.745,24.781|-0.000,-0.000,-1.000|0.031|0.037|0.014|0.200|
|A108-008CDD5A4004|N4|0.75 in|SWE|150|5941.170,1091.745,24.907|1.000,-0.000,-0.000|0.031|0.037|0.014|0.100|
|C905-00B8F45B4104|N15|4.0 in|RFFE|150|6821.547,1036.859,15.329|-0.643,-0.766,0.000|0.114|0.229|0.022|0.300|
|C905-00B8F45B4104|N12|4.0 in|RFFE|150|6821.190,1037.243,12.351|-0.848,-0.530,-0.000|0.114|0.229|0.022|0.300|
|C905-00B8F45B4104|N13|4.0 in|RFFE|150|6821.625,1036.811,12.351|-0.545,-0.839,-0.000|0.114|0.229|0.022|0.300|
|C905-00B8F45B4104|N16|4.0 in|RFFE|150|6821.833,1036.636,15.329|-0.438,-0.899,-0.000|0.114|0.229|0.022|0.300|
|C905-00B8F45B4104|N14|4.0 in|RFFE|150|6821.378,1037.008,12.747|-0.766,-0.643,0.000|0.114|0.229|0.022|0.300|
|C905-00B8F45B4104|N23|1.0 in|RFFE|150|6823.950,1037.319,29.002|0.921,-0.391,0.000|0.033|0.108|0.013|0.400|

|Equipment|Shape|ShapeType|Params (m)|Origin x,y,z|matrix row0 (m0,m1,m2)|row2 (m8,m9,m10)|
|---|---|---|---|---|---|---|
|0508-0199465C2804|0E08-0199465C2804|RectangularSolid 001|A=0.5080 B=7.4030 C=15.6550|6863.094,1222.104,41.144|0.000,0.000,-1.000|1.000,-0.000,0.000|
|0508-0199465C2804|3C08-0199465C2804|RtCircularCone 001|A=0.4000 B=4.6210 C=0.2000|6863.152,1206.904,42.872|0.000,0.000,1.000|-1.000,0.000,-0.000|
|0508-0199465C2804|0A08-0199465C2804|RtCircularCylinder 001|A=0.9420 B=4.6210|6863.152,1222.060,42.872|0.000,0.000,-1.000|1.000,-0.000,0.000|
|0508-0199465C2804|3708-0199465C2804|TruncatedRectangularPrism 001|A=7.2100 B=4.8260 C=4.7330 D=4.7630 E=1.0700|6868.157,1206.889,41.144|0.000,0.000,1.000|0.000,-1.000,0.000|
|431B-0190E4583E06|D501-DFB1E4582804|OctogonalSolid 001|A=0.2730 B=6.0460 C=6.0180 D=2.5320|5964.015,1072.976,11.321|0.000,0.000,1.000|-1.000,-0.000,-0.000|
|431B-0190E4583E06|6010-DFB1E4582804|Platform1 001|A=0.2500 B=0.5000 C=2.8370 D=1.1345|5963.866,1072.855,25.181|0.035,0.999,0.000|0.000,0.000,1.000|
|431B-0190E4583E06|1F07-DFB1E4582804|SemiEllipticalHead 001|A=5.6740 B=1.4180|5964.007,1073.015,39.298|0.000,0.000,1.000|-1.000,-0.000,-0.000|


Shape catalog usage (all 132 838 `EQUIPShape`, owned by 32 346 equipment/components):
```sql
SELECT po.RelationName ShapeType, COUNT(*) n FROM dbo.CORERelationOrigin d
JOIN dbo.CORERelationOrigin po ON po.oidTarget=d.oidTarget AND po.RelationType='5280312B-E69C-11D1-A966-080036069A02'
WHERE d.RelationType='80E8EAB6-2D26-44C4-ACCF-1F13DDE339F4' GROUP BY po.RelationName ORDER BY n DESC;
```
```
RectangularSolid 001 61898 | RtCircularCylinder 001 58700 | SemiEllipticalHead 001 3860 | RtCircularCone 001 2896
TruncatedRectangularPrism 001 2222 | EccentricRectangularPrism 001 756 | CircularTori 001 701 | TriangularSolid 001 652
OctogonalSolid 001 475 | RectangularTorus 001 261 | EccentricCone 001 188 | EccentricPyramid 001 92 | TransitionElement 001 41
Sphere 001 39 | Platform1 001 35 | PrismaticShape 001 14 | HexagonalSolid 001 7 | Platform2 001 6 | EccentricTransitionElement 001 6 | DatumShape 001 2
```
What is available per equipment without decoding blobs:
* name, parent system, catalog class (for example `StorageTankAsm`, `GenericAidesAsm`)
* placement matrix: `JEquipment.x0..o3`, identical to `CORESymbol`
* bbox from `CORESpatialIndex`
* nozzles (37 914 on 4 368 equipment): label, global position and direction, NPD + unit, end prep, rating, pipe OD, flange OD/thickness, length
* primitive shapes with A–E parameters and a 4×4 matrix

Shape parameter meanings follow the standard S3D shape symbols. For example:
* `RtCircularCylinder` A = diameter, B = length
* `RectangularSolid` A/B/C = the three sides
* `RtCircularCone` A/B = diameters, C = height

Confirm each parameter's meaning against the symbol once, when you write the IFC mapper.
Smart equipment that is only a parametric catalog symbol (no `EQUIPShape`) has only bbox, matrix and nozzles. 3 698 `EQUIPDesignSolid` bodies are ACIS.

### 5.2 Blob formats (identified, not decoded)

| table | rows (MB) | flags | format |
|---|---|---|---|
| `GEOTOPSolidBody` | 991 733 (5 128 in-row + 1 213 LOB) | `isCompressed=1` on 100 % of a 1 % sample; `blobSize` = uncompressed size (≈15 KB), stored ≈3.5 KB | see below; keyed by CMemberGeometry 240007 (member solids with cuts), 240022, EQUIPDesignSolidGeom, … |
| `GEOTOPWireBody` | 2 006 136 (3 158) | `isCompressed=1` | same; keyed by member part axes / systems (0003A990, 0003A98B …) |
| `GEOTOPSurfaceBody` | 178 924 (544) | `isCompressed=1` | same |
| `COREGraphicDataCache` | 6 255 763 (7 900) | `blobCompressed` 0 for 95.7 % and 1 for 4.3 % (0.5 % sample); `blobVersion=3` | uncompressed: custom little-endian primitive cache; compressed: same wrapper, OLE stream `STREAM_GCACHE` |
| `GEOTOPTopologyMkEngine` | 937 603 | uncompressed | GUID + integer tables; looks like persistent-naming (topology moniker) data, not geometry |
| `CORESite.blob` | 23 659 | – | same PK/Deflate64/OLE wrapper (site metadata) |

First 64 bytes of a `GEOTOPSolidBody.blob` (`0003A987-0000-0000-5909-000DF8582E04`, blobSize 5632, stored 1584):
```
504b01021500150004000900950d944a950d0000ffffffff000000000000000000000000ffff0000000000000000ed575f6c5355183feb2ebda53db7503671a0
P K 01 02 | ver 0x15 | ver 0x15 | flags 0x0004 | METHOD 0x0009 (=Deflate64) | dos time/date 2017-04-20 | … | raw stream starts at byte 46 (0xED = dynamic-Huffman block)
```
* `zlib` raw inflate fails ("invalid distance too far back"), which is the signature of Deflate64. `inflate64` (pip) decodes every sample to exactly `blobSize` bytes.
* The result starts `d0cf11e0a1b11ae1`, an **OLE2 compound file**. Its single stream **`JS_TOPOLOGY_STREAM`** begins
  `ACIS BinaryFile` followed by version 2300 and header strings `Intergraph S3D v2013`, `ACIS 23.0.2 NT`, the timestamp, then 1000.0 (mm per unit), 1e-06 and 1e-10.
* It is standard **ACIS SAB R23**, the same for solid, wire and surface bodies. `ezdxf.acis.sab.parse_sab` reads the record stream (39–181 records per body).
* S3D's writer uses **entity-type name back-references** (`%14`, `%19-%20` …). A small resolver is needed before B-rep tessellation.
* `COREGraphicDataCache` (uncompressed) for pipe `0001388C-…-3B14-0000675A3204` is a 16-byte header `(1,1,1,31)` followed by doubles
  `6042.0338 703.0066 22.7283 | 0 0 -1 | 0.0300 …`, that is a base point, an axis and a radius. It is a simple primitive list, easy to reverse-engineer if ever needed.
* No Parasolid (`PS`/`T51`) or zlib (`78 9c`/`78 da`) signatures were found.

---

## 6. Scale and representability

Counts below are live objects (`persistentFlag & 1024 = 0`). They come from the class histogram (section 1.2), the relation histogram, and:
```sql
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

```

| domain | objects | from plain columns |
|---|---|---|
| piping systems / pipelines / pipe runs | 3 897 / **45 003** / **604 840** | hierarchy, names |
| pipes (`ROUTEPipeOccur`) | **821 935** | **exact** (2 ports + OD + wall) |
| pipe component occurrences | **881 185**. By PCF type: FLANGE 228 485, ELBOW 209 818 (+E90 32 438, E45 2 764), TEE 99 005, VALVE 74 931 (+check 1 594, butterfly 1 486, strainer 173), FLANGE-BLIND 31 688, FSO (slip-on, PDB) 31 609, REDUCER-CONC 30 972, FWN 28 464, REDUCER-ECC 19 193, OLET 18 855 (+NOL 12 964, FLGOL 8 612, WOL 2 175), reinforcing pads ("n/a") 17 630, CAP 8 696, MISC 7 821, other ≈ 15 k | end points + centre + bore + catalog dims → **good parametric** |
| instruments / specialties | 34 961 / 16 725 | end points + F-F + actuator dims → approximate |
| distribution connections / welds / gaskets / bolt sets | 1 581 391 / 1 267 439 / 264 985 / 243 175 | points + descriptions (PCF only) |
| pipe supports / hanger components | 108 156 / 165 524 (122 173 std + 43 351 conn) | CS origin + matrix + catalog assembly → approximate (bbox fallback) |
| pipe ports | 1 725 332 | exact |
| structural systems | 25 154 | |
| linear members (`STRUCTMemberPartPris`) | **880 311**: Beam 454 691, Column 136 482, Brace 119 792, handrail elements 168 508 (post 60 565, handrail 48 004, top rail 26 087, mid rail 19 895, toe plate 13 122, end 835), ladder 818, stair 13, truss 7 | **exact** extrusion (minus end cuts) |
| curved members | 44 009 | chord only; curve needs ACIS wire body |
| footings / footing components / equipment foundations | 43 127 / 68 223 / 419 | symbol + CORESymbol matrix; parameters not verified → approximate |
| slabs / walls / openings | 9 339 / 13 / 52 579 | ACIS only |
| handrail / stair / ladder assemblies | 4 701 / 1 660 / 1 | members covered above |
| equipment (`EQUIPSmartEquipment`) | **29 059**; 4 368 with nozzles; 37 914 nozzles; 132 838 shapes on 32 346 owners; 3 698 design solids | nozzles **exact**, shapes **good parametric**, symbol-only bodies bbox |
| cableway / conduit runs | 8 185 / 4 793 | path features with width/depth → sweep (not done) |

**Fraction of physical objects** (≈ 3.1 M items: pipes, components, instruments, support components, members, footing components,
slabs, shapes, nozzles, cableway):
* **exact from columns: ≈ 1.74 M (56 %)**: pipes, linear members, nozzles
* **good parametric: ≈ 1.07 M (34 %)**: fittings/valves via end points + catalog dims, equipment primitive shapes
* **approximate or bbox-only without ACIS: ≈ 0.30 M (10 %)**: supports, curved members, footings, slabs, symbol-only equipment, cable trays

Decoding ACIS (Deflate64 → OLE → SAB R23) would make structure (cuts), slabs and design solids exact. That would bring coverage close to 100 % except
catalog-symbol bodies (valves, smart equipment, hangers), which S3D never persists as geometry. For those, the graphic cache
(`COREGraphicDataCache`) is the remaining source.

---

## 7. Top risks

1. **Fitting geometry is not stored.** Only ports, centres and catalog parameters are. Elbows, tees, reducers and flanges regenerate well.
   Valves, instruments, specialties and hangers are symbol-defined, so without re-implementing S3D symbols they will be approximate (F-F cylinder/box
   plus operator). `COREGraphicDataCache` primitives are the fallback and need reverse engineering.
2. **Catalog linkage by name.** The moniker (`ProxyOwner.RelationName`) must equal CDB `CORENamedObjects.ObjectName`.
   * 591 catalog proxies (298 occurrences) don't resolve: renamed or deleted catalog items. Emit them with occurrence-level data only.
   * `RelationName` is nvarchar(900). The longest seen is 82 characters, so there is no truncation.
3. **SKEY coverage.** `REFDATPipeMfgMapSymbol` covers 312 part classes. PDS-migrated classes (`FSO`, `NOL`, `*PDB*`, ≈ 60 k
   occurrences) and all instruments/specialties need a fallback map (CommodityType/CommodityClass → PCF type + end-prep suffix).
4. **Ports of fittings are proxies.** End coordinates depend on the part having a `ROUTEDistribConnection` at that port.
   Open ends (unconnected ports) have no coordinate. Fall back to the run's `ROUTEPipeEndPathFeat.Location` or to CORESymbol matrix × catalog port offset.
   Port-name conventions vary (`PNozN`, `NozzleN`); the SQL uses the trailing digits.
5. **`persistentFlag` semantics.** Bit 1024 is "owned/internal". Symbol-output nozzles (417 k) sit in local coordinates and must be excluded.
   Most S3D J-views filter this bit, so do the same. "Copy of …" objects and unassigned "Undefined" systems exist and are real model objects.
6. **Large global coordinates and bad bboxes.** Coordinates reach X 7 355 m, and `CORESpatialIndex` has garbage outliers (up to 1.6e10).
   * Use a local origin for glTF (float32).
   * Clip to the 0.1–99.9 % box.
   * Never trust CORESpatialIndex over computed geometry.
7. **ACIS decoding effort.** The format is fully identified (Deflate64 + OLE2 + SAB R23 with name back-references), but a SAB B-rep tessellator
   is real work: planes, cones and cylinders are easy, while splines and torus surfaces are harder. It is needed for end cuts, slabs and 44 k curved members.
8. **Query cost on the 97 M-row relation table.** Keep every export join seek-based (origin via clustered PK, target via
   `CORERelationDestinationIndex`) and batch per pipeline, run or class. Type-wide `GROUP BY` scans take about 2 min each.
9. **Missing Reports DB and some metadata.**
   * `MLNG@1_RDB` (report templates/BOM views) was not restored. It isn't needed.
   * Instrument `TagNumber` is empty. Use `CORENamedItem`.
   * Cardinal-point semantics and shape A–E parameter meanings must be checked against S3D documentation or a few known objects before bulk IFC generation.

---

## Appendix A: files

* SQL: `/Users/dhiren/Downloads/Deccan/zen2/s3d_sql/`
  * `pipeline_components.sql`
  * `pipeline_connections_supports.sql`
  * `structure_members.sql`
  * `structure_sections.sql`
  * `section_dimensions.sql`
  * `equipment.sql`
  * `scale_pipe_component_types.sql`
  * `tool_neighbourhood.sql` (all relations of an oid, both directions, with names and other-end class; `-v OID=`)
  * `tool_attributes.sql` (all generic attributes of an oid, named; `-v OID=`)
* Raw outputs (S3): `s3://annotationprod/cad-disk-extract/zenitude-data-2/db/s3dmap/`
  * `classmap.txt`, `classhist.txt` (class id → table/name, object histogram)
  * `relmap.txt`, `relhist.txt`, `srelhist.txt` (relation GUID → name, relation histograms)
  * `xview_guid.txt` (all 1 411 X-views → relation GUID)
  * `attrinfo.txt`, `skeymap.txt`
  * `pl_*.txt`, `plcs_*.txt` (pipeline outputs)
  * `st_members*.txt`, `st_sections.txt`, `secdims.txt`
  * `equip.txt`, `shapetypes.txt`, `ptypes.txt`, `ranges.txt`
  * `blobs.txt.gz` (hex of sample blobs)
  * `mdb_views.txt`, `cdb_columns.txt`, `cdb_views.txt`
* To run on the box:
  `sqlcmd -C -S 127.0.0.1 -U sa -d "MLNG@1_MDB" -W -s '|' -v PL=00033457-0000-0000-231E-0173D05A6004 -i pipeline_components.sql`
