import sys, numpy as np, collections, ifcopenshell, ifcopenshell.geom
sys.path.insert(0,'src'); from vol_compare import vols
cut = vols('pairs/data/7.82_c73731fe0d_db1.ifc', only_csg=True)
nocut = vols('pairs/data/7.82_c73731fe0d_nocut.ifc'); ref = vols('pairs/data/7.82_c73731fe0d.ifc')
R = np.array([c for _, c, _ in ref]); RV = np.array([v for v, _, _ in ref])
N = np.array([c for _, c, _ in nocut]); NV = np.array([v for v, _, _ in nocut])
better = worse = same = 0; rows = []
for vol, cen, g in cut:
    # the same member without cuts: nearest centroid in the no-cut model (cut shifts centroid slightly)
    k = int(np.argmin(np.linalg.norm(N - cen, axis=1)))
    # reference element: nearest to the uncut centroid
    j = int(np.argmin(np.linalg.norm(R - cen, axis=1)))
    e_cut = abs(vol - RV[j]) / RV[j]; e_no = abs(NV[k] - RV[j]) / RV[j]
    rows.append((e_cut, e_no))
    if e_cut < e_no - 1e-4: better += 1
    elif e_cut > e_no + 1e-4: worse += 1
    else: same += 1
rows = np.array(rows)
print('with cuts median err', round(float(np.median(rows[:, 0])), 5), 'without cuts median err', round(float(np.median(rows[:, 1])), 5), '| better', better, 'worse', worse, 'same', same)
