"""modal_image.py - the src_sds2 stage image for the app's plug-in loader (contract of app/pmpstages/plugins.py:
build(modal, root) -> modal.Image).

It is modal_sds2.sds2_image() itself (single source of truth: converter env /opt/conv, proof env /opt/pipe, the 18
sha256-checked converter zips at /opt/sds2_converters, and this component's code at /pmp/src_sds2). Because that image
already holds the component code, INCLUDES_COMPONENT tells the app not to add the folder a second time (the converter
zips would otherwise be mounted twice).
"""
import importlib.util
import os

INCLUDES_COMPONENT = True


def build(modal, root):
    path = os.path.join(str(root), 'modal_sds2.py')
    spec = importlib.util.spec_from_file_location('pmp_src_sds2_modal_sds2', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.sds2_image()
