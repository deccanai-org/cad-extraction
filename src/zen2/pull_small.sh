set -e
SRC="s3://annotationprod/cad-disk-extract/zenitude-data-2/source/PLC 17072025"
cd /data/in
for f in PLC.bcf PLCBackup.log PLCRestore.log MLNG@1_SDB_SiteBackup.dat PLC_CatalogBackup.dat; do aws s3 cp --region ap-south-1 --only-show-errors "$SRC/$f" "/data/in/$f"; done
chown -R mssql:mssql /data/in; ls -la /data/in
