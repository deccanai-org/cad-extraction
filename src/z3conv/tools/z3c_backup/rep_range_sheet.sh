#!/bin/bash
/opt/report/venv/bin/python - <<'PY'
import json, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt, matplotlib.image as mpimg
m = json.load(open('/opt/report/assets/range/range.json'))
fig, axs = plt.subplots(5, 4, figsize=(32, 30))
for ax, r in zip(axs.flat, m):
    ax.imshow(mpimg.imread(f"/opt/report/assets/range/r{r['n']:02d}.jpg")); ax.axis('off')
    ax.set_title(f"r{r['n']:02d} {r['disk']} {r['relpath'].rsplit('/',1)[-1][:40]}", fontsize=14)
plt.tight_layout(); plt.savefig('/opt/report/assets/range/contact.jpg', dpi=50)
print('ok')
PY
