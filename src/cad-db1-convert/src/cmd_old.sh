aws s3 cp --region ap-south-1 --recursive --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/src/ /opt/db1v2/src3/
cd /opt/db1v2/src3 && python3.11 test_old.py /opt/db1v2/pairs/7.24_7ea1f75396.db1 /opt/db1v2/pairs/6.87_62ae06d8ad.db1 2>&1 | grep -v -i warn | tail -4 | cut -c1-600
