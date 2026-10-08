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
