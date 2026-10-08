#!/bin/bash
# Repro of the 6.1.0-dev3 / 6.1.0-rc kernel memory blow-up (patch E) on an agent box (BOX-A), and its fix.
# Needs /opt/conv/env/bin/python (ifcopenshell 0.9.0 + pythonocc). Reads only; writes under $W.
#   bash repro_seaport.sh single   # ~1 min: the one product, every kernel setting in a child capped at 12 GB address space
#   bash repro_seaport.sh full     # whole model, dev3+vr converter (bounded) - DO NOT run dev3 on the whole model without a
#                                  # memory cap: it reached 173 GB RSS within ~10 min of the kernel pass (killed)
set -e
export AWS_DEFAULT_REGION=ap-south-1
W=${W:-/work/agentwork/ifc-verification-residue/repro}; mkdir -p $W; cd $W
P=/opt/conv/env/bin/python
PF=s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/pfix/ifc-verification-residue
DEV3=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcv6/ifc2step6_dev3.py
for f in ifc2step6_dev3+vr.py variant_test.py; do [ -f $f ] || aws s3 cp --quiet $PF/$f $f; done
[ -f ifc2step6_dev3.py ] || aws s3 cp --quiet $DEV3 ifc2step6_dev3.py
# input: data-3 Seaport L4 (SDS/2), sha256 beeeacea7d2d75461797f506103e1e344d94c775204e0163f879af4ffafb1532, 18,916,537 B (zip)
if [ ! -f seaport.ifc ]; then
  aws s3 cp --quiet "s3://bim-proprietary-data/cad-disk-extract/dataset/main/3d/Disk-1__TEKLA-HYD_JOBS-2015-2016_10.10.40.51_Server_Backup_SDS2-TEAM_SDS-PROJECTS_033_CIVES_NEWENGLAND_033_CIVES_NEWENGLAND_Part2.7z/model/ifc/Seaport_L4_Job-24acbb.ifc" seaport.bin
  $P -c "import zipfile,shutil; z=zipfile.ZipFile('seaport.bin'); m=max(z.infolist(),key=lambda i:i.file_size); shutil.copyfileobj(z.open(m),open('seaport.ifc','wb'),1<<24)"
fi
case "${1:-single}" in
single)
  # product a3717 (IfcMember L2x2x3/8, eid 8935, GlobalId 02dnNiHvr9xext7h6RlJ8V): IfcFacetedBrep (12 faces) minus 2 openings
  # (IfcFacetedBrep hole prisms, 18 faces). Expected (measured 2026-10-02 00:55Z):
  #   poly_dev3        rc 1  (create_shape exceeds the 12 GB cap: "RuntimeError: An unknown error occurred" = bad_alloc)
  #   tri_mesh         rc 0  0.14 s, 172 triangles, 1 solid, 343,261 mm3
  #   poly_no_openings rc 0  0.04 s, 12 faces, 352,670 mm3 (openings not applied - reference only)
  #   poly_bool2d_off / poly_no_weld: rc 1 like poly_dev3; tri_bool2d_off: like tri_mesh
  $P variant_test.py ifc2step6_dev3.py seaport.ifc 02dnNiHvr9xext7h6RlJ8V --cap-gb 12 --timeout 150
  ;;
full)
  # dev3+vr: the 8,025 kernel products (openings) as triangle meshes; peak RSS ~1.3 GB through the kernel pass
  ( ulimit -v $((48 << 20)); $P ifc2step6_dev3+vr.py seaport.ifc seaport_vr.step --mode hybrid --prec 2 --threads 4 ) 2>&1 | tail -30
  ;;
esac
