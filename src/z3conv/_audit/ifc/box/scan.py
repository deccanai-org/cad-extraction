#!/usr/bin/env python3
"""IFC audit source scan (read-only): for every distinct data-3 IFC content (contents_ifc.jsonl.gz) download the stored
source copy, unpack like the fleet worker (zip: largest .ifc member, all members listed; gzip), read the SPF header
(FILE_DESCRIPTION / FILE_NAME / FILE_SCHEMA), stream an entity-type census over the whole file (+ NUL bytes, header
blocks, IfcApplication), then run graph.py (ifcopenshell 0.9.0, retry 0.8.4) for body kinds x openings, with an
openings-volume sample for models that have transcoded products with openings, compared with the STEP part volumes
of the current STEP (detail step_parts). One json per model in out/, merged to scan.jsonl.gz and uploaded.
usage: scan.py [--limit N] [--ids a,b] [--small-procs 12] [--big-procs 3]"""
import os, sys, json, gzip, re, time, zipfile, shutil, subprocess, collections, traceback, argparse, zlib
from multiprocessing import Pool
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'; ROOT = 'cad-disk-extract/zenitude-data-3'; ST = ROOT + '/_state/conv'
OUTK = ROOT + '/_state/agentwork/audit-ifc'
W = '/work/agentwork/audit-ifc'
PY = '/opt/conv/env/bin/python'; PY84 = '/opt/conv/ifc84/bin/python'
BIG = 100 << 20
NVOL = 8
ENT = re.compile(rb'#\d+\s*=\s*([A-Za-z][A-Za-z0-9_]*)\s*\(')
APP = re.compile(rb'IFCAPPLICATION\s*\(([^;]{0,400})\)\s*;', re.I)


def s3c():
    return boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 10, 'mode': 'standard'}))


def step_strings(s):
    """tokens of a STEP header argument list: strings (with '' escapes) and $ / *"""
    out = []; i = 0; n = len(s)
    while i < n:
        c = s[i]
        if c == "'":
            j = i + 1; buf = []
            while j < n:
                if s[j] == "'":
                    if j + 1 < n and s[j + 1] == "'":
                        buf.append("'"); j += 2; continue
                    break
                buf.append(s[j]); j += 1
            out.append(''.join(buf)); i = j + 1
        else:
            i += 1
    return out


def header(head):
    h = head.decode('latin1', 'replace')
    o = {}
    for key in ('FILE_DESCRIPTION', 'FILE_NAME', 'FILE_SCHEMA'):
        m = re.search(key + r'\s*\((.*?)\)\s*;', h, re.S)
        if m:
            o[key] = step_strings(m.group(1))[:12]
    fn = o.get('FILE_NAME') or []
    # FILE_NAME(name, time_stamp, (author), (organization), preprocessor_version, originating_system, authorization)
    o['fn_name'] = fn[0][:120] if fn else None
    o['fn_time'] = fn[1][:40] if len(fn) > 1 else None
    if len(fn) >= 3:
        o['fn_preprocessor'] = fn[-3][:160]; o['fn_originating'] = fn[-2][:160]
    o['schema'] = (o.get('FILE_SCHEMA') or [None])[0]
    o['view'] = ' | '.join((o.get('FILE_DESCRIPTION') or [])[:2])[:200]
    return o


def unpack(raw, dst, rec):
    with open(raw, 'rb') as fh:
        head = fh.read(8)
    if head[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(raw) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            rec['zip'] = {'members': len(infos), 'list': [[i.filename[-120:], i.file_size] for i in infos][:40]}
            ifcs = [i for i in infos if i.filename.lower().endswith(('.ifc', '.ifcxml'))]
            rec['zip']['ifc_members'] = len(ifcs)
            rec['zip']['ifc_member_bytes'] = sorted([i.file_size for i in ifcs], reverse=True)[:20]
            cand = ifcs or infos
            if not cand:
                rec['zip']['empty'] = True; return None
            m = max(cand, key=lambda i: i.file_size)
            rec['zip']['chosen'] = m.filename[-160:]
            out = dst + ('.ifcXML' if m.filename.lower().endswith('.ifcxml') else '.ifc')
            try:
                with z.open(m) as a, open(out, 'wb') as b:
                    shutil.copyfileobj(a, b, 1 << 24)
            except Exception as e:
                rec['zip']['error'] = f'{type(e).__name__}: {str(e)[:150]}'; return None
            with open(out, 'rb') as fh:
                if fh.read(4) == b'PK\x03\x04':
                    rec['zip']['nested'] = True
                    return unpack(out, dst + '.in', rec)
            return out
    if head[:2] == b'\x1f\x8b':
        out = dst + '.ifc'
        import gzip as gz
        with gz.open(raw) as a, open(out, 'wb') as b:
            shutil.copyfileobj(a, b, 1 << 24)
        rec['gzip'] = True
        return out
    if head[:8] == bytes.fromhex('D0CF11E0A1B11AE1'):
        rec['ole2'] = True
    return raw


def text_census(path, rec):
    size = os.path.getsize(path)
    types = collections.Counter(); nul = 0; iso = 0; endiso = 0; apps = []; carry = b''
    first_non_nul = None; last_non_nul = None; off = 0
    with open(path, 'rb') as fh:
        while True:
            ch = fh.read(64 << 20)
            if not ch:
                break
            n0 = ch.count(b'\x00'); nul += n0
            if n0 < len(ch):
                if first_non_nul is None:
                    first_non_nul = off + len(ch) - len(ch.lstrip(b'\x00'))
                last_non_nul = off + len(ch.rstrip(b'\x00')) - 1
            off += len(ch)
            buf = carry + ch
            cut = buf.rfind(b';')
            if cut < 0:
                carry = buf[-(1 << 20):]; continue
            body, carry = buf[:cut + 1], buf[cut + 1:]
            for m in ENT.finditer(body):
                types[m.group(1).upper().decode("latin1")] += 1
            endiso += body.count(b'END-ISO-10303-21;')
            iso += body.count(b'ISO-10303-21;')
            if len(apps) < 5:
                for m in APP.finditer(body):
                    apps.append(m.group(1)[:300].decode('latin1', 'replace'))
                    if len(apps) >= 5:
                        break
        if carry:
            for m in ENT.finditer(carry):
                types[m.group(1).upper().decode("latin1")] += 1
            endiso += carry.count(b'END-ISO-10303-21;'); iso += carry.count(b'ISO-10303-21;')
    rec['bytes'] = size; rec['nul_bytes'] = nul; rec['first_non_nul'] = first_non_nul; rec['last_non_nul'] = last_non_nul
    rec['spf_blocks'] = iso - endiso; rec['end_iso'] = endiso
    rec['entities'] = sum(types.values()); rec['types_n'] = len(types)
    rec['types'] = dict(types.most_common(400))
    rec['ifcapplication_text'] = apps


def detail_key(mi, mid):
    sk = (mi or {}).get('step_key') or ''
    if mi and mi.get('reused'):
        return f'{ST}/grade/detail/ifc-{mid}.step_parts.jsonl.gz'
    if sk.endswith('.v6.step'):
        return f'{ST}/ifc/detail/{mid}.v6.step_parts.jsonl.gz'
    return f'{ST}/ifc/detail/{mid}.step_parts.jsonl.gz'


def compare_step(s3, mid, mi, samples, rec):
    key = detail_key(mi, mid)
    try:
        body = s3.get_object(Bucket=B, Key=key)['Body'].read()
        rows = [json.loads(l) for l in gzip.decompress(body).decode().splitlines() if l.strip()]
    except Exception as e:
        rec['step_parts_error'] = f'{key[-80:]}: {type(e).__name__}'; return
    bypid = collections.defaultdict(list); byname = collections.defaultdict(list)
    for r in rows:
        bypid[r.get('pid')].append(r); byname[r.get('name')].append(r)
    rec['step_parts_key'] = key; rec['step_parts_n'] = len(rows)
    for smp in samples:
        if smp.get('error') or smp.get('uncut_vol') is None:
            smp['verdict'] = 'kernel_error'; continue
        cands = bypid.get(smp['gid']) or []
        how = 'gid'
        if not cands:
            nm = byname.get(smp.get('name')) or []
            if len(nm) == 1:
                cands = nm; how = 'name_unique'
            elif nm:
                cands = nm; how = 'name_multi'
        both_closed = smp.get('cut_closed') and smp.get('uncut_closed')
        cv, uv = smp['cut_vol'], smp['uncut_vol']
        ca, ua = smp['cut_area'], smp['uncut_area']
        eff = (1 - cv / uv) if (both_closed and uv) else ((ca - ua) / ua if ua else None)   # volume removed / area change
        smp['opening_effect'] = round(eff, 5) if eff is not None else None
        smp['effect_basis'] = 'volume' if both_closed else 'area'
        if eff is not None and abs(eff) < 5e-4:
            smp['verdict'] = 'opening_no_effect'; continue
        if not cands:
            smp['verdict'] = 'step_part_not_found'; continue
        # among the candidates (name_multi: all same-name parts) take the one closest to either expectation
        best = None
        for c in cands:
            v = c.get('volume')
            if not v or not c.get('solids'):
                continue
            rc_, ru_ = v / cv if cv else None, v / uv if uv else None
            d = min(abs((rc_ or 9) - 1), abs((ru_ or 9) - 1))
            if best is None or d < best[0]:
                best = (d, v, rc_, ru_)
        smp['match'] = how
        if best is None:
            smp['verdict'] = 'step_part_surface_only'; continue
        _, v, rc_, ru_ = best
        smp['step_vol'] = round(v, 1); smp['step_over_cut'] = round(rc_, 5) if rc_ else None; smp['step_over_uncut'] = round(ru_, 5) if ru_ else None
        if not both_closed:
            smp['verdict'] = 'kernel_mesh_open'
        elif abs(ru_ - 1) < 0.002 and abs(rc_ - 1) > abs(ru_ - 1):
            smp['verdict'] = 'step_uncut'
        elif abs(rc_ - 1) < 0.002:
            smp['verdict'] = 'step_cut'
        else:
            smp['verdict'] = 'step_other'


def process(args):
    c, mi = args
    mid = c['id']; d = os.path.join(W, 'src', mid[:20]); outp = os.path.join(W, 'out', mid + '.json')
    if os.path.exists(outp):
        return mid, 'skip'
    os.makedirs(d, exist_ok=True)
    rec = {'id': mid, 'size': c.get('size'), 'kind': c.get('kind'), 'input_from': c.get('input_from'), 'action': c.get('action'),
           'path0': (c.get('paths') or [''])[0][-200:], 'n_paths': c.get('n_paths'), 'info': mi}
    t0 = time.time(); s3 = s3c()
    try:
        raw = os.path.join(d, 'in.bin')
        s3.download_file(B, c['input_key'], raw)
        src = unpack(raw, os.path.join(d, 'unz'), rec)
        if src:
            with open(src, 'rb') as fh:
                head = fh.read(256 << 10)
            rec['xml'] = head.lstrip()[:5] == b'<?xml' or b'<ifcXML' in head[:4096] or b'iso_10303_28' in head[:4096]
            rec['hdr'] = header(head)
            with open(src, 'rb') as fh:
                fh.seek(max(0, os.path.getsize(src) - 4096)); tail = fh.read()
            rec['terminated'] = tail.rstrip(b'\x00 \r\n\t\x1a').endswith(b'END-ISO-10303-21;')
            text_census(src, rec)
            sch = (rec['hdr'].get('schema') or '').upper()
            gsrc = src
            if sch in ('IFC2X2_FINAL', 'IFC2X_FINAL', 'IFC2X2', 'IFC2X', 'IFC2X3_TC1', 'IFC2X3_FINAL'):
                data = open(src, 'rb').read()
                m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", data[:1 << 16])
                gsrc = os.path.join(d, 'relabel.ifc')
                open(gsrc, 'wb').write(data[:m.start(1)] + b'IFC2X3' + data[m.end(1):]); del data
                rec['graph_relabel'] = sch + '->IFC2X3'
            if sch.startswith('IFC') and not rec.get('xml') and rec.get('entities'):
                nv = NVOL if (mi or {}).get('step_key') else 0
                to = int(min(3 * 3600, 900 + 6 * (os.path.getsize(gsrc) >> 20)))
                for py in (PY, PY84):
                    gj = os.path.join(d, 'graph.json')
                    try:
                        p = subprocess.run([py, os.path.join(W, 'graph.py'), gsrc, gj, str(nv)], capture_output=True, timeout=to)
                        rc = p.returncode; err = p.stderr.decode('latin1', 'replace')[-400:]
                    except subprocess.TimeoutExpired:
                        rc = 'timeout'; err = ''
                    if rc == 0 and os.path.exists(gj):
                        rec['graph'] = json.load(open(gj)); rec['graph']['python'] = py; break
                    rec.setdefault('graph_errors', []).append({'py': py, 'rc': rc, 'err': err})
                if rec.get('graph', {}).get('vol_samples'):
                    compare_step(s3, mid, mi, rec['graph']['vol_samples'], rec)
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {str(e)[:300]}'; rec['trace'] = traceback.format_exc()[-800:]
    finally:
        shutil.rmtree(d, ignore_errors=True)
    rec['sec'] = round(time.time() - t0, 1)
    with open(outp + '.tmp', 'w') as fh:
        json.dump(rec, fh, default=str)
    os.replace(outp + '.tmp', outp)
    return mid, 'ok' if 'error' not in rec else 'error'


def progress(n_all, tag):
    done = len([x for x in os.listdir(os.path.join(W, 'out')) if x.endswith('.json')])
    s3c().put_object(Bucket=B, Key=OUTK + '/progress.json', Body=json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'done': done, 'of': n_all, 'phase': tag}).encode())
    return done


def merge():
    p = os.path.join(W, 'scan.jsonl.gz')
    with gzip.open(p, 'wt') as f:
        for x in sorted(os.listdir(os.path.join(W, 'out'))):
            if x.endswith('.json'):
                f.write(open(os.path.join(W, 'out', x)).read().strip() + '\n')
    s3c().upload_file(p, B, OUTK + '/scan.jsonl.gz')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--limit', type=int); ap.add_argument('--ids'); ap.add_argument('--small-procs', type=int, default=12)
    ap.add_argument('--big-procs', type=int, default=3); ap.add_argument('--big-only', action='store_true'); ap.add_argument('--reverse', action='store_true')
    a = ap.parse_args()
    os.makedirs(os.path.join(W, 'out'), exist_ok=True); os.makedirs(os.path.join(W, 'src'), exist_ok=True)
    cont = [json.loads(l) for l in gzip.open(os.path.join(W, 'contents_ifc.jsonl.gz'), 'rt')]
    info = json.load(open(os.path.join(W, 'model_info.json')))
    if a.ids:
        want = set(a.ids.split(','))
        cont = [c for c in cont if c['id'] in want or c['id'][:16] in want]
    if a.limit:
        cont = cont[:a.limit]
    small = [(c, info.get(c['id'])) for c in cont if (c.get('size') or 0) < BIG]
    big = sorted([(c, info.get(c['id'])) for c in cont if (c.get('size') or 0) >= BIG], key=lambda x: -(x[0].get('size') or 0))
    if a.big_only:
        small = []
    if a.reverse:
        big = big[::-1]
    print('models', len(cont), 'small', len(small), 'big', len(big), flush=True)
    t0 = time.time()
    ps = Pool(a.small_procs, maxtasksperchild=20); pb = Pool(a.big_procs, maxtasksperchild=1)
    rs = ps.imap_unordered(process, small, chunksize=1); rb = pb.imap_unordered(process, big, chunksize=1)
    import threading
    stop = [False]
    def mon():
        while not stop[0] and not a.big_only:
            try:
                n = progress(len(cont), 'scan')
                print(time.strftime('%H:%M:%S'), 'done', n, '/', len(cont), round(time.time() - t0), 's', flush=True)
            except Exception as e:
                print('progress error', e, flush=True)
            time.sleep(60)
    threading.Thread(target=mon, daemon=True).start()
    st = collections.Counter()
    for mid, s in rs:
        st[s] += 1
    for mid, s in rb:
        st[s] += 1
    ps.close(); pb.close(); ps.join(); pb.join(); stop[0] = True
    print('status', dict(st), 'sec', round(time.time() - t0), flush=True)
    if not a.big_only:
        merge(); progress(len(cont), 'merged')
    print('MERGED', flush=True)


if __name__ == '__main__':
    main()
