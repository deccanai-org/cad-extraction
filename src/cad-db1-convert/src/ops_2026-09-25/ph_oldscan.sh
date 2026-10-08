cd /opt/ph/probe
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc/fix
aws s3 cp --region ap-south-1 --quiet $C/old_ok_step_keys.txt /opt/ph/probe/old_ok_step_keys.txt
scan() { n=$(aws s3 cp --region ap-south-1 --quiet "s3://annotationprod/$1" - | grep -a -c -E "CARTESIAN_POINT\('[^']*',\([^)]*([eE]\+?0*(1[0-9]|[2-9][0-9]|[1-9][0-9][0-9])|[(,-][0-9]{11,})"); echo "$n $1"; }
export -f scan
xargs -P 16 -I{} bash -c 'scan "$@"' _ {} < /opt/ph/probe/old_ok_step_keys.txt > /opt/ph/probe/old_scan.txt 2>&1
aws s3 cp --region ap-south-1 --quiet /opt/ph/probe/old_scan.txt $C/old_scan.txt
