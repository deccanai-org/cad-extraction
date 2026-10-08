cd /opt/ph/probe
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc/fix
aws s3 cp --region ap-south-1 --quiet $C/regen_step.py /opt/ph/probe/regen_step.py
aws s3 cp --region ap-south-1 --quiet $C/ifc_nobbox_keys.txt /opt/ph/probe/ifc_nobbox_keys.txt
( /opt/ifc84/bin/python /opt/ph/probe/regen_step.py b5e0694a4b02a8ecced6c4128b00d8a941e23756574f6a8959a45bc178df7d1e 9c2e39cb0fcfc14665403bc76e27aba7c3a17e7578f1c5c448824856d8dadda2 > /opt/ph/probe/regen.log 2>&1; echo "regen rc=$?" >> /opt/ph/probe/regen.log; aws s3 cp --region ap-south-1 --quiet /opt/ph/probe/regen.log $C/regen.log ) &
scan() { n=$(aws s3 cp --region ap-south-1 --quiet "s3://annotationprod/$1" - | grep -a -c -E "CARTESIAN_POINT\('',\([^)]*[eE]\+?(1[0-9]|[2-9][0-9]|[1-9][0-9][0-9])[,)]"); echo "$n $1"; }
export -f scan
xargs -P 12 -I{} bash -c 'scan "$@"' _ {} < /opt/ph/probe/ifc_nobbox_keys.txt > /opt/ph/probe/ifc_scan.txt 2>&1
aws s3 cp --region ap-south-1 --quiet /opt/ph/probe/ifc_scan.txt $C/ifc_scan.txt
wait
echo FIX-DONE > /opt/ph/probe/fix.done; aws s3 cp --region ap-south-1 --quiet /opt/ph/probe/fix.done $C/fix.done
