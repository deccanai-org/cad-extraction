#!/bin/bash
# Export every table of the five restored S3D databases to JSONL (one JSON object per row, built by SQL Server
# FOR JSON so escaping is exact) -> s3://annotationprod/cad-disk-extract/zenitude-data-2/json/db/<db>/<table>.jsonl.gz
# Binary columns (varbinary/image/timestamp) are left out here and listed in _schema.json; blobs are exported separately.
# Runs on cad-zen2-sql as root (nohup). Parallel: 10 tables at a time, largest first.
set -u
OUT=s3://annotationprod/cad-disk-extract/zenitude-data-2/json/db
W=/data/export; mkdir -p $W
SQLCMD=/opt/mssql-tools18/bin/sqlcmd; BCP=/opt/mssql-tools18/bin/bcp
export SQLCMDPASSWORD="$(cat /root/.mssql_sa)"
LOG=$W/export.log
log() { echo "$(date -u +%FT%TZ) $*" >> $LOG; }
q() { $SQLCMD -C -S 127.0.0.1 -U sa -b -h -1 -W -s $'\t' -Q "SET NOCOUNT ON; $1"; }

log "export start"
for DB in MLNG@1_SDB MLNG@1_SDB_SCHEMA MLNG@1_CDB MLNG@1_CDB_SCHEMA MLNG@1_MDB; do
  safe=${DB//@/_}; mkdir -p $W/$safe
  # table list with row counts, largest first; column lists (non-binary) and binary columns per table
  q "USE [$DB]; SELECT s.name, t.name, SUM(p.rows) FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
     JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0,1) GROUP BY s.name,t.name ORDER BY 3 DESC" > $W/$safe/_tables.tsv
  q "USE [$DB]; SELECT s.name, t.name, c.name, ty.name, c.column_id FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
     JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id ORDER BY s.name,t.name,c.column_id" > $W/$safe/_columns.tsv
  log "$DB: $(wc -l < $W/$safe/_tables.tsv) tables"
done

one() {   # $1=DB $2=schema $3=table $4=rows
  DB=$1; S=$2; T=$3; R=$4; safe=${DB//@/_}
  cols=$(awk -F'\t' -v s="$S" -v t="$T" '$1==s && $2==t && $4!="varbinary" && $4!="image" && $4!="timestamp" && $4!="binary" && $4!="geometry" && $4!="geography" && $4!="hierarchyid" {printf "%st.[%s]", (n++?",":""), $3}' $W/$safe/_columns.tsv)
  [ -z "$cols" ] && return
  f="$W/$safe/${S}.${T}.jsonl"
  $BCP "SELECT (SELECT $cols FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES) FROM [$DB].[$S].[$T] t" queryout "$f" \
      -c -C 65001 -r '\n' -S 127.0.0.1 -U sa -P "$SQLCMDPASSWORD" -u -a 65535 > "$f.bcp.log" 2>&1
  rc=$?
  n=$(wc -l < "$f" 2>/dev/null || echo 0)
  gzip -1 -f "$f" && aws s3 cp --only-show-errors "$f.gz" "$OUT/$safe/${S}.${T}.jsonl.gz" && rm -f "$f.gz"
  log "$DB.$S.$T rows=$R exported=$n rc=$rc"
}
export -f one log; export W OUT BCP LOG

for DB in MLNG@1_SDB MLNG@1_SDB_SCHEMA MLNG@1_CDB MLNG@1_CDB_SCHEMA MLNG@1_MDB; do
  safe=${DB//@/_}
  awk -F'\t' -v db="$DB" 'NF==3 {print db, $1, $2, $3}' $W/$safe/_tables.tsv
done > $W/_tasks.txt
log "tasks: $(wc -l < $W/_tasks.txt)"
xargs -P 10 -L 1 bash -c 'one "$0" "$1" "$2" "$3"' < $W/_tasks.txt

# schema files (columns + which binary columns were left out) next to the data
for DB in MLNG@1_SDB MLNG@1_SDB_SCHEMA MLNG@1_CDB MLNG@1_CDB_SCHEMA MLNG@1_MDB; do
  safe=${DB//@/_}
  python3 - "$W/$safe" <<'PY'
import json, sys, collections
d = sys.argv[1]
tabs = collections.OrderedDict()
for l in open(d + '/_tables.tsv'):
    p = l.rstrip('\n').split('\t')
    if len(p) == 3: tabs[f'{p[0]}.{p[1]}'] = {'rows': int(p[2]), 'columns': [], 'binary_columns_not_in_jsonl': []}
for l in open(d + '/_columns.tsv'):
    p = l.rstrip('\n').split('\t')
    if len(p) < 4: continue
    k = f'{p[0]}.{p[1]}'
    if k not in tabs: continue
    if p[3] in ('varbinary', 'image', 'timestamp', 'binary', 'geometry', 'geography', 'hierarchyid'):
        tabs[k]['binary_columns_not_in_jsonl'].append({'name': p[2], 'type': p[3]})
    else:
        tabs[k]['columns'].append({'name': p[2], 'type': p[3]})
json.dump(tabs, open(d + '/_schema.json', 'w'), indent=1)
PY
  aws s3 cp --only-show-errors $W/$safe/_schema.json $OUT/$safe/_schema.json
done
log "export DONE: $(grep -c ' exported=' $LOG) tables"
aws s3 cp --only-show-errors $LOG $OUT/_export.log
