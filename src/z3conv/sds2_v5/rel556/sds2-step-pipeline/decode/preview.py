"""Quick isometric preview of decoded member work lines (from *_members.csv) -> PNG."""
import sys, csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection

rows = list(csv.DictReader(open(sys.argv[1])))
col = {"BEAM": "#2b6cb0", "COLUMN": "#c53030", "VERTICAL BRACE": "#2f855a", "PL GIRDER": "#6b46c1", "MISC": "#a0aec0"}
fig = plt.figure(figsize=(12, 9), dpi=110)
ax = fig.add_subplot(projection="3d")
for t, c in col.items():
    segs = [[(float(r["x1"]), float(r["y1"]), float(r["z1"])), (float(r["x2"]), float(r["y2"]), float(r["z2"]))]
            for r in rows if r["type"] == t and r["solid"] == "1"]
    if segs:
        ax.add_collection3d(Line3DCollection(segs, colors=c, linewidths=0.6 if t != "MISC" else 0.3, label=f"{t} ({len(segs)})"))
xs = [float(r[k]) for r in rows if r["solid"] == "1" for k in ("x1", "x2")]
ys = [float(r[k]) for r in rows if r["solid"] == "1" for k in ("y1", "y2")]
zs = [float(r[k]) for r in rows if r["solid"] == "1" for k in ("z1", "z2")]
ax.set_xlim(min(xs), max(xs)); ax.set_ylim(min(ys), max(ys)); ax.set_zlim(min(zs), max(zs))
ax.set_box_aspect((max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))
ax.view_init(elev=22, azim=-60)
ax.set_axis_off()
ax.legend(loc="upper left")
ax.set_title(sys.argv[3] if len(sys.argv) > 3 else "decoded SDS2 members")
plt.tight_layout()
plt.savefig(sys.argv[2])
print("saved", sys.argv[2])
