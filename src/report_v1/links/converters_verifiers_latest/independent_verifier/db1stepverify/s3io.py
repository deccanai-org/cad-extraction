"""S3 side: conversion records, the STEP object, the input .db1 (with a fallback into the original disk bucket),
and Tekla IFC exports stored next to the .db1 (independent ground truth)."""
import os, re, json, hashlib, gzip, zlib, functools
from . import config as C

_S3 = None
# Offline mode: a machine without S3 rights (e.g. a borrowed VM) runs from a manifest built by `prep` on a machine
# that has them: records, object heads, sibling-IFC lists and presigned GET URLs. No credentials leave that machine.
MANIFEST = json.load(open(os.environ["DB1V_MANIFEST"])) if os.environ.get("DB1V_MANIFEST") else None


def s3():
    global _S3
    if _S3 is None:
        import boto3
        from botocore.config import Config
        _S3 = boto3.client("s3", region_name=C.REGION, config=Config(max_pool_connections=32, retries={"max_attempts": 8, "mode": "adaptive"}))
    return _S3


def head(bucket, key):
    if MANIFEST is not None:
        return MANIFEST["heads"].get(f"{bucket}/{key}", dict(error="not in manifest"))
    from botocore.exceptions import ClientError
    try:
        h = s3().head_object(Bucket=bucket, Key=key)
        return dict(bytes=h["ContentLength"], etag=h["ETag"].strip('"'), modified=h["LastModified"].isoformat())
    except ClientError as e:
        return dict(error=e.response.get("Error", {}).get("Code", "error"))


def get_json(bucket, key):
    return json.loads(s3().get_object(Bucket=bucket, Key=key)["Body"].read())


def record(sha):
    """the production worker's result record for this input sha"""
    if MANIFEST is not None:
        return MANIFEST["records"].get(sha, dict(error="not in manifest"))
    try: return get_json(C.BUCKET, f"{C.RESULTS_PREFIX}{sha}.json")
    except Exception as e: return dict(error=f"{type(e).__name__}: {e}"[:200])


def download(bucket, key, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) == (head(bucket, key).get("bytes") or -1):
        return path
    if MANIFEST is not None:
        import urllib.request, shutil
        url = MANIFEST["urls"][f"{bucket}/{key}"]
        with urllib.request.urlopen(url, timeout=600) as r, open(path + ".part", "wb") as o: shutil.copyfileobj(r, o, 16 << 20)
        os.replace(path + ".part", path)
    else:
        s3().download_file(bucket, key, path)
    return path


def presign(bucket, key, hours=12):
    return s3().generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=int(hours * 3600))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(16 << 20), b""): h.update(b)
    return h.hexdigest()


def db1_facts(path):
    """engine banner (Xsteel version) and gzip state of a .db1, read from its decompressed head"""
    raw = open(path, "rb").read(1 << 20)
    gz = raw[:2] == b"\x1f\x8b"; truncated = False; head_b = raw
    if gz:
        try: head_b = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, 65536)
        except Exception: head_b = b""; truncated = True
    m = re.search(rb"(\d+\.\d+)", head_b[:16])
    x = re.search(rb"Xsteel.{0,4}?(\d+\.\d+)", head_b[:256], re.S)
    return dict(gzip=gz, engine=(x or m).group(1).decode() if (x or m) else None, head_readable=bool(head_b))


# ---------------------------------------------------------------- fallback: the original disk bucket
def _norm(s):
    return re.sub(r"[^A-Za-z0-9.]+", "_", s).strip("_").lower()


@functools.lru_cache(maxsize=4)
def _src_index(listing_dir):
    """normalized path -> (key, bytes) for bim-proprietary-data, from saved `aws s3 ls --recursive` listings
    (disk1_listing.txt / disk2_listing.txt); built lazily, only when an input is missing."""
    idx = {}
    for d in ("disk1", "disk2"):
        p = os.path.join(listing_dir, f"{d}_listing.txt")
        if not os.path.exists(p): continue
        for ln in open(p, encoding="utf-8", errors="replace"):
            q = ln.rstrip("\n").split(None, 3)
            if len(q) < 4 or q[3].endswith("/"): continue
            disk, _, rest = q[3].partition("/")
            idx[(disk, _norm(rest))] = (q[3], int(q[2]))
    return idx


def locate_in_source_bucket(key, listing_dir=None):
    """Where an input .db1 came from in s3://bim-proprietary-data. The extract flattened the archive path
    ('/' and spaces -> '_', long names cut) and appended '-<12 hex>'. -> dict(found, bim_key, bytes, how)."""
    if MANIFEST is not None:
        return MANIFEST["source"].get(key, dict(found=False, how="not in manifest"))
    parts = key.split("/")                       # cad-disk-extract/Disk-N/<archive dir>/<path inside archive>
    if len(parts) < 4: return dict(found=False, how="unrecognised key")
    disk, arc = parts[1], re.sub(r"-[0-9a-f]{12}$", "", parts[2])
    idx = _src_index(listing_dir) if listing_dir else {}
    if not idx:                                  # no saved listing: list the disk live (slow, but only on a miss)
        pg = s3().get_paginator("list_objects_v2")
        for page in pg.paginate(Bucket=C.SRC_BUCKET, Prefix=disk + "/"):
            for o in page.get("Contents", []):
                idx[(disk, _norm(o["Key"].partition("/")[2]))] = (o["Key"], o["Size"])
    a = _norm(arc)
    r = idx.get((disk, a))
    if r: return dict(found=True, bim_key=r[0], bytes=r[1], how="archive (exact name)", inner_path="/".join(parts[3:]))
    inner = _norm("/".join(parts[2:]))
    r = idx.get((disk, inner))
    if r: return dict(found=True, bim_key=r[0], bytes=r[1], how="loose file")
    pre = sorted(v for (dk, n), v in idx.items() if dk == disk and n.startswith(a) and n[-3:] in (".7z", "zip", "rar"))
    if len(pre) == 1: return dict(found=True, bim_key=pre[0][0], bytes=pre[0][1], how="archive (truncated name, prefix)", inner_path="/".join(parts[3:]))
    if pre: return dict(found=False, how=f"ambiguous: {len(pre)} archives share the prefix", candidates=[p[0] for p in pre[:5]])
    return dict(found=False, how="not in source bucket listing")


# ---------------------------------------------------------------- ground truth next to the .db1
def sibling_ifcs(key, max_bytes=C.TRUTH_IFC_MAX_BYTES):
    """Tekla-exported IFC files in the .db1's folder and its parent folder (Tekla writes exports to the model folder
    or an IFC subfolder). -> [dict(key, bytes, head)] largest first."""
    if MANIFEST is not None:
        return MANIFEST["siblings"].get(key, [])
    folder = key.rsplit("/", 1)[0] + "/"
    out = []; seen = set()
    for pre in (folder, folder + "IFC/", folder + "ifc/", folder + "Output/", folder.rsplit("/", 2)[0] + "/"):
        try: r = s3().list_objects_v2(Bucket=C.BUCKET, Prefix=pre, Delimiter="/")
        except Exception: continue
        for o in r.get("Contents") or []:
            k = o["Key"]
            if k in seen or not k.lower().endswith(".ifc") or not (10_000 < o["Size"] <= max_bytes): continue
            seen.add(k)
            from .ifcmesh import ifc_head
            h = ifc_head(s3().get_object(Bucket=C.BUCKET, Key=k, Range="bytes=0-3999")["Body"].read())
            out.append(dict(key=k, bytes=o["Size"], same_folder=pre == folder, **h))
    return sorted(out, key=lambda x: (not x["same_folder"], not x["tekla"], -x["bytes"]))
