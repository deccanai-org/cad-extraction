#!/bin/bash
# Report workspace on the coordinator: /opt/report (venv with PyMuPDF, ezdxf, matplotlib, numpy; system site packages for pythonocc).
# No S3 writes. Idempotent.
set -e
mkdir -p /opt/report/{work,assets,out}
if [ ! -x /opt/report/venv/bin/python ]; then
  /opt/conv/env/bin/python -m venv --system-site-packages /opt/report/venv
fi
/opt/report/venv/bin/python -m pip install -q --disable-pip-version-check pymupdf ezdxf matplotlib 2>&1 | tail -2
/opt/report/venv/bin/python -c "import fitz, ezdxf, matplotlib, numpy; print('fitz', fitz.__doc__.split()[1] if fitz.__doc__ else '?', 'ezdxf', ezdxf.__version__, 'mpl', matplotlib.__version__)"
/opt/report/venv/bin/python -c "from OCC.Core.RWGltf import RWGltf_CafWriter; from OCC.Core.STEPCAFControl import STEPCAFControl_Reader; print('OCC gltf writer ok')"
df -h /opt | tail -1
