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
