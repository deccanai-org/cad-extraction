aws s3 cp --region ap-south-1 --recursive --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/src/ /opt/db1v2/src3/
aws s3 cp --region ap-south-1 --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/layouts.json /opt/db1v2/
cd /opt/db1v2/src3 && python3.11 test_final.py 2>&1 | grep -v -i warn | tail -4 | cut -c1-700
