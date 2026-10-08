set -x
mkdir -p /opt/ph && cd /opt/ph
aws s3 cp --region ap-south-1 --quiet s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc/pkg_posthoc_run.py /opt/ph/pkg_posthoc_run.py
echo test > /tmp/ph_del_test.txt
aws s3 cp --region ap-south-1 --quiet /tmp/ph_del_test.txt s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc/del_test.txt && aws s3 rm --region ap-south-1 s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc/del_test.txt && echo DELETE_OK || echo DELETE_DENIED
PKG_SOURCES=db1 PKG_STATE=cad-disk-extract/_control/packaging/step_v1_db1_posthoc THREADS=64 python3 /opt/ph/pkg_posthoc_run.py plan > /opt/ph/plan.log 2>&1; echo rc=$?
tail -5 /opt/ph/plan.log
aws s3 cp --region ap-south-1 --quiet /opt/ph/plan.log s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc/plan.log
