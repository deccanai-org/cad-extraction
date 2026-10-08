"""Shared helpers for the Zenitude-data-3 verification adapters (adapter_ifc.py, adapter_db1.py).

The two verifiers (ifcstepverify, db1stepverify) are shipped UNCHANGED next to this file. The adapters only
  * feed them local files instead of their original S3 layouts (projpkg4 packages / db1-v2 run),
  * translate our STEP product convention (ifc2step5/6 write PRODUCT('<IFC GlobalId>','<Name>','<IFC class>')
    while both verifiers were written for a writer that put the Name first) into the verifiers' own inputs,
  * map their verdicts / codes / causes into the fleet's verify-result schema, keeping every original code.
"""
import os, re, sys, json, csv, time, hashlib, resource, platform

ADAPTER_VERSION = "z3v-2026-10-02a"
CAUSES = ("pipeline", "source", "files", "packaging", "by_design", "decoder", "unclassified")
# conservative: anything that is not provably source / by-design blocks class 1
CLASS1_OK_CAUSES = ("source", "by_design")

_GUID = re.compile(r"^[0-9A-Za-z_$]{22}$")       # IFC GlobalId alphabet (some exporters write a first char > 3)
_PROD = re.compile(r"#\d+\s*=\s*PRODUCT\s*\(\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(16 << 20), b""): h.update(b)
    return h.hexdigest()


def product_triples(step_path, decode):
    """[(id, name, desc)] of every PRODUCT in file order (ifc2step5/6 write one PRODUCT per line)."""
    out = []
    with open(step_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "PRODUCT(" not in line and "PRODUCT (" not in line: continue
            m = _PROD.search(line)
            if m: out.append(tuple(decode(x) for x in m.groups()))
    return out


def guid_mode(triples, min_share=0.5):
    """True when the first PRODUCT string is an IFC GlobalId (our ifc2step5/6 convention)."""
    if not triples: return False
    return sum(bool(_GUID.match(t[0])) for t in triples) / len(triples) >= min_share


def peak_gb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; c = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    k = 1 if platform.system() == "Darwin" else 1024          # macOS: bytes, Linux: KiB
    return round(max(r, c) * k / 2 ** 30, 2)


def class1_gate(verdict, findings):
    """The grading rule (mirrors the builder's): class 1 only with PASS, or WARN where every WARN cause is source /
    by_design, and no FAIL. Anything else -> (False, blocking findings)."""
    if verdict not in ("PASS", "WARN"):
        return False, [f for f in findings if f["level"] in ("FAIL", "WARN")]
    block = [f for f in findings if f["level"] == "FAIL" or (f["level"] == "WARN" and f["cause"] not in CLASS1_OK_CAUSES)]
    return not block, block


def index_reasons(pipeline, verdict, block):
    """class-2 reason entries in the index's own format: missing [{what,count,category}], needed_to_fix [{fix,category,key}].
    category converter_feature unless the verifier says source."""
    miss, need = [], []
    if verdict in ("CANNOT_VERIFY", "ERROR"):
        miss.append({"what": f"independent verification could not run ({verdict})", "count": None, "category": "converter_feature"})
        need.append({"fix": "re-run the verifier (larger box / longer limit) or fix its input", "category": "converter_feature",
                     "key": f"converter_feature | verify {pipeline} {verdict.lower()}"})
    for f in block:
        cat = "source_damaged" if f["cause"] == "source" else "source_file_missing" if f["cause"] == "files" else "converter_feature"
        miss.append({"what": f"verifier {f['code']}: {f['detail'][:160]}", "count": f.get("count"), "category": cat})
        need.append({"fix": f"resolve verifier finding {f['code']} ({f['cause']})", "category": cat, "key": f"{cat} | verify {pipeline} {f['code']}"})
    return miss, need


def write_out(out_path, doc, missing_rows=None, csv_cols=None, full=None):
    """<out>.json (adapter result), <out>.missing.csv (every missing / flagged element), <out>.full.json (verifier's own result)"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    base = out_path[:-5] if out_path.endswith(".json") else out_path
    if missing_rows is not None:
        p = base + ".missing.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, csv_cols, extrasaction="ignore"); w.writeheader()
            for r in missing_rows: w.writerow(r)
        doc["missing_csv"] = os.path.basename(p)
    if full is not None:
        p = base + ".full.json"
        json.dump(full, open(p, "w"), indent=1, sort_keys=True, default=str); doc["full_json"] = os.path.basename(p)
    json.dump(doc, open(out_path, "w"), indent=1, sort_keys=True, default=str)
    return doc


def s3_client():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", region_name="ap-south-1", config=Config(retries={"max_attempts": 8, "mode": "standard"}))


def get_json_s3(bucket, key):
    try:
        b = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
        if b[:2] == b"\x1f\x8b":
            import gzip; b = gzip.decompress(b)
        return json.loads(b)
    except Exception:
        return None


SCHEMA_FIX = {**{s: b"IFC2X3" for s in ("IFC2X2_FINAL", "IFC2X_FINAL", "IFC2X2", "IFC2X", "IFC2X2_PLATFORM", "IFC2X_PLATFORM", "IFC2X3_FINAL", "IFC2X3_TC1")},
              **{s: b"IFC4X3_ADD2" for s in ("IFC4X1", "IFC4X2", "IFC4X3_RC1", "IFC4X3_RC2", "IFC4X3_RC3", "IFC4X3_RC4", "IFC4X3_TC1", "IFC4X3_ADD1")}}


def fix_schema(src, dst_dir):
    """mirror of ifc/worker.py fix_schema (the data-3 input fix): an older / interim schema name that IfcOpenShell does not load
    is declared as the schema it is a subset of (IFC2X2 -> IFC2X3, IFC4X1..ADD1 -> IFC4X3_ADD2). -> (path, note or None)"""
    with open(src, "rb") as f: head = f.read(1 << 16)
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", head)
    sc = m.group(1).decode("latin-1").upper() if m else None
    if sc not in SCHEMA_FIX: return src, None
    data = open(src, "rb").read()
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data[:1 << 16])
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.splitext(os.path.basename(src))[0] + ".schemafix.ifc")
    open(dst, "wb").write(data[:m.start(1)] + SCHEMA_FIX[sc] + data[m.end(1):])
    return dst, f"schema {sc} declared {SCHEMA_FIX[sc].decode()} (data-3 input fix, as ifc/worker.py)"
