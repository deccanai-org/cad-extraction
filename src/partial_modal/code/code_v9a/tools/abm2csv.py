#!/usr/bin/env python3
"""Advance bill of materials (ABM, legacy Excel .xls) -> CSV for kiss_check.py --weights.

An ABM sheet ("ADVANCE BILL OF MATERIALS") lists, per preliminary (ABM) mark, the quantity, size, material, order
length, weight in lb and sequence. The .xls files are read with a small pure-Python BIFF8 reader (OLE2 compound file,
cell values only): no Excel, no third-party package.

usage: abm2csv.py OUT.csv ABM.xls [ABM.xls ...]
       abm2csv.py --dump FILE.xls            (print every sheet as tab separated text)
columns: source, date, rev, job, mark, qty, size, grade, length_text, length_mm, weight_lbs, seq, row
"""
import csv, os, re, struct, sys


def _cfb_streams(data):
    if data[:8] != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        raise ValueError('not an OLE2 compound file')
    ss = 1 << struct.unpack_from('<H', data, 30)[0]
    mss = 1 << struct.unpack_from('<H', data, 32)[0]
    n_fat = struct.unpack_from('<I', data, 44)[0]
    dir_start = struct.unpack_from('<I', data, 48)[0]
    cutoff = struct.unpack_from('<I', data, 56)[0]
    mfat_start = struct.unpack_from('<I', data, 60)[0]
    difat_start = struct.unpack_from('<I', data, 68)[0]
    n_difat = struct.unpack_from('<I', data, 72)[0]

    def sector(i):
        o = 512 + i * ss if ss == 512 else ss * (i + 1)
        return data[o:o + ss]
    difat = list(struct.unpack_from('<109I', data, 76))
    d = difat_start
    for _ in range(n_difat):
        if d >= 0xFFFFFFFA:
            break
        s = sector(d)
        vals = struct.unpack_from('<%dI' % (ss // 4), s)
        difat += vals[:-1]
        d = vals[-1]
    fat = []
    for i in difat[:n_fat]:
        fat += struct.unpack_from('<%dI' % (ss // 4), sector(i))

    def chain(start, table):
        out, seen = [], set()
        while start < 0xFFFFFFFA and start not in seen:
            seen.add(start)
            out.append(start)
            start = table[start] if start < len(table) else 0xFFFFFFFE
        return out

    def read_big(start, size=None):
        b = b''.join(sector(i) for i in chain(start, fat))
        return b if size is None else b[:size]
    dirdata = read_big(dir_start)
    entries = []
    for o in range(0, len(dirdata) - 127, 128):
        nl = struct.unpack_from('<H', dirdata, o + 64)[0]
        name = dirdata[o:o + max(0, nl - 2)].decode('utf-16-le', 'replace')
        typ = dirdata[o + 66]
        start, size = struct.unpack_from('<II', dirdata, o + 116)
        entries.append((name, typ, start, size))
    root = entries[0]
    ministream = read_big(root[2], root[3]) if root[3] else b''
    mfat = []
    if mfat_start < 0xFFFFFFFA:
        mb = read_big(mfat_start)
        mfat = list(struct.unpack_from('<%dI' % (len(mb) // 4), mb))
    out = {}
    for name, typ, start, size in entries[1:]:
        if typ != 2:
            continue
        if size < cutoff:
            b = b''.join(ministream[i * mss:(i + 1) * mss] for i in chain(start, mfat))[:size]
        else:
            b = read_big(start, size)
        out[name] = b
    return out


def _rk(v):
    if v & 2:
        x = v >> 2
        if x & 0x20000000:
            x -= 0x40000000
        x = float(x)
    else:
        x = struct.unpack('<d', struct.pack('<Q', (v & 0xFFFFFFFC) << 32))[0]
    return x / 100.0 if v & 1 else x


class _Reader:
    """reads unicode strings that may continue across CONTINUE record boundaries"""

    def __init__(self, chunks):
        self.chunks, self.ci, self.pos = chunks, 0, 0

    def _need(self):
        while self.ci < len(self.chunks) and self.pos >= len(self.chunks[self.ci]):
            self.ci += 1
            self.pos = 0

    def bytes(self, n):
        out = b''
        while n > 0:
            self._need()
            c = self.chunks[self.ci]
            take = min(n, len(c) - self.pos)
            out += c[self.pos:self.pos + take]
            self.pos += take
            n -= take
        return out

    def u8(self):
        return self.bytes(1)[0]

    def u16(self):
        return struct.unpack('<H', self.bytes(2))[0]

    def u32(self):
        return struct.unpack('<I', self.bytes(4))[0]

    def string(self, cch_bytes=2):
        cch = self.u16() if cch_bytes == 2 else self.u8()
        flags = self.u8()
        high = flags & 1
        nrun = self.u16() if flags & 8 else 0
        ext = self.u32() if flags & 4 else 0
        chars = []
        left = cch
        while left > 0:
            self._need()
            c = self.chunks[self.ci]
            avail = (len(c) - self.pos) // (2 if high else 1)
            if avail <= 0:              # string continues in the next CONTINUE record: new flag byte
                self.ci += 1
                self.pos = 0
                high = self.u8() & 1
                continue
            take = min(left, avail)
            raw = self.bytes(take * (2 if high else 1))
            chars.append(raw.decode('utf-16-le' if high else 'latin-1', 'replace'))
            left -= take
        if nrun:
            self.bytes(4 * nrun)
        if ext:
            self.bytes(ext)
        return ''.join(chars)


def read_xls(path):
    streams = _cfb_streams(open(path, 'rb').read())
    wb = streams.get('Workbook') or streams.get('Book')
    if wb is None:
        raise ValueError('no Workbook stream')
    recs = []
    o = 0
    while o + 4 <= len(wb):
        t, n = struct.unpack_from('<HH', wb, o)
        recs.append((t, wb[o + 4:o + 4 + n], o))
        o += 4 + n
    sheets = []
    sst = []
    i = 0
    while i < len(recs):
        t, d, off = recs[i]
        if t == 0x0085:
            pos = struct.unpack_from('<I', d, 0)[0]
            r = _Reader([d[6:]])
            sheets.append((pos, r.string(cch_bytes=1)))
        elif t == 0x00FC:
            chunks = [d[8:]]
            j = i + 1
            while j < len(recs) and recs[j][0] == 0x003C:
                chunks.append(recs[j][1])
                j += 1
            total = struct.unpack_from('<I', d, 4)[0]
            r = _Reader(chunks)
            for _ in range(total):
                try:
                    sst.append(r.string())
                except IndexError:
                    break
            i = j - 1
        elif t == 0x000A and sheets:
            break
        i += 1
    offs = {off: k for k, (_, _, off) in enumerate(recs)}
    out = {}
    for pos, name in sheets:
        cells = {}
        k = offs.get(pos)
        if k is None:
            continue
        pending = None
        for t, d, _ in recs[k + 1:]:
            if t == 0x000A:
                break
            if t == 0x00FD:
                r, c, _, s = struct.unpack_from('<HHHI', d)
                cells[(r, c)] = sst[s] if s < len(sst) else ''
            elif t == 0x0203:
                r, c, _ = struct.unpack_from('<HHH', d)
                cells[(r, c)] = struct.unpack_from('<d', d, 6)[0]
            elif t == 0x027E:
                r, c, _, v = struct.unpack_from('<HHHI', d)
                cells[(r, c)] = _rk(v)
            elif t == 0x00BD:
                r, c0 = struct.unpack_from('<HH', d)
                n = (len(d) - 6) // 6
                for q in range(n):
                    _, v = struct.unpack_from('<HI', d, 4 + 6 * q)
                    cells[(r, c0 + q)] = _rk(v)
            elif t == 0x0204:
                r, c, _ = struct.unpack_from('<HHH', d)
                cells[(r, c)] = _Reader([d[6:]]).string()
            elif t == 0x0006:
                r, c, _ = struct.unpack_from('<HHH', d)
                res = d[6:14]
                if res[6:8] == b'\xff\xff':
                    if res[0] == 0:
                        pending = (r, c)
                    elif res[0] == 1:
                        cells[(r, c)] = bool(res[2])
                else:
                    cells[(r, c)] = struct.unpack('<d', res)[0]
            elif t == 0x0207 and pending is not None:
                cells[pending] = _Reader([d]).string()
                pending = None
            elif t == 0x0205:
                r, c, _, v, e = struct.unpack_from('<HHHBB', d)
                if not e:
                    cells[(r, c)] = bool(v)
        out[name] = cells
    return out


def rows(cells):
    if not cells:
        return []
    nr = max(r for r, _ in cells) + 1
    nc = max(c for _, c in cells) + 1
    return [[cells.get((r, c), '') for c in range(nc)] for r in range(nr)]



def _txt(v):
    if isinstance(v, float):
        return ('%d' % v) if v == int(v) else ('%g' % v)
    return str(v).strip()


def parse_ftin(s):
    """17'-11'' / 10'-0" / 6'-0 1/2" / 2'-7 1/2" -> inches"""
    t = s.replace("''", '"').replace('\u2019', "'").strip()
    m = re.fullmatch(r"(\d+)\s*'\s*-?\s*(\d+)?(?:\s+(\d+)\s*/\s*(\d+))?\s*\"?", t)
    if not m:
        m2 = re.fullmatch(r"(\d+)?(?:\s+(\d+)\s*/\s*(\d+))?\s*\"", t)
        if not m2 or not (m2.group(1) or m2.group(2)):
            return None
        v = float(m2.group(1) or 0)
        if m2.group(2):
            v += float(m2.group(2)) / float(m2.group(3))
        return v
    v = float(m.group(1)) * 12 + float(m.group(2) or 0)
    if m.group(3):
        v += float(m.group(3)) / float(m.group(4))
    return v


def abm_rows(path):
    out = []
    for sheet, cells in read_xls(path).items():
        R = rows(cells)
        date = rev = job = ''
        hdr = None
        for i, r in enumerate(R):
            line = ' '.join(_txt(v) for v in r if _txt(v))
            m = re.search(r'Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})', line)
            if m and not date:
                date = f'{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
            m = re.search(r'\bRev-?\s*(\w+)', line)
            if m and not rev:
                rev = m.group(1)
            m = re.search(r'JOB NO:\s*([\w-]+)', line, re.I)
            if m and not job:
                job = m.group(1)
            low = [_txt(v).lower() for v in r]
            if 'qty' in low and 'abm_mark' in low:
                hdr = (i, {k: low.index(k) for k in low if k})
                break
        if hdr is None:
            continue
        i0, col = hdr
        def c(r, *names):
            for n in names:
                for k, j in col.items():
                    if k.startswith(n) and j < len(r):
                        return r[j]
            return ''
        for i in range(i0 + 1, len(R)):
            r = R[i]
            q, mk = c(r, 'qty'), _txt(c(r, 'abm_mark'))
            if not isinstance(q, float) or not mk:
                continue
            lt = _txt(c(r, 'length'))
            li = parse_ftin(lt)
            w = c(r, 'weight')
            out.append(dict(source=os.path.basename(path), date=date, rev=rev, job=job, mark=mk, qty=int(q),
                            size=_txt(c(r, 'size')), grade=_txt(c(r, 'material')), length_text=lt,
                            length_mm='' if li is None else round(li * 25.4, 2),
                            weight_lbs=w if isinstance(w, float) else '', seq=_txt(c(r, 'seq')), row=i + 1))
    return out


def main(argv):
    if argv[:1] == ['--dump']:
        for name, cells in read_xls(argv[1]).items():
            print('### sheet', name, len(cells), 'cells')
            for row in rows(cells):
                print('\t'.join(_txt(v) for v in row))
        return 0
    out, files = argv[0], argv[1:]
    allr = []
    for f in sorted(files):
        allr += abm_rows(f)
    cols = ['source', 'date', 'rev', 'job', 'mark', 'qty', 'size', 'grade', 'length_text', 'length_mm', 'weight_lbs', 'seq', 'row']
    with open(out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(allr)
    print(len(allr), 'ABM rows from', len(files), 'files ->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
