# build the kit's conversion env on this box (/opt/conv/env: ifcopenshell 0.9.0 + pythonocc; /opt/conv/ifc84: ifcopenshell 0.8.4.post1)
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/db1/setup.sh /opt/v2/setup_kit.sh
bash /opt/v2/setup_kit.sh /opt/conv
/opt/conv/env/bin/python -c "import ifcopenshell, OCC, numpy; print('env ok', ifcopenshell.version)"
/opt/conv/env/bin/pip install -q scipy > /dev/null 2>&1 || true
touch /opt/v2/ENV_READY
