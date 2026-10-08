#!/bin/bash
set -e
mkdir -p /data/s3d/{src,work,out,logs,jobs,tmp}
cd /data/s3d
cat > /data/s3d/setup_env_inner.sh <<'INNER'
#!/bin/bash
set -x
export MAMBA_ROOT_PREFIX=/data/s3d/mamba
cd /data/s3d
if [ ! -x /data/s3d/micromamba ]; then
  curl -sSL -o /data/s3d/micromamba https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64
  chmod 755 /data/s3d/micromamba
fi
/data/s3d/micromamba create -y -p /data/s3d/env -c conda-forge python=3.11 ifcopenshell pythonocc-core numpy lark pyodbc unixodbc trimesh pygltflib boto3 scipy networkx shapely mesalib pyopengl pillow matplotlib olefile rtree
/data/s3d/env/bin/pip install inflate64 pyrender ezdxf pymssql
/data/s3d/env/bin/python -c "import ifcopenshell,OCC,pyodbc,trimesh;print('ENV_OK', ifcopenshell.version)"
ls /data/s3d/env/bin/ | grep -i ifc
echo SETUP_DONE
INNER
chmod +x /data/s3d/setup_env_inner.sh
setsid nohup /data/s3d/setup_env_inner.sh > /data/s3d/logs/setup_env.log 2>&1 < /dev/null &
echo started
aws s3 ls s3://annotationprod/cad-disk-extract/zenitude-data-2/png/ | head -5
aws s3 ls s3://annotationprod/cad-disk-extract/zenitude-data-2/json/ | head -5
aws s3 ls s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/ | head -20
aws s3 ls s3://annotationprod/cad-disk-extract/zenitude-data-2/db/s3dmap/ | head -50
