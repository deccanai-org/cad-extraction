aws s3 cp --region ap-south-1 --recursive --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/src/ /opt/db1v2/src/
aws s3 cp --region ap-south-1 --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/layouts.json /opt/db1v2/
cd /opt/db1v2/src && (nohup python3.11 run_val_subset.py 9.08 7.98 8.37 8.53_347 8.53_478 8.53_943 8.85 8.65 > /opt/db1v2/val6.out 2>&1 &); echo started
