#!/usr/bin/env python3
"""Streamed OCC verification of large STEP files: the signals of z3conv common/step_check.py (text pass + OCC read-back per
root: solids, BRepCheck validity per solid, non-positive volumes, per-part volume keyed by PRODUCT, bbox, read status) without
loading the whole file into OpenCASCADE at once.

usage:  step_verify_big.py FILE.step OUT.json [--parts OUT.parts.jsonl.gz] [--chunk-mb 24] [--workers 3] [--mem-gb 5]
                           [--workdir DIR] [--max-check 0] [--timeout 14400] [--keep] [--plan-only] [--python PY]
        step_verify_big.py --worker CHUNK.step CHUNK.json          (internal: OCC read of one chunk)
--max-check 0 checks every solid (exact); --max-check 150000 reproduces step_check.py's default sampling exactly.

How (README.md has the details and the output schema):
 1. one streaming pass over the file (bounded memory): the step_check text pass (markers, FILE_SCHEMA, PRODUCT chain), every
    `#id` occurrence parsed with numpy, the DATA section cut into contiguous blocks of ~chunk-mb that end right after a
    SHAPE_DEFINITION_REPRESENTATION statement; per block: the ids it defines (index on disk) and the ids it references but does
    not define (external references)
 2. the transitive closure of every block's external references (header contexts / units, shared DIRECTIONs, ...) is fetched
    from the file by id; SDR / PDS / SHAPE_REPRESENTATION_RELATIONSHIP statements that sit in another block than the product
    they attach to are attached to that product's block
 3. per block a self-contained Part 21 file = original HEADER + needed foreign statements + the block's own statements
    (verbatim, original order); a worker process reads it with STEPControl_Reader and runs exactly step_check's per-root loop
    (TransferRoot, solids, shells, faces, Bnd_Box, BRepCheck_Analyzer per solid, GProp volume per solid)
 4. results are aggregated in the global root order of a full read (OCC roots = PRODUCT_DEFINITIONs in file order), each root
    counted only in the block that holds its PRODUCT_DEFINITION statement; failed / killed / unreadable blocks are re-cut into
    smaller blocks down to single products (a product that still fails is reported as a crashed root, `streamed.complete` false);
    when the first chunks all fail to read and none reads, the file itself does not read: read_status is that failure
Workers run in parallel under a memory budget (estimated from measured peak RSS per chunk byte; children are polled and killed
when the budget is exceeded, then re-cut).
"""
import sys, os, re, json, time, math, random, gzip, argparse, subprocess, shutil, tempfile, resource, collections

# ------------------------------------------------------------------ step_check text-pass constants (kept identical)
MARK = ['FACETED_BREP(', 'POLY_LOOP', 'CLOSED_SHELL(', 'OPEN_SHELL(', 'MANIFOLD_SOLID_BREP(', 'ADVANCED_FACE', 'SHELL_BASED_SURFACE_MODEL(',
        'TESSELLATED', 'TRIANGULATED_FACE_SET', 'NEXT_ASSEMBLY_USAGE_OCCURRENCE(', 'MAPPED_ITEM(']
ent_re = re.compile(r"^#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*)\)\s*;\s*$", re.S)
VERSION = 'step-verify-big 2026-10-02b'
TOL_FLAG = 0.1      # mm: a root whose Bnd_Box gap (max sub-shape tolerance after the reader's healing) exceeds this is flagged


def refs(s):
    return [int(x) for x in re.findall(r'#(\d+)', s)]


def strs(s):
    return re.findall(r"'((?:[^']|'')*)'", s)


_RI = None


def _ri():
    """macOS proc_pid_rusage(RUSAGE_INFO_V4): phys_footprint = the memory the kernel charges to a process (resident + compressed
    + swapped), the number Activity Monitor shows; RSS alone under-reports on a box under memory pressure"""
    global _RI
    if _RI is None:
        import ctypes

        class RI(ctypes.Structure):
            _fields_ = [('uuid', ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
                'user_time', 'system_time', 'pkg_idle_wkups', 'interrupt_wkups', 'pageins', 'wired_size', 'resident_size', 'phys_footprint',
                'proc_start_abstime', 'proc_exit_abstime', 'child_user_time', 'child_system_time', 'child_pkg_idle_wkups',
                'child_interrupt_wkups', 'child_pageins', 'child_elapsed_abstime', 'diskio_bytesread', 'diskio_byteswritten',
                'cpu_time_qos_default', 'cpu_time_qos_maintenance', 'cpu_time_qos_background', 'cpu_time_qos_utility',
                'cpu_time_qos_legacy', 'cpu_time_qos_user_initiated', 'cpu_time_qos_user_interactive', 'billed_system_time',
                'serviced_system_time', 'logical_writes', 'lifetime_max_phys_footprint', 'instructions', 'cycles', 'billed_energy',
                'serviced_energy', 'interval_max_phys_footprint', 'runnable_time')]
        try:
            _RI = (ctypes.CDLL('/usr/lib/libproc.dylib'), RI, ctypes)
        except OSError:
            _RI = False
    return _RI


def mem_of(pid):
    """(current, lifetime peak) bytes of a live process: phys_footprint on macOS, VmRSS / VmHWM on Linux; (0, 0) if gone"""
    if sys.platform == 'darwin':
        r = _ri()
        if r:
            lib, RI, ct = r
            ri = RI()
            if lib.proc_pid_rusage(int(pid), 4, ct.byref(ri)) == 0:
                return int(ri.phys_footprint), int(ri.lifetime_max_phys_footprint)
        return 0, 0
    try:
        cur = peak = 0
        for ln in open(f'/proc/{pid}/status'):
            if ln.startswith('VmRSS:'):
                cur = int(ln.split()[1]) * 1024
            elif ln.startswith('VmHWM:'):
                peak = int(ln.split()[1]) * 1024
        return cur, peak
    except OSError:
        return 0, 0


def peak_rss_bytes():
    """peak memory of this process: lifetime max phys_footprint (macOS) or ru_maxrss (Linux)"""
    if sys.platform == 'darwin':
        c, p = mem_of(os.getpid())
        if p:
            return p
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(r if sys.platform == 'darwin' else r * 1024)


# ================================================================== worker: OCC read of one chunk (step_check section 2, per root)
def occ_api():
    try:
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.IFSelect import IFSelect_RetDone
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL
        from OCC.Core.BRepCheck import BRepCheck_Analyzer
        from OCC.Core.GProp import GProp_GProps
        from OCC.Core.Bnd import Bnd_Box
        try:
            from OCC.Core.BRepGProp import brepgprop
            vol_props = brepgprop.VolumeProperties
        except ImportError:
            from OCC.Core.BRepGProp import brepgprop_VolumeProperties as vol_props
        try:
            from OCC.Core.BRepBndLib import brepbndlib
            bnd_add = brepbndlib.Add
        except ImportError:
            from OCC.Core.BRepBndLib import brepbndlib_Add as bnd_add
        import OCC
        kern = 'pythonocc ' + str(getattr(OCC, 'VERSION', '?'))
    except ImportError:                                   # cadquery OCP bindings (same OCCT kernel)
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.GProp import GProp_GProps
        from OCP.Bnd import Bnd_Box
        from OCP.BRepGProp import BRepGProp
        from OCP.BRepBndLib import BRepBndLib
        vol_props = BRepGProp.VolumeProperties_s
        bnd_add = BRepBndLib.Add_s
        kern = 'OCP'
    return dict(Reader=STEPControl_Reader, RetDone=IFSelect_RetDone, Explorer=TopExp_Explorer, SOLID=TopAbs_SOLID, FACE=TopAbs_FACE,
                SHELL=TopAbs_SHELL, Analyzer=BRepCheck_Analyzer, GProps=GProp_GProps, Box=Bnd_Box, vol_props=vol_props,
                bnd_add=bnd_add, kernel=kern)


def worker_main(chunk, outp):
    """read CHUNK with STEPControl_Reader; every root: the step_check per-root signals (all solids checked; sampling, when asked,
    is emulated by the parent in global root order). Raw floats are returned; the parent rounds exactly like step_check."""
    T0 = time.time()
    A = occ_api()
    res = {'chunk': os.path.basename(chunk), 'bytes': os.path.getsize(chunk), 'kernel': A['kernel']}
    r = A['Reader']()
    st = r.ReadFile(chunk)
    res['read_status'] = 'ok' if st == A['RetDone'] else f'fail:{st}'
    res['read_sec'] = round(time.time() - T0, 2)
    roots = []
    if st == A['RetDone']:
        nroots = r.NbRootsForTransfer()
        res['roots'] = nroots
        model = r.WS().Model()
        t_occ = time.time()
        for i in range(1, nroots + 1):
            eid = None
            try:
                ent = r.RootForTransfer(i)
                try:
                    lab = model.StringLabel(ent).ToCString()
                    eid = int(lab.lstrip('#'))
                except Exception:
                    eid = None
                ok = r.TransferRoot(i)
                if not ok:
                    roots.append({'eid': eid, 'empty': True}); continue
                sh = r.Shape(r.NbShapes())
            except Exception:
                roots.append({'eid': eid, 'exc': True}); continue
            if sh is None or sh.IsNull():
                roots.append({'eid': eid, 'empty': True}); continue
            rec = {'eid': eid}
            ex = A['Explorer'](sh, A['SOLID']); sols = []
            while ex.More():
                sols.append(ex.Current()); ex.Next()
            rec['solids'] = len(sols)
            if not sols:
                exs = A['Explorer'](sh, A['SHELL']); ns = 0
                while exs.More():
                    ns += 1; exs.Next()
                rec['shells'] = ns
            exf = A['Explorer'](sh, A['FACE']); nf = 0
            while exf.More():
                nf += 1; exf.Next()
            rec['faces'] = nf
            b = A['Box']()
            try:
                A['bnd_add'](sh, b, False)
                if not b.IsVoid():
                    rec['bb'] = list(b.Get()); rec['gap'] = b.GetGap()
            except Exception:
                pass
            if sols:
                vol = 0.0; val = 0; nonpos = 0
                for s in sols:
                    try:
                        v_ = A['Analyzer'](s).IsValid()
                    except Exception:
                        v_ = False
                    val += bool(v_)
                    g = A['GProps']()
                    try:
                        A['vol_props'](s, g); vv = g.Mass()
                    except Exception:
                        vv = float('nan')
                    vol += vv
                    if not (vv > 0):
                        nonpos += 1
                rec['valid'] = val; rec['vol'] = vol; rec['nonpos'] = nonpos
            roots.append(rec)
        res['occ_sec'] = round(time.time() - t_occ, 2)
    res['records'] = roots
    res['sec'] = round(time.time() - T0, 2)
    res['peak_rss'] = peak_rss_bytes()
    tmp = outp + '.tmp'
    with open(tmp, 'w') as g:
        json.dump(res, g)
    os.replace(tmp, outp)
    return 0


# ================================================================== pass 1: streaming scan
_np = None


def np_():
    global _np
    if _np is None:
        import numpy
        _np = numpy
    return _np


def hash_scan(buf, base):
    """every '#<digits>' in buf (buf starts at a line start, base = its file offset) -> (def ids, def offsets, ref ids, ref offsets).
    A definition is '#n=' at a line start (or, checked one by one: after whitespace / ';' at the start of a statement, '#n =')."""
    np = np_()
    a = np.frombuffer(buf, np.uint8)
    n = len(a)
    hp = np.flatnonzero(a == 35)
    E = np.zeros(0, np.int64)
    if len(hp) == 0:
        return E, E, E, E
    val = np.zeros(len(hp), np.int64)
    nd = np.zeros(len(hp), np.int16)
    term = np.zeros(len(hp), np.uint8)
    alive = np.ones(len(hp), bool)
    for k in range(1, 20):
        p = hp + k
        inb = p < n
        c = a[np.minimum(p, n - 1)]
        c = np.where(inb, c, 0).astype(np.uint8)
        isd = alive & (c >= 48) & (c <= 57)
        stop = alive & ~isd
        term = np.where(stop, c, term)
        val = np.where(isd, val * 10 + (c.astype(np.int64) - 48), val)
        nd += isd
        alive = isd
        if not alive.any():
            break
    ok = nd > 0
    prev = np.where(hp > 0, a[np.maximum(hp - 1, 0)], 10)
    isdef = ok & (term == 61) & (prev == 10)
    slow = np.flatnonzero(ok & ~isdef & ((term == 61) | (term == 32) | (term == 9)))
    for j in slow:                                       # rare: '#n =' or a definition that is not at a line start
        p0 = int(hp[j]); ls = buf.rfind(b'\n', 0, p0) + 1
        pre = buf[ls:p0]
        if pre.count(b"'") % 2:
            continue
        st = pre.rstrip(b' \t\r')
        if st and not st.endswith(b';'):
            continue
        after = buf[p0 + 1 + int(nd[j]):p0 + 1 + int(nd[j]) + 64].lstrip(b' \t')
        if after[:1] == b'=':
            isdef[j] = True
    isref = ok & ~isdef
    return val[isdef], hp[isdef] + base, val[isref], hp[isref] + base


def stmt_end(chunk, start=0):
    """index of the ';' that ends the statement starting at chunk[start] (quotes respected), -1 if not inside chunk"""
    i = chunk.find(b';', start)
    if i < 0:
        return -1
    q = chunk.find(b"'", start, i)
    if q < 0:
        return i
    pos = start; ins = False
    while True:
        q = chunk.find(b"'", pos)
        s = chunk.find(b';', pos)
        if s < 0:
            return -1
        if not ins:
            if q < 0 or s < q:
                return s
            ins = True; pos = q + 1
        else:
            if q < 0:
                return -1
            ins = False; pos = q + 1


def read_stmt(f, off):
    f.seek(off)
    chunk = f.read(4096)
    while True:
        e = stmt_end(chunk)
        if e >= 0:
            return chunk[:e + 1]
        more = f.read(max(4096, len(chunk)))
        if not more:
            return chunk
        chunk += more


class Scan:
    pass


def scan_file(path, target, wd, log, bufsize=16 << 20):
    """pass 1 -> Scan object (text-pass fields identical to step_check, blocks, product offsets, attachments)"""
    np = np_()
    T0 = time.time()
    S = Scan()
    S.size = os.path.getsize(path)
    mk = dict.fromkeys(MARK, 0)
    mkb = [(m, m.encode()) for m in MARK]
    prod, pdf, pd, pds, sdr = {}, {}, {}, {}, {}
    pd_off, pds_off, sdr_off = {}, {}, {}
    srr = []                                              # (id, offset, [refs]) of *REPRESENTATION_RELATIONSHIP statements
    schema = [None]
    f = open(path, 'rb')
    head = f.read(min(S.size, 64 << 20))
    m = re.search(rb'(?m)^[ \t]*DATA[ \t]*;[ \t]*\r?$', head)
    if not m:
        raise SystemExit('no DATA; section in the first 64 MB')
    data_start = head.find(b'\n', m.end()) + 1 if head.find(b'\n', m.end()) >= 0 else m.end()
    S.header = head[:data_start]
    tail_from = max(data_start, S.size - (4 << 20))
    f.seek(tail_from); tail = f.read()
    ends = [x.start() for x in re.finditer(rb'(?m)^[ \t]*ENDSEC[ \t]*;', tail)]
    data_end = tail_from + ends[-1] if ends else S.size
    S.data_start, S.data_end = data_start, data_end
    del head, tail

    kstate = {'buf': b'', 'off': None}                   # step_check continuation buffer (bytes; decoded latin-1 at the end)

    def handle_stmt(stb, off):
        st = stb.decode('latin-1')
        mm = ent_re.match(st.strip())
        if not mm:
            return
        eid, typ, body = int(mm.group(1)), mm.group(2), mm.group(3)
        if typ == 'PRODUCT':
            s = strs(body); prod[eid] = (s[0] if s else '', s[1] if len(s) > 1 else '', s[2] if len(s) > 2 else '')
        elif typ in ('PRODUCT_DEFINITION_FORMATION', 'PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE'):
            r = refs(body); pdf[eid] = r[-1] if r else None
        elif typ in ('PRODUCT_DEFINITION', 'PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS'):
            r = refs(body); pd[eid] = r[0] if r else None; pd_off[eid] = off
        elif typ == 'PRODUCT_DEFINITION_SHAPE':
            r = refs(body); pds[eid] = r[0] if r else None; pds_off[eid] = off
        elif typ == 'SHAPE_DEFINITION_REPRESENTATION':
            r = refs(body); sdr[eid] = r[0] if r else None; sdr_off[eid] = off

    def keyword_lines(buf, base):
        """step_check's line filter: lines containing PRODUCT / SHAPE_DEFINITION_REPRESENTATION, plus continuation lines of a
        statement that did not end on its first line (a buffer > 1 MB is dropped, as in step_check)"""
        starts = set()
        for kw in (b'PRODUCT', b'SHAPE_DEFINITION_REPRESENTATION'):
            i = buf.find(kw)
            while i >= 0:
                starts.add(buf.rfind(b'\n', 0, i) + 1)
                j = buf.find(b'\n', i)
                i = buf.find(kw, j + 1) if j >= 0 else -1
        pos = 0
        if kstate['buf']:                                 # continuation from the previous buffer
            starts.add(0)
        for ls in sorted(starts):
            if ls < pos:
                continue
            le = buf.find(b'\n', ls)
            le = len(buf) if le < 0 else le + 1
            line = buf[ls:le].replace(b'\r\n', b'\n')
            if not kstate['buf']:
                kstate['off'] = base + ls
            kstate['buf'] += line
            pos = le
            while not kstate['buf'].rstrip().endswith(b';'):
                if len(kstate['buf']) > 1 << 20:
                    kstate['buf'] = b''; break
                if pos >= len(buf):
                    break                                 # continues in the next buffer
                le = buf.find(b'\n', pos)
                le = len(buf) if le < 0 else le + 1
                kstate['buf'] += buf[pos:le].replace(b'\r\n', b'\n')
                pos = le
            if kstate['buf'] and kstate['buf'].rstrip().endswith(b';'):
                st, kstate['buf'] = kstate['buf'], b''
                handle_stmt(st, kstate['off'])
            elif kstate['buf'] and pos < len(buf):
                pass

    def srr_lines(buf, base):
        i = buf.find(b'REPRESENTATION_RELATIONSHIP')
        while i >= 0:
            ls = buf.rfind(b'\n', 0, i) + 1
            mm = re.match(rb'[ \t]*#(\d+)[ \t]*=', buf[ls:ls + 40])
            if mm:
                e = stmt_end(buf, ls)
                txt = buf[ls:e + 1] if e >= 0 else buf[ls:ls + 4096]
                rr = [int(x) for x in re.findall(rb'#(\d+)', txt)]
                srr.append((rr[0], base + ls, rr[1:]))
            j = buf.find(b'\n', i)
            i = buf.find(b'REPRESENTATION_RELATIONSHIP', j + 1) if j >= 0 else -1

    def text_pass(buf, base):
        for m_, mb in mkb:
            mk[m_] += buf.count(mb)
        if schema[0] is None and b'FILE_SCHEMA' in buf:
            i = buf.find(b'FILE_SCHEMA')
            ls = buf.rfind(b'\n', 0, i) + 1; le = buf.find(b'\n', i)
            schema[0] = buf[ls:le if le >= 0 else len(buf)].decode('latin-1').strip()[:200]
        keyword_lines(buf, base)

    # header region: text pass only
    text_pass(S.header, 0)

    blocks = []
    cur = {'start': data_start, 'defs': [], 'offs': [], 'refs': [], 'nprod': 0}

    def close_block(end):
        if end <= cur['start']:
            return
        d = np.concatenate(cur['defs']) if cur['defs'] else np.zeros(0, np.int64)
        o = np.concatenate(cur['offs']) if cur['offs'] else np.zeros(0, np.int64)
        rf = np.unique(np.concatenate(cur['refs'])) if cur['refs'] else np.zeros(0, np.int64)
        mono = bool(len(d) < 2 or np.all(d[1:] > d[:-1]))
        if not mono:
            order = np.argsort(d, kind='stable'); d = d[order]; o = o[order]
        ext = np.setdiff1d(rf, d, assume_unique=False)
        k = len(blocks)
        ip = os.path.join(wd, f'idx_{k:05d}.npy')
        np.save(ip, np.stack([d, o]) if len(d) else np.zeros((2, 0), np.int64))
        blocks.append({'k': k, 'start': cur['start'], 'end': end, 'n_ent': int(len(d)), 'ext': ext,
                       'min': int(d[0]) if len(d) else None, 'max': int(d[-1]) if len(d) else None, 'mono': mono, 'idx': ip,
                       'n_sdr': cur['nprod']})
        cur.update(start=end, defs=[], offs=[], refs=[], nprod=0)

    SDR_RE = re.compile(rb'=[ \t]*SHAPE_DEFINITION_REPRESENTATION[ \t]*\(')
    pos = data_start
    t_last = time.time()
    while pos < data_end:
        f.seek(pos)
        buf = f.read(min(bufsize, data_end - pos))
        if pos + len(buf) < data_end:
            cut = buf.rfind(b'\n') + 1
            while cut <= 0:                               # a line longer than the buffer
                more = f.read(bufsize)
                if not more:
                    cut = len(buf); break
                buf += more
                cut = buf.rfind(b'\n') + 1
            buf = buf[:cut]
        base = pos
        text_pass(buf, base)
        if b'REPRESENTATION_RELATIONSHIP' in buf:
            srr_lines(buf, base)
        # candidate block ends: right after an SDR statement (end of a product in ifc2step output)
        cands = []
        for mm in SDR_RE.finditer(buf):
            e = stmt_end(buf, mm.end())
            if e < 0:
                continue
            le = buf.find(b'\n', e)
            cands.append(base + (le + 1 if le >= 0 else e + 1))
        dids, doffs, rids, roffs = hash_scan(buf, base)
        lo = 0                                            # index into the buffer's def / ref arrays
        di0 = 0; ri0 = 0
        for c in cands:
            cur['nprod'] += 1
            if c - cur['start'] >= target and c < data_end:
                di1 = int(np.searchsorted(doffs, c)); ri1 = int(np.searchsorted(roffs, c))
                cur['defs'].append(dids[di0:di1]); cur['offs'].append(doffs[di0:di1]); cur['refs'].append(np.unique(rids[ri0:ri1]))
                di0, ri0 = di1, ri1
                close_block(c)
        cur['defs'].append(dids[di0:]); cur['offs'].append(doffs[di0:]); cur['refs'].append(np.unique(rids[ri0:]))
        pos += len(buf)
        if time.time() - t_last > 30:
            log(f'scan {pos / max(1, S.size) * 100:.1f}% ({pos >> 20} MB) blocks {len(blocks)} products {len(prod)} {time.time() - T0:.0f}s')
            t_last = time.time()
    close_block(data_end)
    # trailer: text pass
    f.seek(data_end)
    text_pass(f.read(), data_end)
    if kstate['buf'] and kstate['buf'].rstrip().endswith(b';'):
        handle_stmt(kstate['buf'], kstate['off'])
    f.close()
    S.markers = {k.rstrip('('): v for k, v in mk.items()}
    S.schema = schema[0]
    S.prod, S.pdf, S.pd, S.pds, S.sdr = prod, pdf, pd, pds, sdr
    S.pd_off, S.pds_off, S.sdr_off = pd_off, pds_off, sdr_off
    S.srr = srr
    S.blocks = blocks
    S.scan_sec = round(time.time() - T0, 1)
    v6 = {}
    for v in prod.values():
        d_ = v[2] or ''
        i_ = d_.find('[v6:')
        if i_ >= 0:
            for t_ in d_[i_ + 4:d_.find(']', i_)].split(','):
                t_ = t_.strip()
                if t_:
                    v6[t_] = v6.get(t_, 0) + 1
    S.v6_tags = v6
    return S


# ================================================================== closure of external references
class Index:
    """id -> file offset over the per-block definition indexes written by the scan (memory-mapped .npy)"""

    def __init__(self, blocks):
        np = np_()
        self.blocks = [b for b in blocks if b['n_ent']]
        self.mins = np.array([b['min'] for b in self.blocks], np.int64)
        self.maxs = np.array([b['max'] for b in self.blocks], np.int64)
        self.disjoint = bool(len(self.blocks) < 2 or np.all(self.mins[1:] > self.maxs[:-1]))

    def locate(self, ids):
        """sorted unique int64 ids -> {id: offset} (ids not defined anywhere are absent)"""
        np = np_()
        out = {}
        if len(ids) == 0:
            return out
        if self.disjoint:
            bi = np.searchsorted(self.maxs, ids)         # first block whose max >= id
            groups = collections.defaultdict(list)
            for x, b in zip(ids.tolist(), bi.tolist()):
                if b < len(self.blocks):
                    groups[b].append(x)
            items = groups.items()
        else:
            items = []
            for b in range(len(self.blocks)):
                sel = ids[(ids >= self.mins[b]) & (ids <= self.maxs[b])]
                if len(sel):
                    items.append((b, sel.tolist()))
        for b, xs in items:
            arr = np.load(self.blocks[b]['idx'], mmap_mode='r')
            d = arr[0]; o = arr[1]
            q = np.array(xs, np.int64)
            j = np.searchsorted(d, q)
            j = np.minimum(j, len(d) - 1)
            hit = d[j] == q
            for x, jj in zip(q[hit].tolist(), j[hit].tolist()):
                out.setdefault(x, int(o[jj]))
        return out


REF_RE = re.compile(rb'#(\d+)')


def build_store(path, S, extra_ids, log):
    """transitive closure (downward references) of extra_ids -> store {id: (offset, statement bytes, [refs])}; dangling refs"""
    np = np_()
    idx = S.index
    store = {}
    dangling = set()
    looked = set()
    front = sorted(set(int(x) for x in extra_ids))
    with open(path, 'rb') as f:
        lvl = 0
        while front:
            lvl += 1
            q = np.array(front, np.int64)
            looked.update(front)
            loc = idx.locate(q)
            nxt = set()
            for x in front:
                off = loc.get(x)
                if off is None:
                    dangling.add(x); continue
                st = read_stmt(f, off)
                rr = [int(y) for y in REF_RE.findall(st)]
                rr = rr[1:] if rr and rr[0] == x else rr
                store[x] = (off, st, rr)
                for y in rr:
                    if y not in looked:
                        nxt.add(y)
            log(f'closure level {lvl}: {len(front)} ids fetched, store {len(store)}, dangling {len(dangling)}')
            front = sorted(nxt)
    return store, dangling


def chunk_extras(store, seeds, lo, hi):
    """ids of the store needed by a chunk whose own statements are the byte range [lo, hi)"""
    need = []
    seen = set()
    stack = [int(x) for x in seeds]
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        e = store.get(x)
        if e is None:
            continue
        if lo <= e[0] < hi:
            continue                                      # defined inside the chunk itself
        need.append(x)
        stack.extend(e[2])
    need.sort(key=lambda x: store[x][0])
    return need


def write_chunk(path, S, store, extras, lo, hi, outp):
    with open(path, 'rb') as f, open(outp, 'wb') as g:
        g.write(S.header)
        for x in extras:
            st = store[x][1]
            g.write(st if st.endswith(b'\n') else st + b'\n')
        f.seek(lo)
        left = hi - lo
        while left > 0:
            b = f.read(min(left, 16 << 20))
            if not b:
                break
            g.write(b); left -= len(b)
        g.write(b'ENDSEC;\nEND-ISO-10303-21;\n')
    return os.path.getsize(outp)


def plan_range(path, lo, hi, target, wd, tag):
    """re-cut the byte range [lo, hi) (statements, from an earlier block) into blocks of ~target bytes ending after an SDR:
    -> list of (lo, hi, ext ids) ; used when a block's worker failed"""
    np = np_()
    with open(path, 'rb') as f:
        f.seek(lo); buf = f.read(hi - lo)
    SDR_RE = re.compile(rb'=[ \t]*SHAPE_DEFINITION_REPRESENTATION[ \t]*\(')
    cands = []
    for mm in SDR_RE.finditer(buf):
        e = stmt_end(buf, mm.end())
        if e < 0:
            continue
        le = buf.find(b'\n', e)
        cands.append(lo + (le + 1 if le >= 0 else e + 1))
    cuts = [lo]
    for c in cands:
        if c - cuts[-1] >= target and c < hi:
            cuts.append(c)
    if cuts[-1] != hi:
        cuts.append(hi)
    dids, doffs, rids, roffs = hash_scan(buf, lo)
    out = []
    for a_, b_ in zip(cuts[:-1], cuts[1:]):
        d0, d1 = np.searchsorted(doffs, a_), np.searchsorted(doffs, b_)
        r0, r1 = np.searchsorted(roffs, a_), np.searchsorted(roffs, b_)
        ext = np.setdiff1d(np.unique(rids[r0:r1]), np.unique(dids[d0:d1]))
        out.append((a_, b_, ext))
    return out


# ================================================================== orchestration
def rss_of(pids):
    """current memory (bytes) of live pids (phys_footprint on macOS)"""
    out = {}
    for p in pids:
        c, _ = mem_of(p)
        if c:
            out[p] = c
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('step'); ap.add_argument('out')
    ap.add_argument('--parts')
    ap.add_argument('--chunk-mb', type=float, default=24.0, help='target block size (MB of the source file)')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--mem-gb', type=float, default=5.0, help='memory budget for this process + its workers')
    ap.add_argument('--rss-per-byte', type=float, default=30.0, help='initial worker peak-RSS estimate per chunk byte (re-measured)')
    ap.add_argument('--max-check', type=int, default=0, help='0 = every solid checked (exact); N = emulate step_check sampling')
    ap.add_argument('--timeout', type=int, default=4 * 3600, help='per-chunk worker timeout (s)')
    ap.add_argument('--workdir')
    ap.add_argument('--python', default=sys.executable)
    ap.add_argument('--keep', action='store_true', help='keep chunk files and worker outputs')
    ap.add_argument('--plan-only', action='store_true', help='pass 1 + chunk plan, no OCC')
    ap.add_argument('--title', default='')
    a = ap.parse_args()
    T0 = time.time()
    wd = a.workdir or tempfile.mkdtemp(prefix='svb_', dir=os.path.dirname(os.path.abspath(a.out)) or '.')
    os.makedirs(wd, exist_ok=True)
    logf = open(os.path.join(wd, 'run.log'), 'a')

    def log(msg):
        line = f'[{time.strftime("%H:%M:%S")} +{time.time() - T0:.0f}s] {msg}'
        print(line, file=sys.stderr, flush=True); logf.write(line + '\n'); logf.flush()

    out = {'file': os.path.basename(a.step), 'bytes': os.path.getsize(a.step)}
    target = int(a.chunk_mb * (1 << 20))
    S = scan_file(a.step, target, wd, log)
    out['markers'] = S.markers
    out['schema'] = S.schema
    out['products'] = len(S.prod)
    out['approx_products'] = sum(1 for v in S.prod.values() if '[approx:' in (v[1] or '') or '[approx:' in (v[0] or ''))
    if S.v6_tags:
        out['v6_tags'] = S.v6_tags
    out['text_sec'] = S.scan_sec
    log(f'scan done: {len(S.blocks)} blocks, {len(S.prod)} products, {len(S.pd)} product definitions, {S.scan_sec}s')
    streamed = {'version': VERSION, 'chunk_target_bytes': target, 'blocks': len(S.blocks)}
    out['streamed'] = streamed
    nauo = S.markers.get('NEXT_ASSEMBLY_USAGE_OCCURRENCE', 0)
    if nauo:
        # assemblies: a root pulls its whole tree; the per-product cut is not equivalent -> refuse instead of guessing
        out['read_status'] = None
        out['skipped'] = f'streamed verification does not support assembly structures (NEXT_ASSEMBLY_USAGE_OCCURRENCE x {nauo})'
        streamed['unsupported'] = 'assembly'
        json.dump(out, open(a.out, 'w')); print(json.dumps(out)); return 2

    S.index = Index(S.blocks)
    streamed['index_disjoint'] = S.index.disjoint

    def block_of(off):
        lo, hi = 0, len(S.blocks) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if S.blocks[mid]['end'] <= off:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # attachments: PDS / SDR statements outside the block of their PRODUCT_DEFINITION (and SRR outside their reps' blocks)
    attach = collections.defaultdict(set)
    n_att = 0
    for e, pdid in S.pds.items():
        if pdid in S.pd_off and e in S.pds_off and block_of(S.pds_off[e]) != block_of(S.pd_off[pdid]):
            attach[block_of(S.pd_off[pdid])].add(e); n_att += 1
    for e, pdsid in S.sdr.items():
        pdid = S.pds.get(pdsid)
        if pdid in S.pd_off and e in S.sdr_off and block_of(S.sdr_off[e]) != block_of(S.pd_off[pdid]):
            hb = block_of(S.pd_off[pdid]); attach[hb].add(e); n_att += 1
            if pdsid in S.pds_off and block_of(S.pds_off[pdsid]) != hb:
                attach[hb].add(pdsid)
    if S.srr:
        np = np_()
        allrep = sorted({r for _, _, rr in S.srr for r in rr})
        loc = S.index.locate(np.array(allrep, np.int64))
        for sid, soff, rr in S.srr:
            for r in rr:
                if r in loc and block_of(loc[r]) != block_of(soff):
                    attach[block_of(loc[r])].add(sid); n_att += 1
    streamed['attachments_moved'] = n_att
    streamed['srr'] = len(S.srr)
    seeds = set()
    for b in S.blocks:
        seeds.update(b['ext'].tolist())
    for v in attach.values():
        seeds.update(v)
    store, dangling = build_store(a.step, S, seeds, log)
    streamed['shared_statements'] = len(store)
    streamed['shared_bytes'] = sum(len(v[1]) for v in store.values())
    streamed['dangling_refs'] = len(dangling)
    streamed['dangling_examples'] = sorted(dangling)[:10]


    def product_of(eid):
        try:
            if eid in S.sdr:
                eid = S.pds.get(S.sdr[eid])
            if eid in S.pd:
                return S.prod.get(S.pdf.get(S.pd[eid]))
        except Exception:
            pass
        return None

    # job list: (lo, hi, seeds, depth)
    jobs = collections.deque()
    for b in S.blocks:
        jobs.append({'lo': b['start'], 'hi': b['end'], 'seeds': set(b['ext'].tolist()) | attach.get(b['k'], set()), 'depth': 0, 'name': f'b{b["k"]:05d}'})
    streamed['chunks_planned'] = len(jobs)
    if a.plan_only:
        sizes = []
        for j in list(jobs):
            ex = chunk_extras(store, j['seeds'], j['lo'], j['hi'])
            sizes.append((j['hi'] - j['lo'], len(ex), sum(len(store[x][1]) for x in ex)))
        streamed['plan'] = [{'own_bytes': s, 'extra_statements': n, 'extra_bytes': eb} for s, n, eb in sizes]
        out['sec'] = round(time.time() - T0, 1)
        json.dump(out, open(a.out, 'w'), indent=1); print(json.dumps({k: v for k, v in out.items() if k != 'streamed'}))
        return 0

    me = os.path.abspath(__file__)
    budget = int(a.mem_gb * (1 << 30))
    ratio = a.rss_per_byte
    running = {}                                          # pid -> dict(job, proc, chunk, outp, est, t0)
    results = []                                          # (job, worker result)
    crashed = []                                          # jobs that failed at single-product size
    peak_tree = 0; ratios = []
    n_done = 0; n_resplit = 0
    n_read_ok = 0; n_read_fail = 0; file_fail = [None]
    t_occ0 = time.time()
    last_log = 0

    def parent_rss():
        return mem_of(os.getpid())[0]

    def launch(job):
        ex = chunk_extras(store, job['seeds'], job['lo'], job['hi'])
        cp = os.path.join(wd, f'{job["name"]}.step'); op = os.path.join(wd, f'{job["name"]}.json')
        nb = write_chunk(a.step, S, store, ex, job['lo'], job['hi'], cp)
        lf = open(os.path.join(wd, f'{job["name"]}.log'), 'w')
        p = subprocess.Popen([a.python, me, '--worker', cp, op], stdout=lf, stderr=subprocess.STDOUT)
        running[p.pid] = {'job': job, 'proc': p, 'chunk': cp, 'outp': op, 'est': int(nb * ratio), 'bytes': nb, 't0': time.time(),
                          'extras': len(ex), 'lf': lf, 'peak': 0}

    def resplit(job, why, tail=''):
        nonlocal n_resplit
        size = job['hi'] - job['lo']
        parts = plan_range(a.step, job['lo'], job['hi'], max(1, size // 4), wd, job['name'])
        if len(parts) <= 1:
            crashed.append(dict(job, why=why, log_tail=tail))
            log(f'{job["name"]}: {why} on a single-product chunk -> crashed roots recorded; log tail: {tail[-200:]!r}')
            return
        n_resplit += 1
        newseeds = set()
        for lo_, hi_, ext in parts:
            newseeds.update(ext.tolist())
        miss = [x for x in newseeds if x not in store]
        if miss:
            st2, dg2 = build_store(a.step, S, miss, log)
            store.update(st2)
        for n_, (lo_, hi_, ext) in enumerate(parts):
            sd = set(ext.tolist()) | job['seeds']
            jobs.appendleft({'lo': lo_, 'hi': hi_, 'seeds': sd, 'depth': job['depth'] + 1, 'name': f'{job["name"]}_{n_}'})
        log(f'{job["name"]}: {why} -> re-cut into {len(parts)} chunks')

    while jobs or running:
        if file_fail[0]:
            jobs.clear()
            for r in running.values():
                r['proc'].kill(); r['proc'].wait(); r['lf'].close()
            running.clear()
            break
        # launch while the budget allows (a 'solo' job runs with nothing else beside it)
        while jobs and len(running) < a.workers:
            j = jobs[0]
            if j.get('solo') and running:
                break
            est = int((j['hi'] - j['lo']) * 1.05 * ratio)
            used = sum(r['est'] for r in running.values()) + parent_rss()
            if running and used + est > budget:
                break
            jobs.popleft(); launch(j)
        time.sleep(0.5)
        rs = rss_of(list(running) + [os.getpid()])
        prss = rs.pop(os.getpid(), 0)
        tree = prss + sum(rs.values())
        peak_tree = max(peak_tree, tree)
        for pid, r in list(running.items()):
            r['peak'] = max(r['peak'], rs.get(pid, 0))
            rc = r['proc'].poll()
            killed_for_mem = False
            if rc is None and tree > budget and rs.get(pid, 0) > 0 and rs.get(pid, 0) == max(rs.values()):
                r['proc'].kill(); r['proc'].wait(); rc = -9; killed_for_mem = True
                log(f'{r["job"]["name"]}: killed (process tree {tree >> 20} MB > budget {budget >> 20} MB)')
                tree -= rs.get(pid, 0)
            if rc is None and time.time() - r['t0'] > a.timeout:
                r['proc'].kill(); r['proc'].wait(); rc = -14
            if rc is None:
                continue
            r['lf'].close()
            del running[pid]
            res = None
            if rc == 0 and os.path.exists(r['outp']):
                try:
                    res = json.load(open(r['outp']))
                except Exception:
                    res = None
            if res is not None and res.get('read_status') != 'ok':
                # the chunk did not read: re-cut it (down to one product, then a crashed root) unless the file itself does
                # not read (the first chunks all fail, e.g. header / schema): then the result is a read failure, as a full read
                n_read_fail += 1
                if n_read_ok == 0 and n_read_fail >= 3:
                    file_fail[0] = res.get('read_status')
                    log(f'{r["job"]["name"]}: read {file_fail[0]}; {n_read_fail} chunks failed and none read -> file read failure')
                else:
                    resplit(r['job'], f'read {res.get("read_status")}', '')
                if not a.keep:
                    for p_ in (r['chunk'], r['outp']):
                        try:
                            os.remove(p_)
                        except OSError:
                            pass
                continue
            if res is not None:
                n_read_ok += 1
            if res is None:
                tail = ''
                try:
                    tail = open(os.path.join(wd, f'{r["job"]["name"]}.log'), errors='replace').read()[-300:]
                except Exception:
                    pass
                if killed_for_mem and not r['job'].get('solo') and len(running) > 0:
                    jobs.appendleft(dict(r['job'], solo=True))   # retry with the whole budget before cutting it
                    log(f'{r["job"]["name"]}: re-queued to run alone')
                else:
                    resplit(r['job'], f'rc {rc}' + (' (memory budget)' if killed_for_mem else ''), tail)
            else:
                res['_chunk_bytes'] = r['bytes']; res['_extras'] = r['extras']; res['_wall'] = round(time.time() - r['t0'], 1)
                res['_peak_polled'] = r['peak']
                results.append((r['job'], res)); n_done += 1
                pk = max(res.get('peak_rss') or 0, r['peak'])
                if r['bytes']:
                    ratios.append(pk / r['bytes']); ratio = max(a.rss_per_byte * 0.25, max(ratios[-20:]) * 1.15)
            if not a.keep:
                for p_ in (r['chunk'], r['outp']):
                    try:
                        os.remove(p_)
                    except OSError:
                        pass
        if time.time() - last_log > 30:
            last_log = time.time()
            log(f'chunks done {n_done}, running {len(running)}, queued {len(jobs)}, tree rss {tree >> 20} MB (peak {peak_tree >> 20}), '
                f'rss/byte {ratio:.1f}')
    occ_wall = time.time() - t_occ0
    if file_fail[0]:
        out['read_status'] = file_fail[0]
        streamed.update({'chunks_run': n_done, 'chunk_read_failures_before_abort': n_read_fail, 'complete': False,
                         'occ_wall_sec': round(occ_wall, 1)})
        out['sec'] = round(time.time() - T0, 1)
        json.dump(out, open(a.out, 'w'))
        print(json.dumps({k: v for k, v in out.items() if k != 'streamed'}))
        if not a.keep:
            shutil.rmtree(wd, ignore_errors=True)
        return 0

    # ------------------------------------------------------------------ aggregate in global root order
    recs = {}
    read_fail = []
    occ_sec = 0.0
    unknown = set()
    for job, res in results:
        for rc_ in res.get('records') or []:
            e = rc_.get('eid')
            if e is not None and e not in S.pd_off:
                unknown.add(e)
    eoff = dict(S.pd_off)
    if unknown:                                           # roots the text pass did not see as PRODUCT_DEFINITION statements
        np = np_()
        eoff.update(S.index.locate(np.array(sorted(unknown), np.int64)))
    n_exc_unknown = 0
    for job, res in results:
        occ_sec += res.get('occ_sec') or 0.0
        if res.get('read_status') != 'ok':
            read_fail.append({'chunk': job['name'], 'read_status': res.get('read_status')}); continue
        for rc_ in res['records']:
            e = rc_.get('eid')
            if e is None:
                n_exc_unknown += 1; recs[('?', job['name'], n_exc_unknown)] = rc_; continue
            off = eoff.get(e)
            if off is None or not (job['lo'] <= off < job['hi']):
                continue                                  # a foreign root pulled in as context: counted in its own chunk
            recs[e] = rc_
    for job in crashed:
        for e, off in S.pd_off.items():
            if job['lo'] <= off < job['hi'] and e not in recs:
                recs[e] = {'eid': e, 'crashed': job['why']}
    missing = [e for e in S.pd_off if e not in recs]
    roots_order = sorted(recs, key=lambda e: (eoff.get(e, float('inf')) if not isinstance(e, tuple) else float('inf'), str(e)))
    root_rank = {e: i + 1 for i, e in enumerate(roots_order)}
    out['read_status'] = 'ok' if not read_fail else f'fail:chunks {len(read_fail)}'
    out['roots'] = len(roots_order)
    n_est_solids = S.markers['FACETED_BREP'] + S.markers['MANIFOLD_SOLID_BREP'] or out['roots']
    check_p = 1.0 if (a.max_check <= 0 or n_est_solids <= a.max_check) else a.max_check / float(n_est_solids)
    out['check_fraction'] = round(check_p, 4)
    rng = random.Random(7)
    tot = dict(transferred=0, empty_roots=0, solids=0, shells=0, faces=0, checked=0, valid=0, invalid=0, nonpos_vol=0, nonfinite=0)
    exact = dict(checked=0, valid=0, invalid=0, nonpos_vol=0)
    parts = []; invalid_names = []
    G = None                                              # global Bnd_Box: raw min / max + max gap (Bnd_Box::Add semantics)
    boxes = []
    n_crashed = 0; n_tol = 0
    for e in roots_order:
        rc_ = recs.get(e)
        i = root_rank[e]
        p = product_of(e) if not isinstance(e, tuple) else None
        if rc_.get('crashed'):
            tot['empty_roots'] += 1; n_crashed += 1
            parts.append({'i': i, 'pid': p[0] if p else None, 'name': p[1] if p else None, 'solids': 0, 'empty': True, 'crashed': rc_['crashed']})
            continue
        if rc_.get('exc'):
            tot['empty_roots'] += 1; continue
        if rc_.get('empty'):
            tot['empty_roots'] += 1; parts.append({'i': i, 'pid': p[0] if p else None, 'name': p[1] if p else None, 'solids': 0, 'empty': True}); continue
        tot['transferred'] += 1
        rec = {'i': i, 'pid': p[0] if p else None, 'name': p[1] if p else None, 'desc': p[2] if p else None}
        ns = rc_['solids']
        rec['solids'] = ns; tot['solids'] += ns
        if not ns:
            rec['shells'] = rc_.get('shells', 0); tot['shells'] += rec['shells']
        rec['faces'] = rc_['faces']; tot['faces'] += rc_['faces']
        bb = rc_.get('bb')
        if bb is not None:
            if all(math.isfinite(v) and abs(v) < 1e10 for v in bb):
                boxes.append((bb, rc_.get('gap') or 0.0)); rec['bbox'] = [round(v, 2) for v in bb]
            else:
                tot['nonfinite'] += 1; rec['nonfinite'] = True
        gp = rc_.get('gap') or 0.0
        if gp > TOL_FLAG:
            n_tol += 1
        if ns:
            val = rc_['valid']; vol = rc_['vol']
            exact['checked'] += ns; exact['valid'] += val; exact['invalid'] += ns - val; exact['nonpos_vol'] += rc_['nonpos']
            if check_p >= 1.0 or rng.random() < check_p:
                tot['checked'] += ns; tot['valid'] += val; tot['invalid'] += ns - val; tot['nonpos_vol'] += rc_['nonpos']
                rec['valid'] = val; rec['volume'] = round(vol, 3)
                if rc_['nonpos']:
                    rec['nonpos'] = rc_['nonpos']           # extra field (not in step_check): solids of this root with volume <= 0
                if val < ns and len(invalid_names) < 50:
                    invalid_names.append([rec.get('pid'), rec.get('name')])
        if gp > TOL_FLAG:
            rec['tol'] = round(gp, 3)                       # extra field (not in step_check): healed tolerance > 0.1 mm
        parts.append(rec)
    out.update(tot)
    out['occ_sec'] = round(occ_sec, 1)
    if tot['checked']:
        f_ = tot['solids'] / tot['checked']
        out['valid_solids_est'] = int(round(tot['valid'] * f_)); out['invalid_solids_est'] = int(round(tot['invalid'] * f_))
        out['invalid_frac'] = round(tot['invalid'] / tot['checked'], 6)
    out['sampled'] = check_p < 1.0
    out['invalid_examples'] = invalid_names
    out['roots_mapped_to_products'] = sum(1 for p in parts if p.get('pid') is not None or p.get('name') is not None)
    if boxes:
        gap = max(g for _, g in boxes)
        lo = [min(bb[k] - (gap - g) for bb, g in boxes) for k in range(3)]
        hi = [max(bb[k + 3] + (gap - g) for bb, g in boxes) for k in range(3)]
        out['bbox'] = [round(v, 3) for v in lo + hi]
    if a.parts:
        with gzip.open(a.parts, 'wt') as g:
            for p in parts:
                g.write(json.dumps(p) + '\n')
    peaks = [max(res.get('peak_rss') or 0, res.get('_peak_polled') or 0) for _, res in results]
    streamed.update({
        'chunks_run': len(results), 'chunks_resplit': n_resplit, 'chunks_crashed': len(crashed), 'crashed_roots': n_crashed,
        'pd_not_reported_as_root': len(missing), 'pd_not_reported_examples': missing[:10], 'roots_without_label': n_exc_unknown,
        'chunk_read_failures': read_fail[:20], 'crashed_chunks': [{'chunk': j['name'], 'why': j['why'], 'bytes': j['hi'] - j['lo'],
                                                                     'log_tail': j.get('log_tail', '')[-300:]} for j in crashed][:20],
        'exact': exact, 'parts_tol_gt_0p1mm': n_tol, 'workers': a.workers, 'mem_budget_bytes': budget,
        'peak_tree_rss_bytes': peak_tree, 'peak_worker_rss_bytes': max(peaks) if peaks else None,
        'max_chunk_bytes': max((res['_chunk_bytes'] for _, res in results), default=None),
        'max_extras_per_chunk': max((res['_extras'] for _, res in results), default=None),
        'occ_wall_sec': round(occ_wall, 1), 'kernel': results[0][1].get('kernel') if results else None,
        'parent_peak_rss_bytes': peak_rss_bytes()})
    if n_crashed or read_fail or n_exc_unknown:
        streamed['complete'] = False
    else:
        streamed['complete'] = True
    out['sec'] = round(time.time() - T0, 1)
    json.dump(out, open(a.out, 'w'))
    print(json.dumps({k: v for k, v in out.items() if k not in ('streamed', 'invalid_examples')}))
    if not a.keep:
        shutil.rmtree(wd, ignore_errors=True)
    return 0


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == '--worker':
        sys.exit(worker_main(sys.argv[2], sys.argv[3]))
    sys.exit(main())
