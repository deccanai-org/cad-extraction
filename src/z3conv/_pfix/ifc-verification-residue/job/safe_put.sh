#!/bin/bash
# safe_put.sh LOCAL_FILE S3_DEST : upload only under this agent's own prefixes; echoes the destination first
SRC="$1"; DST="$2"
case "$DST" in
  s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/*|\
  s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/pfix/ifc-verification-residue/*) ;;
  *) echo "REFUSED: destination outside own prefixes: $DST" >&2; exit 2;;
esac
[ -f "$SRC" ] || { echo "REFUSED: local source missing: $SRC" >&2; exit 2; }
echo "PUT $SRC -> $DST"
AWS_PROFILE=annotationprod-publish aws s3 cp --quiet "$SRC" "$DST"
