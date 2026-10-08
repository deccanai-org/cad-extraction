"""READ-ONLY scan of every IFC job input for concatenated STEP-21 files (two or more HEADER/DATA
sections in one .ifc; the later section reuses entity ids, so ifcopenshell resolves references of
the first model to entities of the second -> empty or wrong geometry). Streams each object in-region.
Writes _control/ifc-step/concat_scan/{result.json,progress.json}."""
import json, os, re, sys, time, boto3
from concurrent.futures import ProcessPoolExecutor, as_completed
B = "annotationprod"; R = "cad-disk-extract"; OUT = f"{R}/_control/ifc-step/concat_scan"
RX_DATA = re.compile(rb"DATA;\s*#(\d+)\s*=")
def scan(job):
    s3 = boto3.client("s3", region_name="ap-south-1")
    key = job["key"]
    for k in (key, key.replace("/dataset/main/2d/", "/dataset/main/3d/", 1)):
        try:
            body = s3.get_object(Bucket=B, Key=k)["Body"]; key = k; break
        except Exception as e:
            err = str(e)[:200]; body = None
    if body is None: return {"id": job["id"], "error": err}
    heads = isos = ends = datas = 0; first_ids = []; tail = b""; nbytes = 0; max_id = 0
    for chunk in body.iter_chunks(8 << 20):
        buf = tail + chunk; nbytes += len(chunk)
        cut = len(buf) - 64 if len(chunk) == (8 << 20) else len(buf)
        seg = buf[:cut] if cut > 0 else b""
        heads += seg.count(b"HEADER;"); ends += seg.count(b"END-ISO-10303-21;")
        isos += seg.count(b"ISO-10303-21;")
        for m in RX_DATA.finditer(seg):
            datas += 1
            if len(first_ids) < 8: first_ids.append(int(m.group(1)))
        tail = buf[cut:] if cut > 0 else buf
    if tail:
        heads += tail.count(b"HEADER;"); ends += tail.count(b"END-ISO-10303-21;"); isos += tail.count(b"ISO-10303-21;")
        for m in RX_DATA.finditer(tail):
            datas += 1
            if len(first_ids) < 8: first_ids.append(int(m.group(1)))
    return {"id": job["id"], "key": key, "bytes": nbytes, "headers": heads, "iso_starts": isos - ends, "iso_ends": ends, "data_sections": datas, "first_ids": first_ids}
def main():
    s3 = boto3.client("s3", region_name="ap-south-1")
    jobs = json.loads(s3.get_object(Bucket=B, Key=f"{R}/_control/ifc-step/ifc_jobs.json")["Body"].read()); jobs = jobs["jobs"] if isinstance(jobs, dict) else jobs
    jobs.sort(key=lambda j: -(j.get("size") or 0))
    t0 = time.time(); res = []; done = 0
    with ProcessPoolExecutor(int(os.environ.get("P", "48"))) as ex:
        futs = [ex.submit(scan, j) for j in jobs]
        for f in as_completed(futs):
            try: res.append(f.result())
            except Exception as e: res.append({"error": f"{type(e).__name__}: {str(e)[:200]}"})
            done += 1
            if done % 500 == 0 or done == len(jobs):
                flagged = [r for r in res if r.get("headers", 0) > 1 or r.get("data_sections", 0) > 1 or r.get("iso_starts", 0) > 1]
                s3.put_object(Bucket=B, Key=f"{OUT}/progress.json", Body=json.dumps({"done": done, "total": len(jobs), "secs": round(time.time() - t0), "flagged": len(flagged), "errors": sum(1 for r in res if "error" in r)}).encode())
    flagged = [r for r in res if r.get("headers", 0) > 1 or r.get("data_sections", 0) > 1 or r.get("iso_starts", 0) > 1]
    out = {"scanned": len(res), "secs": round(time.time() - t0), "flagged": flagged, "errors": [r for r in res if "error" in r],
           "normal": sum(1 for r in res if r.get("headers") == 1 and r.get("data_sections") == 1)}
    s3.put_object(Bucket=B, Key=f"{OUT}/result.json", Body=json.dumps(out).encode())
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out.items()}), flush=True)
if __name__ == "__main__": main()
