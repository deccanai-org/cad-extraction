aws s3 cp --region ap-south-1 --quiet s3://annotationprod/cad-disk-extract/_control/db1-v2/src/yv_check.py /opt/db1v2/src/
cd /opt/db1v2/src && python3.11 yv_check.py 8.53_347eb7c4bd 8.53_0575f7270f 8.53_4784257112 8.53_943ee59f0a 2>&1 | grep -v -i warn | tail -4
