"""Finish IFC->STEP for the jobs that never produced a STEP: memory-deferred giants (inflated by the
converter's one-thread-per-core default) and conversion failures. Run on a fleet host that has the
occ env (/opt/db1v2). Shard with IFC_SHARD=i/N. Only verified outputs are published, exactly like
ifc_worker.py (same result schema, out_key conversions/ifc-step/<id>.stp).
Input fixes (recorded in the result as input_fix): legacy schema IFC2X2_FINAL / IFC2X_FINAL is
declared as IFC2X3 (ifcopenshell parses strictly: any entity that does not fit fails the run, it is
never guessed); an unparsable HEADER is replaced by a minimal standard one. CIS/2 files
(STRUCTURAL_FRAME_SCHEMA) are not IFC and are recorded as unsupported_format."""
import json, os, re, subprocess, sys, time, zlib, platform, traceback
import boto3
B = "annotationprod"; R = "cad-disk-extract"; CTL = f"{R}/_control/ifc-step"; ST = f"{R}/_state/ifc-step"; OUT = f"{R}/conversions/ifc-step"
WORK = os.environ.get("W", "/opt/db1v2"); PY = os.path.join(WORK, "mamba/envs/occ/bin/python")
PY84 = "/opt/ifc84/bin/python"       # ifcopenshell 0.8.5 hangs on some boolean cuts; 0.8.4 does not
CPY = PY84 if os.path.exists(PY84) else PY
CONV = os.path.join(WORK, "ifc2step5.py"); VAL = os.path.join(WORK, "validate_step.py")
HOST = platform.node(); s3 = boto3.client("s3", region_name="ap-south-1"); RB_MAX = 64 << 20; TIMEOUT = 21600
def now(): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def put(k, o): s3.put_object(Bucket=B, Key=k, Body=json.dumps(o, default=str).encode(), ContentType="application/json")
def getj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)["Body"].read())
    except Exception: return None
jobs = json.loads(s3.get_object(Bucket=B, Key=f"{CTL}/ifc_jobs.json")["Body"].read()); jobs = jobs["jobs"] if isinstance(jobs, dict) else jobs
todo = []
for j in jobs:
    r = getj(f"{ST}/results/{j['id']}.json")
    if r is None or (r.get("status") in ("convert_fail", "convert_timeout", "worker_error", "empty_output", "bad_flavour") and not r.get("finisher")): todo.append(j)
todo.sort(key=lambda j: -(j.get("size") or 0))
print(now(), HOST, "open IFC jobs", len(todo), flush=True)
STALE = 1800
def claim(jid):
    """S3 conditional create; a claim untouched for STALE s is taken over (any number of hosts)"""
    key = f"{ST}/claims/{jid}.json"; body = json.dumps({"host": HOST, "at": now(), "by": "ifc_finish"}).encode()
    try:
        s3.put_object(Bucket=B, Key=key, Body=body, IfNoneMatch="*"); return True
    except Exception:
        pass
    try: age = time.time() - s3.head_object(Bucket=B, Key=key)["LastModified"].timestamp()
    except Exception: return False
    if age < STALE: return False
    try:
        s3.delete_object(Bucket=B, Key=key); s3.put_object(Bucket=B, Key=key, Body=body, IfNoneMatch="*"); return True
    except Exception: return False
def touch_loop(jid, stop):
    while not stop.wait(300):
        try: s3.put_object(Bucket=B, Key=f"{ST}/claims/{jid}.json", Body=json.dumps({"host": HOST, "at": now(), "refresh": True}).encode())
        except Exception: pass
import threading

def unzip_if_ifczip(src, dst):
    """IFCZIP saved with a .ifc name: extract the largest member (the SPF model)"""
    import zipfile
    with open(src, "rb") as f:
        if f.read(4) != b"PK\x03\x04": return False
    with zipfile.ZipFile(src) as z:
        mem = max(z.infolist(), key=lambda i: i.file_size)
        with z.open(mem) as a, open(dst, "wb") as b:
            while True:
                chunk = a.read(1 << 24)
                if not chunk: break
                b.write(chunk)
    return True


def header_fix(src, dst):
    """-> (fix_label or None, schema) ; writes dst when a fix is applied"""
    with open(src, "rb") as f: head = f.read(1 << 16)
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", head)
    schema = m.group(1).decode("latin1").upper() if m else None
    if schema and schema.startswith("STRUCTURAL_FRAME"): return "unsupported_format_cis2", schema
    data = None
    if schema in ("IFC2X2_FINAL", "IFC2X_FINAL", "IFC2X2", "IFC2X"):
        data = open(src, "rb").read(); data = data.replace(m.group(0), m.group(0).replace(m.group(1), b"IFC2X3"), 1); fix = f"schema_{schema}_declared_IFC2X3"
    else:
        data = open(src, "rb").read()
        h = re.search(rb"HEADER;(.*?)ENDSEC;", data, re.S)
        if not h: return None, schema
        std = (b"HEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
               b"FILE_NAME('model.ifc','2000-01-01T00:00:00',(''),(''),'','','');\n"
               b"FILE_SCHEMA(('" + (schema or "IFC2X3").encode() + b"'));\nENDSEC;")
        data = data[:h.start()] + std + data[h.end():]; fix = "header_normalized"
    open(dst, "wb").write(data); return fix, schema

def run(cmd, logf):
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    cmd = ["systemd-run", "--scope", "--quiet", "-p", f"MemoryMax={int(total * 0.85)}", "-p", "MemorySwapMax=0"] + cmd
    with open(logf, "w") as lf:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT)
        try: return p.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired: p.kill(); p.wait(); return 124

def count(path, pats):
    c = {p: 0 for p in pats}
    with open(path, "rb") as f:
        for ln in f:
            for p in pats:
                if p in ln: c[p] += ln.count(p)
    return c

for j in todo:
    jid = j["id"]
    r0 = getj(f"{ST}/results/{jid}.json")
    if r0 is not None and (r0.get("finisher") or r0.get("status") == "ok"): continue   # done by another host meanwhile
    dj = getj(f"{ST}/deferred/{jid}.json")
    host_gb = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) >> 30
    if dj and host_gb < 400: continue          # memory-heavy job: leave it to a 512 GB host
    if not claim(jid): continue
    stop = threading.Event(); threading.Thread(target=touch_loop, args=(jid, stop), daemon=True).start()
    d = os.path.join(WORK, "ifcfin", jid); os.makedirs(d, exist_ok=True)
    inp = os.path.join(d, "in.ifc"); fixed = os.path.join(d, "fixed.ifc"); out = os.path.join(d, "out.stp"); logf = os.path.join(d, "conv.log")
    rec = {"id": jid, "key": j["key"], "in_bytes": j.get("size"), "etag": j.get("etag"), "host": HOST, "started": now(),
           "out_key": f"{OUT}/{jid}.stp", "finisher": "ifc_finish.py (threads 4, 6 h)"}
    try:
        key = j["key"]
        try: s3.head_object(Bucket=B, Key=key)
        except Exception:
            # the IFC packaging pass moved this project from main/2d to main/3d
            if "/dataset/main/2d/" in key: key = key.replace("/dataset/main/2d/", "/dataset/main/3d/", 1)
        rec["key"] = key
        s3.download_file(B, key, inp)
        rc = None; mode_used = None; src = inp; rec["input_fix"] = None
        unz = os.path.join(d, "unzipped.ifc")
        if unzip_if_ifczip(inp, unz):
            os.replace(unz, inp); rec["input_unzipped"] = "ifczip_saved_as_ifc"
        for attempt in ("asis", "fix"):
            if attempt == "fix":
                fx, schema = header_fix(inp, fixed); rec["input_fix"] = fx; rec["schema_in"] = schema
                if fx == "unsupported_format_cis2" or fx is None: break
                src = fixed
            for mode in ("hybrid", "tess"):
                if os.path.exists(out): os.remove(out)
                rc = run([CPY, CONV, src, out, "--mode", mode, "--prec", "2", "--threads", "4"], logf); mode_used = mode
                if rc == 0 and os.path.exists(out) and os.path.getsize(out) > 0: break
            if rc == 0 and os.path.exists(out) and os.path.getsize(out) > 0: break
        rec["rc"] = rc; rec["converter"] = f"ifc2step5.py --mode {mode_used} --prec 2 --threads 4"; rec["ifcopenshell"] = "0.8.4.post1" if CPY == PY84 else "env-default"
        if rc in (-9, 137):
            # memory-killed: not a verdict on the file; release it for a bigger host, write no result
            put(f"{ST}/deferred/{jid}.json", {"id": jid, "host": HOST, "host_mem_gb": host_gb, "min_mem_gb": int(host_gb * 1.2), "at": now(), "rc": rc, "by": "ifc_finish"})
            stop.set(); s3.delete_object(Bucket=B, Key=f"{ST}/claims/{jid}.json"); subprocess.run(["rm", "-rf", d])
            print(now(), jid[:12], "memory-killed, released", flush=True); continue
        if rec.get("input_fix") == "unsupported_format_cis2":
            rec["status"] = "unsupported_format"; rec["reason"] = "CIS/2 STRUCTURAL_FRAME_SCHEMA file with .ifc name (not IFC)"
        elif rc != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
            rec["status"] = "convert_timeout" if rc == 124 else "convert_fail"
            rec["log_tail"] = open(logf, errors="replace").read()[-2000:]
        else:
            nb = os.path.getsize(out); rec["out_bytes"] = nb
            pats = [b"FACETED_BREP(", b"POLY_LOOP", b"CLOSED_SHELL(", b"OPEN_SHELL(", b"SHELL_BASED_SURFACE_MODEL(", b"ADVANCED_FACE", b"TESSELLATED", b"TRIANGULATED_FACE_SET"]
            m = {k.decode().rstrip("("): v for k, v in count(out, pats).items()}; rec["markers"] = m
            with open(out, errors="replace") as f: head = [next(f, "") for _ in range(12)]
            rec["schema"] = next((l.strip() for l in head if "FILE_SCHEMA" in l), None)
            rec["flavour_ok"] = (m["ADVANCED_FACE"] == 0 and m["TESSELLATED"] == 0 and m["TRIANGULATED_FACE_SET"] == 0 and "AUTOMOTIVE_DESIGN" in (rec["schema"] or ""))
            geom = {}
            if nb < RB_MAX:
                try: geom = json.loads(subprocess.run([PY, VAL, out], capture_output=True, text=True, timeout=1800).stdout.strip().splitlines()[-1])
                except Exception as e: geom = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            else: geom = {"skipped": "output >= 64 MB"}
            rec["readback"] = geom
            if geom.get("read_status") == "ok" and "faces" in geom:
                g = "ok_solid" if geom.get("solids", 0) > 0 else ("ok_surface" if geom.get("faces", 0) > 0 else "empty")
            else:
                g = "ok_solid" if (m["FACETED_BREP"] > 0 or m["CLOSED_SHELL"] > 0) else ("ok_surface" if m["POLY_LOOP"] > 0 else "empty")
            rec["grade"] = g
            rec["status"] = "ok" if g != "empty" and rec["flavour_ok"] else ("empty" if g == "empty" else "bad_flavour")
            if rec["status"] == "ok": s3.upload_file(out, B, rec["out_key"], ExtraArgs={"ContentType": "application/step"})
    except Exception as e:
        rec["status"] = "worker_error"; rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"; rec["trace"] = traceback.format_exc()[-1200:]
    finally:
        subprocess.run(["rm", "-rf", d])
    stop.set()
    rec["finished"] = now(); put(f"{ST}/results/{jid}.json", rec)
    try: s3.delete_object(Bucket=B, Key=f"{ST}/claims/{jid}.json")
    except Exception: pass
    print(now(), jid[:12], rec["status"], rec.get("input_fix"), rec.get("converter"), rec.get("out_bytes"), flush=True)
print(now(), "SHARD DONE", flush=True)


# ---- crash rescue: IFC jobs whose finisher run ended in a geometry-kernel segfault (rc -11). Bisect to the
# elements the kernel crashes on, convert the model WITHOUT exactly those elements, record them by GUID.
# Never more than max(50, 1% of the tessellated set): a systematic crash is not "a few bad elements".
RES_DIR = os.path.join(WORK, "rescue"); os.makedirs(RES_DIR, exist_ok=True)
def rescue_tools():
    for t in ("ifc_crash_bisect.py", "ifc_exclude.py"):
        s3.download_file(B, f"{CTL}/rescue/{t}", os.path.join(RES_DIR, t))
def tail_repair(path):
    """A file cut off mid-statement (no END-ISO terminator) is repaired ONLY when nothing is lost but the
    unfinished tail: cut at the last complete statement, append the terminators, and require that every
    #reference in the kept statements resolves and that IfcProject + IfcUnitAssignment are present."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        fh.seek(max(0, size - 4096)); tail = fh.read()
    if tail.rstrip(b"\x00 \r\n\t").endswith(b"END-ISO-10303-21;"): return {"terminated": True}
    with open(path, "rb") as fh: data = fh.read()
    cut = max(data.rfind(b";\r\n"), data.rfind(b";\n"))
    if cut < 0: return {"refused": "no complete statement"}
    body = data[:cut + 1]; dropped = len(data) - len(body)
    ids = set(int(m.group(1)) for m in re.finditer(rb"#(\d+)\s*=", body))
    refs = set(int(m.group(1)) for m in re.finditer(rb"#(\d+)", re.sub(rb"'[^']*'", b"", body)))
    dangling = len(refs - ids)
    has_proj = re.search(rb"=\s*IFCPROJECT\s*\(", body) is not None; has_units = re.search(rb"=\s*IFCUNITASSIGNMENT\s*\(", body) is not None
    info = {"dropped_bytes": dropped, "entities_kept": len(ids), "dangling_refs": dangling, "project": has_proj, "units": has_units}
    if dangling or not has_proj or not has_units or dropped > 1 << 20:
        info["refused"] = f"{dangling} references to missing entities, project={has_proj}, units={has_units}, cut {dropped} bytes"
        return info
    nl = b"\r\n" if b"\r\n" in body[-64:] else b"\n"
    with open(path, "wb") as fh: fh.write(body + nl + b"ENDSEC;" + nl + b"END-ISO-10303-21;" + nl)
    info["repaired"] = True
    return info


rescue = []
for j in jobs:
    r = getj(f"{ST}/results/{j['id']}.json")
    rs_ = r.get("rescue") if r else None
    if r and r.get("finisher") and r.get("status") == "convert_fail" and r.get("rc") == -11 and (
            not rs_ or (str(rs_.get("result", "")).startswith("rescue error") and not rs_.get("tail_checked"))):
        rescue.append((j, r))
print(now(), HOST, "crash-rescue candidates", len(rescue), flush=True)
if rescue:
    rescue_tools()
for j, prev in sorted(rescue, key=lambda x: (x[0].get("size") or 0)):
    jid = j["id"]
    cur = getj(f"{ST}/results/{jid}.json")
    if not cur or cur.get("status") == "ok": continue
    crs = cur.get("rescue")
    if crs and not (str(crs.get("result", "")).startswith("rescue error") and not crs.get("tail_checked")): continue
    if not claim(jid): continue
    stop = threading.Event(); threading.Thread(target=touch_loop, args=(jid, stop), daemon=True).start()
    d = os.path.join(WORK, "ifcres", jid); os.makedirs(d, exist_ok=True)
    inp = os.path.join(d, "in.ifc"); fixed = os.path.join(d, "fixed.ifc"); out = os.path.join(d, "out.stp"); logf = os.path.join(d, "conv.log")
    rec = dict(prev); rec.update(host=HOST, started=now(), finisher="ifc_finish.py crash-rescue (bisect + exclude, threads 4, 6 h)")
    info = {"at": now()}
    try:
        key = j["key"]
        try: s3.head_object(Bucket=B, Key=key)
        except Exception:
            if "/dataset/main/2d/" in key: key = key.replace("/dataset/main/2d/", "/dataset/main/3d/", 1)
        s3.download_file(B, key, inp)
        unz = os.path.join(d, "unzipped.ifc")
        if unzip_if_ifczip(inp, unz): os.replace(unz, inp)
        tr = tail_repair(inp); info["tail_checked"] = True; info["tail"] = tr
        if tr.get("refused"):
            raise RuntimeError("not repairable: " + tr["refused"])
        bl = os.path.join(d, "bisect.log")
        with open(bl, "w") as lf:
            p = subprocess.run([CPY, os.path.join(RES_DIR, "ifc_crash_bisect.py"), inp, CONV, "16", "300"], stdout=subprocess.PIPE, stderr=lf, text=True, timeout=4 * 3600)
        lines = p.stdout.strip().splitlines()
        if not lines:
            raise RuntimeError(f"bisect produced no result (rc {p.returncode}): " + open(bl, errors="replace").read()[-300:].replace("\n", " "))
        res = json.loads(lines[-1])
        culprits = res["culprits"]; info.update(tessellate_set=res["tessellate_set"], bisect_secs=res["secs"], culprits=len(culprits))
        cap = max(50, res["tessellate_set"] // 100)
        repaired_tail = bool((info.get("tail") or {}).get("repaired"))
        if not culprits and not repaired_tail:
            info["result"] = "no_crashing_element_isolated"
        elif len(culprits) > cap:
            info["result"] = f"too_many_crashing_elements ({len(culprits)} > {cap})"
        else:
            if culprits:
                ex = subprocess.run([CPY, os.path.join(RES_DIR, "ifc_exclude.py"), inp, fixed] + [c["guid"] for c in culprits], capture_output=True, text=True, timeout=3600)
                excluded = json.loads(ex.stdout.strip().splitlines()[-1])
            else:
                excluded = []; os.replace(inp, fixed)       # tail repair alone made the model readable
            rc = run([CPY, CONV, fixed, out, "--mode", "hybrid", "--prec", "2", "--threads", "4"], logf)
            info["convert_rc"] = rc
            if rc == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                nb = os.path.getsize(out)
                pats = [b"FACETED_BREP(", b"POLY_LOOP", b"CLOSED_SHELL(", b"OPEN_SHELL(", b"SHELL_BASED_SURFACE_MODEL(", b"ADVANCED_FACE", b"TESSELLATED", b"TRIANGULATED_FACE_SET"]
                mk = {k.decode().rstrip("("): v for k, v in count(out, pats).items()}
                with open(out, errors="replace") as fh: head = [next(fh, "") for _ in range(12)]
                schema = next((l.strip() for l in head if "FILE_SCHEMA" in l), None)
                flav = (mk["ADVANCED_FACE"] == 0 and mk["TESSELLATED"] == 0 and mk["TRIANGULATED_FACE_SET"] == 0 and "AUTOMOTIVE_DESIGN" in (schema or ""))
                geom = {}
                if nb < RB_MAX:
                    try: geom = json.loads(subprocess.run([PY, VAL, out], capture_output=True, text=True, timeout=1800).stdout.strip().splitlines()[-1])
                    except Exception as e: geom = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
                else: geom = {"skipped": "output >= 64 MB"}
                if geom.get("read_status") == "ok" and "faces" in geom:
                    g = "ok_solid" if geom.get("solids", 0) > 0 else ("ok_surface" if geom.get("faces", 0) > 0 else "empty")
                else:
                    g = "ok_solid" if (mk["FACETED_BREP"] > 0 or mk["CLOSED_SHELL"] > 0) else ("ok_surface" if mk["POLY_LOOP"] > 0 else "empty")
                st = {}
                try: st = json.load(open(out + ".stats.json"))
                except Exception: pass
                if g != "empty" and flav:
                    put(f"{ST}/results_superseded/{jid}.json", prev)
                    s3.upload_file(out, B, rec["out_key"], ExtraArgs={"ContentType": "application/step"})
                    rec.update(status="ok", out_bytes=nb, markers=mk, schema=schema, flavour_ok=flav, readback=geom, grade=g, stats=st, rc=0,
                               converter="ifc2step5.py --mode hybrid --prec 2 --threads 4", ifcopenshell="0.8.4.post1",
                               input_fix=("truncated_tail_repaired+" if (info.get("tail") or {}).get("repaired") else "") + ("kernel_crash_elements_excluded" if excluded else "none"),
                               excluded_elements=excluded)
                    rec.pop("log_tail", None)
                    info["result"] = (f"converted without {len(excluded)} crashing element(s)" if excluded else "converted") + (" after dropping an unfinished final statement" if repaired_tail else "")
                else:
                    info["result"] = f"output rejected (grade {g}, flavour {flav})"
            else:
                info["result"] = "still crashes after exclusion" if rc == -11 else f"convert rc {rc}"
                info["log_tail"] = open(logf, errors="replace").read()[-1200:]
    except Exception as e:
        info["result"] = f"rescue error: {type(e).__name__}: {str(e)[:200]}"
    finally:
        subprocess.run(["rm", "-rf", d])
    stop.set()
    rec["rescue"] = info; rec["finished"] = now()
    put(f"{ST}/results/{jid}.json", rec)
    try: s3.delete_object(Bucket=B, Key=f"{ST}/claims/{jid}.json")
    except Exception: pass
    print(now(), jid[:12], "rescue:", info.get("result"), flush=True)
print(now(), "RESCUE DONE", flush=True)
