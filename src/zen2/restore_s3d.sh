#!/bin/bash
# Restore the five S3D databases from the Zenitude-data-2 backup set on the cad-zen2-sql box (run as root via SSM).
# Step 1: RESTORE HEADERONLY / FILELISTONLY for every backup set -> db/headers/
# Step 2: RESTORE each set under its original name with files moved to /data/mssql -> db/restore.log
# Step 3: inventory (db sizes, tables, row counts, views) -> db/inventory/
# The SA password is passed through SQLCMDPASSWORD only (never on the command line, never logged).
set -u
OUT=s3://annotationprod/cad-disk-extract/zenitude-data-2/db
W=/data/work/restore; mkdir -p $W/headers $W/inventory
SQLCMD=$(ls /opt/mssql-tools18/bin/sqlcmd /opt/mssql-tools/bin/sqlcmd 2>/dev/null | head -1)
export SQLCMDPASSWORD="$(cat /root/.mssql_sa)"
q()  { $SQLCMD -C -S 127.0.0.1 -U sa -b -W -s '|' -Q "SET NOCOUNT ON; $1"; }
qt() { $SQLCMD -C -S 127.0.0.1 -U sa -b -W -s $'\t' -h -1 -Q "SET NOCOUNT ON; $1"; }
log() { echo "$(date -u +%FT%TZ) $*" | tee -a $W/restore.log; }

# backup file | set number | database name
SETS="MLNG@1_SDB_SiteBackup.dat|1|MLNG@1_SDB
MLNG@1_SDB_SiteBackup.dat|2|MLNG@1_SDB_SCHEMA
PLC_CatalogBackup.dat|1|MLNG@1_CDB
PLC_CatalogBackup.dat|2|MLNG@1_CDB_SCHEMA
PLC_Model_Backup.dat|1|MLNG@1_MDB"

log "restore start on $(hostname); $(q 'SELECT @@VERSION' | sed -n 3p | cut -c1-100)"
for f in MLNG@1_SDB_SiteBackup.dat PLC_CatalogBackup.dat PLC_Model_Backup.dat; do
  log "file /data/in/$f $(stat -c %s /data/in/$f) B"
  q "RESTORE HEADERONLY FROM DISK = N'/data/in/$f'" > "$W/headers/${f%.dat}.headeronly.txt" 2>&1
  log "headeronly rc=$? -> headers/${f%.dat}.headeronly.txt"
done

echo "$SETS" | while IFS='|' read -r f n db; do
  q "RESTORE FILELISTONLY FROM DISK = N'/data/in/$f' WITH FILE = $n" > "$W/headers/${db}.filelist.txt" 2>&1
  # logical name + type (D/L) from the tab-separated form
  MOVES=$(qt "RESTORE FILELISTONLY FROM DISK = N'/data/in/$f' WITH FILE = $n" | awk -F'\t' -v db="$db" '
    NF>3 && ($3=="D" || $3=="L") { ext = ($3=="L") ? "ldf" : "mdf"; safe=db; gsub(/@/,"_",safe);
      printf "%sMOVE N'\''%s'\'' TO N'\''/data/mssql/%s__%s.%s'\''", (c++ ? ", " : ""), $1, safe, $1, ext }')
  if [ -z "$MOVES" ]; then log "ERROR no file list for $db ($f set $n)"; continue; fi
  if [ "$(qt "SELECT COUNT(*) FROM sys.databases WHERE name = N'$db'")" = "1" ]; then log "skip $db (already restored)"; continue; fi
  log "restoring $db from $f set $n"
  T0=$(date +%s)
  q "RESTORE DATABASE [$db] FROM DISK = N'/data/in/$f' WITH FILE = $n, $MOVES, RECOVERY, STATS = 10" >> $W/restore.log 2>&1
  log "restore $db rc=$? in $(( $(date +%s)-T0 )) s"
done

# Inventory
q "SELECT d.name, d.state_desc, d.compatibility_level, d.collation_name, CAST(SUM(mf.size)*8/1024.0 AS DECIMAL(12,1)) AS size_mb
   FROM sys.databases d JOIN sys.master_files mf ON mf.database_id=d.database_id WHERE d.name LIKE 'MLNG@1%' GROUP BY d.name,d.state_desc,d.compatibility_level,d.collation_name" > $W/inventory/databases.txt 2>&1
for db in MLNG@1_SDB MLNG@1_SDB_SCHEMA MLNG@1_CDB MLNG@1_CDB_SCHEMA MLNG@1_MDB; do
  safe=${db//@/_}
  qt "USE [$db]; SELECT s.name, t.name, SUM(p.rows) FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
      JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0,1) GROUP BY s.name,t.name ORDER BY SUM(p.rows) DESC" > $W/inventory/${safe}.tables.tsv 2>&1
  qt "USE [$db]; SELECT s.name, v.name FROM sys.views v JOIN sys.schemas s ON s.schema_id=v.schema_id ORDER BY 1,2" > $W/inventory/${safe}.views.tsv 2>&1
  qt "USE [$db]; SELECT s.name, t.name, c.name, ty.name, c.max_length FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
      JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id ORDER BY 1,2,c.column_id" > $W/inventory/${safe}.columns.tsv 2>&1
  log "inventory $db: $(wc -l < $W/inventory/${safe}.tables.tsv) tables, $(wc -l < $W/inventory/${safe}.views.tsv) views"
done
aws s3 cp --region ap-south-1 --recursive --quiet $W $OUT/
log "restore script done; uploaded to $OUT/"
aws s3 cp --region ap-south-1 --quiet $W/restore.log $OUT/restore.log
