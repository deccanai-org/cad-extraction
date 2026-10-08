export LD_LIBRARY_PATH=/data/s3d/env/lib
find /data/s3d/env -name "*mesa*.json" 2>/dev/null | head
J=$(find /data/s3d/env -name "50_mesa.json" | head -1)
export __EGL_VENDOR_LIBRARY_FILENAMES=$J
export LIBGL_DRIVERS_PATH=/data/s3d/env/lib/dri
PYOPENGL_PLATFORM=egl EGL_PLATFORM=surfaceless /data/s3d/env/bin/python -c "
from pyrender.platforms import egl as pegl
devs = pegl.query_devices(); print('devices', len(devs))
if not devs: pegl.get_device_by_index = lambda i: pegl.EGLDevice(None)
import pyrender, trimesh, numpy as np, time
t=time.time()
r=pyrender.OffscreenRenderer(800,600); s=pyrender.Scene(ambient_light=[.3,.3,.3]); s.add(pyrender.Mesh.from_trimesh(trimesh.creation.box()));
c=pyrender.OrthographicCamera(2,2); s.add(c, pose=np.array([[1,0,0,0],[0,1,0,0],[0,0,1,5],[0,0,0,1.]])); s.add(pyrender.DirectionalLight(), pose=np.eye(4))
col,d=r.render(s); print('egl render ok', col.shape, col.mean(), time.time()-t)
from OpenGL import GL; print(GL.glGetString(GL.GL_RENDERER))
" 2>&1 | tail -6
