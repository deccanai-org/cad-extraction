"""Headless renderer: triangles -> area-sampled points -> orthographic z-buffer with Lambert shading and depth edges.
No GPU or display needed (runs on EC2). Deterministic (seeded sampling). Output: PNG panels for people and the VLM."""
import math, re
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from . import config as C

PLATE_RE = re.compile(r"^(PL|FL|FB|BL|PLT|FLT|PLATE|BPL|FPL|FLAT|GRTG|GRATING|CHKPL|BPLT)", re.I)
COL_MEMBER = np.array([70, 110, 165]); COL_PLATE = np.array([215, 135, 55]); COL_OTHER = np.array([130, 130, 130])
COL_MISS = np.array([200, 40, 40]); COL_OK = np.array([60, 150, 80]); COL_NEAR = np.array([225, 185, 30])

VIEWS = {"iso": (-60, 30), "plan": (-90, 90), "front": (-90, 0), "side": (0, 0), "iso_back": (120, 30)}


def part_colors(names, classes=None):
    out = []
    for i, n in enumerate(names):
        c = (classes[i] if classes else None)
        if c == "IfcPlate" or (c is None and PLATE_RE.match(n or "")): out.append(COL_PLATE)
        elif c in (None, "IfcBeam", "IfcColumn", "IfcMember"): out.append(COL_MEMBER)
        else: out.append(COL_OTHER)
    return np.array(out).reshape(-1, 3)


def sample(tris, owner, n_points=C.RENDER_POINTS, seed=C.SEED):
    """-> points (N,3), normals (N,3), owner index (N,)"""
    if len(tris) == 0: return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0, int)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cr = np.cross(b - a, c - a); area = 0.5 * np.linalg.norm(cr, axis=1)
    nrm = cr / np.maximum(2 * area, 1e-12)[:, None]
    rng = np.random.default_rng(seed)
    dens = n_points / max(area.sum(), 1e-9)
    k = np.floor(area * dens).astype(np.int64); k += rng.random(len(k)) < (area * dens - k)
    k = np.minimum(k, 2000) + 1                                     # +1: every triangle shows up, however thin
    idx = np.repeat(np.arange(len(tris)), k)
    r1 = np.sqrt(rng.random(len(idx))); r2 = rng.random(len(idx))
    P = (1 - r1)[:, None] * a[idx] + (r1 * (1 - r2))[:, None] * b[idx] + (r1 * r2)[:, None] * c[idx]
    return P, nrm[idx], owner[idx]


def _basis(az, el):
    az, el = math.radians(az), math.radians(el)
    cam = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    fwd = -cam
    up0 = np.array([0, 0, 1.0]) if abs(el) < math.radians(89) else np.array([0, 1.0, 0])
    right = np.cross(fwd, up0); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return right, up, fwd


def view(P, N, col, az, el, W=C.RENDER_W, H=C.RENDER_H, frame=None, margin=0.04):
    """-> uint8 image (H,W,3). frame: (lo, hi) world box the view must fit (shared between compared renders)."""
    img = np.full((H, W, 3), 255, np.uint8)
    if len(P) == 0: return img
    right, up, fwd = _basis(az, el)
    if frame is None: frame = (P.min(0), P.max(0))
    lo, hi = np.asarray(frame[0], float), np.asarray(frame[1], float)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    cu, cv = corners @ right, corners @ up
    span = max((cu.max() - cu.min()) / (W * (1 - 2 * margin)), (cv.max() - cv.min()) / (H * (1 - 2 * margin)), 1e-9)
    u0, v0 = (cu.max() + cu.min()) / 2, (cv.max() + cv.min()) / 2
    x = ((P @ right - u0) / span + W / 2).astype(np.int64)
    y = (H / 2 - (P @ up - v0) / span).astype(np.int64)
    d = P @ fwd
    ok = (x >= 0) & (x < W) & (y >= 0) & (y < H)
    x, y, d, Nn, cc = x[ok], y[ok], d[ok], N[ok], col[ok]
    pix = y * W + x
    order = np.lexsort((d, pix)); pix_s = pix[order]
    first = order[np.r_[True, pix_s[1:] != pix_s[:-1]]]
    light = -fwd * 0.75 + up * 0.35 + right * 0.2; light /= np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.abs(Nn[first] @ light)
    rgb = np.clip(cc[first] * shade[:, None], 0, 255)
    D = np.full(H * W, np.inf); D[pix[first]] = d[first]
    flat = img.reshape(-1, 3); flat[pix[first]] = rgb.astype(np.uint8)
    D = D.reshape(H, W)
    # fill single-pixel holes from the nearest-depth neighbour
    filled = np.isfinite(D)
    best = np.full((H, W), np.inf); src = np.zeros((H, W, 3), np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0: continue
            Ds = np.roll(np.roll(D, dy, 0), dx, 1); Is = np.roll(np.roll(img, dy, 0), dx, 1)
            m = Ds < best; best[m] = Ds[m]; src[m] = Is[m]
    hole = ~filled & np.isfinite(best)
    nb = sum(np.roll(np.roll(filled, dy, 0), dx, 1).astype(int) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
    hole &= nb >= 4
    img[hole] = src[hole]; D[hole] = best[hole]
    # depth edges: silhouettes and part boundaries
    scale = max(np.linalg.norm(hi - lo), 1.0)
    Dm = np.where(np.isfinite(D), D, np.nanmax(np.where(np.isfinite(D), D, -np.inf)) + scale)
    gx = np.abs(np.diff(Dm, axis=1, prepend=Dm[:, :1])); gy = np.abs(np.diff(Dm, axis=0, prepend=Dm[:1]))
    edge = (np.maximum(gx, gy) > scale * 0.004) & (np.isfinite(D) | np.isfinite(np.roll(D, 1, 0)))
    img[edge] = (img[edge] * 0.35).astype(np.uint8)
    return img


def _font(sz):
    for f in ("arial.ttf", "DejaVuSans.ttf"):
        try: return ImageFont.truetype(f, sz)
        except Exception: pass
    return ImageFont.load_default()


def panel_sheet(panels, cols, title, path, footer=None):
    """panels: [(label, image)] -> one PNG with labels"""
    H, W = panels[0][1].shape[:2]; rows = -(-len(panels) // cols); th = 34; fh = 26 if footer else 0
    sheet = Image.new("RGB", (cols * W, rows * H + th + fh), "white"); dr = ImageDraw.Draw(sheet)
    dr.text((8, 6), title, fill=(20, 20, 20), font=_font(18))
    for k, (lab, im) in enumerate(panels):
        r, c = divmod(k, cols); sheet.paste(Image.fromarray(im), (c * W, th + r * H))
        dr.rectangle([c * W, th + r * H, c * W + W - 1, th + r * H + H - 1], outline=(200, 200, 200))
        dr.text((c * W + 8, th + r * H + 6), lab, fill=(40, 40, 40), font=_font(15))
    if footer: dr.text((8, th + rows * H + 4), footer, fill=(60, 60, 60), font=_font(13))
    sheet.save(path, optimize=True)
    return path


def core_frame(P, lo_pct=0.5, hi_pct=99.5, pad=0.03):
    lo, hi = np.percentile(P, lo_pct, axis=0), np.percentile(P, hi_pct, axis=0)
    ext = np.maximum(hi - lo, 1.0)
    return lo - ext * pad, hi + ext * pad
