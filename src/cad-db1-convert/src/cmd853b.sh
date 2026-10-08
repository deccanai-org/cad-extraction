aws s3 cp --region ap-south-1 --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/src/dbg853b.py /opt/db1v2/src/
cd /opt/db1v2/src && python3.11 dbg853b.py 2>&1 | grep -v -i warn | tail -14
