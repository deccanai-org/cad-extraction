SET NOCOUNT ON;
SELECT TABLE_NAME, STRING_AGG(COLUMN_NAME + ':' + DATA_TYPE, ', ') WITHIN GROUP (ORDER BY ORDINAL_POSITION) cols
FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME IN
('ROUTEPipeRun','SHPCONPipelineSystem','SHPCONPipingSystem','ROUTEPipeOccur','ROUTEPipeComponentOcc','ROUTEPipePort','ROUTEDistribConnection',
 'ROUTEPipeTurnPathFeat','ROUTEPipeBranchPathFeat','ROUTEPipeStraightPathFeat','ROUTEPipeEndPathFeat','ROUTEPipeAlongLegPathFeat',
 'STRUCTMemberPartAxisLin','STRUCTPartPrismaticGen','STRUCTMemberPartPris','EQUIPSmartEquipment','JEquipment','EQUIPPipeNozzle','CORESymbol',
 'HNGSUPHgrPipeSupport','GRDSYSSPGCoordinateSystem','ROUTEPipeWeld','ROUTEPipeGasket','ROUTEPipeBoltSet','ROUTEPipeInstrumentOcc','ROUTEPipeSpecialtyOcc',
 'EQUIPShape','HNGSUPHgrStdComponent','HNGSUPHgrConnComponent','CORESpatialIndex','CORENamedItem','REFDATPipeComponent','STRUCTMemberSysLinear','EQUIPDesignSolid',
 'STRUCTMemberPartCurve','STRUCTSlab','STRUCTFooting','STRUCTFootingComponent','ROUTEPipeValveOperatorOcc','EQUIPEquipmentComponent','COREGraphicDataCache','GEOTOPSolidBody')
GROUP BY TABLE_NAME;
