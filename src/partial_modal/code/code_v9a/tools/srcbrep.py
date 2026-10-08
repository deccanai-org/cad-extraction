#!/usr/bin/env python3
"""Exact source geometry of every product (IfcOpenShell kernel, world coordinates, metres, no faceting) written as one
BRep file per product. Runs in its own process: IfcOpenShell and build123d carry different OpenCASCADE builds.

The kernel's own account of the same run is kept for tools/reference_defects.py (evidence about the reference, never
used by a verification status), written beside OUT_DIR (in the schedule folder when verify.py runs this):
  source_kernel_log.jsonl   one line per kernel log message that names its product, grouped by product in the order the
                            kernel wrote them: {"guid", "level", "code", "message", "instance"} - e.g. GEO151 'Boolean
                            operation yields non-manifold result' followed by the retry with fewer operands; then one line
                            per distinct message that names no product, with its count ({"guid": null, ..., "count"}).
                            Not kept (named in the closing summary line): high-volume notices without evidence
                            (GEO122 operand OBB size, GEO133 'Operand A is manifold', GEO031 'No material and surface
                            styles', whose count also depends on the thread count), the run's timings (SYS028), the
                            per-thread precision notice (SYS033) and GEO321 'ContextType not allowed' (a shared context,
                            attributed to whichever product a thread met it with) - so the file is the same whatever the
                            thread count and the thread timing.
  source_brep_census.csv    per product the kernel shape's solids / shells / faces (a product whose B-rep holds no solid
                            has no source reference volume: verify.py reports it source_check n/a)
A representation the kernel evaluates once for several products logs under the first of them only.

usage: srcbrep.py MODEL.ifc OUT_DIR [threads] [--log LOG]
           LOG: where the kernel log goes (default OUT_DIR/../source_kernel_log.jsonl); source_brep_census.csv is written
           beside it. Named, never positional: a fourth positional argument is refused (other versions of this script
           took a file of GlobalIds there)
       srcbrep.py MODEL.ifc OUT_DIR --gross GUID[,GUID...]
           the base extrusion of every body item of those products, uncut and without openings: an IfcExtrudedAreaSolid
           that is a body item or the innermost first operand of an IfcBooleanResult chain (through mapped items), one
           BRep per extrusion (item coordinates, metres) + OUT_DIR/gross_index.json {guid: [file, ...]}"""
import sys, os, json, re, csv, collections
import ifcopenshell, ifcopenshell.geom as G
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract

W = ifcopenshell.ifcopenshell_wrapper
# SYS028 timings, SYS033 once per thread: vary run to run. GEO321 ('ContextType ... not allowed') is about a shared
# representation context, logged under whichever product a thread was evaluating when it first met the context: its
# attribution varies run to run (seen on cmctexas Revit), and it says nothing about a product's geometry
SKIP = {'GEO122', 'GEO133', 'GEO031', 'SYS028', 'SYS033', 'GEO321'}
_GUID = re.compile(r"^#\d+=\w+\('([0-9A-Za-z_$]{22})'")
_INST = re.compile(r"^(#\d+=\w+)")


def _settings():
    s = G.settings()
    s.set('use-world-coords', True)
    s.set('iterator-output', W.SERIALIZED)
    return s


def _census(bd):
    c = collections.Counter(line.strip() for line in bd.splitlines() if line.strip() in ('So', 'Sh', 'Fa'))
    return c['So'], c['Sh'], c['Fa']


class _Log:
    """drains the kernel log (json lines) and groups it by product"""

    def __init__(self):
        self.json = True
        try:
            W.set_log_format_json()
        except Exception:
            self.json = False
        ifcopenshell.get_log()                      # start empty
        self.by = collections.OrderedDict()
        self.loose = collections.Counter()
        self.skipped = set()

    def drain(self):
        for line in ifcopenshell.get_log().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line) if self.json else {'level': 'raw', 'code': '', 'message': line}
            except ValueError:
                d = {'level': 'raw', 'code': '', 'message': line}
            m = _GUID.match(d.get('product') or '')
            code = d.get('code', '')
            if code in SKIP:
                self.skipped.add(code)
                continue
            if m is None:
                self.loose[(d.get('level', ''), code, d.get('message', ''))] += 1
                continue
            inst = _INST.match(d.get('instance') or '')
            self.by.setdefault(m.group(1), []).append(dict(guid=m.group(1), level=d.get('level', ''), code=code,
                                                           message=d.get('message', ''), instance=inst.group(1) if inst else None))

    def write(self, path):
        tmp = path + '.tmp'
        with open(tmp, 'w') as fh:
            for g in sorted(self.by):
                for r in self.by[g]:
                    fh.write(json.dumps(r, separators=(',', ':')) + '\n')
            for (lv, code, msg), n in sorted(self.loose.items()):
                fh.write(json.dumps(dict(guid=None, level=lv, code=code, message=msg, count=n), separators=(',', ':')) + '\n')
            fh.write(json.dumps(dict(summary=dict(products_with_messages=len(self.by), messages_kept=sum(len(v) for v in self.by.values()),
                                                  messages_without_product=sum(self.loose.values()), not_kept=sorted(self.skipped))),
                                separators=(',', ':')) + '\n')
        os.replace(tmp, path)


def _base_extrusions(item, out):
    """IfcExtrudedAreaSolid leaves of a body item: the item itself, the innermost first operand of a boolean chain, the
    items of a mapped representation"""
    if item.is_a('IfcExtrudedAreaSolid'):
        out.append(item)
    elif item.is_a('IfcBooleanResult'):
        _base_extrusions(item.FirstOperand, out)
    elif item.is_a('IfcMappedItem'):
        for it in item.MappingSource.MappedRepresentation.Items:
            _base_extrusions(it, out)
    return out


def gross(f, out, guids):
    s = G.settings()
    s.set('iterator-output', W.SERIALIZED)
    idx = {}
    for g in guids:
        p = f.by_guid(g)
        items = []
        for r in (p.Representation.Representations if p.Representation else []):
            if r.RepresentationIdentifier in extract.BODY_IDS:
                for it in r.Items:
                    _base_extrusions(it, items)
        files = []
        for k, it in enumerate(items):
            try:
                sh = G.create_shape(s, it)
                bd = sh.brep_data if hasattr(sh, 'brep_data') else (sh.geometry.brep_data if hasattr(sh, 'geometry') else sh)
                fn = f'gross_{len(idx)}_{k}.brep'
                with open(os.path.join(out, fn), 'w') as fh:
                    fh.write(bd if isinstance(bd, str) else bd.decode())
                files.append(fn)
            except Exception as e:
                files.append(f'error: {type(e).__name__}: {e}')
        idx[g] = files
    json.dump(idx, open(os.path.join(out, 'gross_index.json'), 'w'), indent=1)
    print(len(idx))


def _args(argv):
    """(ifc, out, threads, log path, gross guids or None) from the command line (see usage)"""
    pos, log, grs, i = [], None, None, 0
    while i < len(argv):
        if argv[i] == '--log' and i + 1 < len(argv):
            log, i = argv[i + 1], i + 2
        elif argv[i] == '--gross' and i + 1 < len(argv):
            grs, i = [g for g in argv[i + 1].split(',') if g], i + 2
        elif argv[i].startswith('--'):
            sys.exit(f'srcbrep.py: unknown option {argv[i]}')
        else:
            pos.append(argv[i])
            i += 1
    if len(pos) < 2 or len(pos) > 3:
        sys.exit('usage: srcbrep.py MODEL.ifc OUT_DIR [threads] [--log LOG] | srcbrep.py MODEL.ifc OUT_DIR --gross GUIDS')
    ifc, out = pos[0], pos[1]
    th = int(pos[2]) if len(pos) > 2 else 4
    log = log or os.path.join(os.path.dirname(os.path.abspath(out)), 'source_kernel_log.jsonl')
    return ifc, out, th, log, grs


def main():
    ifc, out, th, logp, grs = _args(sys.argv[1:])
    os.makedirs(out, exist_ok=True)
    f = extract.open_ifc(ifc)
    if grs is not None:
        return gross(f, out, grs)
    log = _Log()
    it = G.iterator(_settings(), f, th)
    idx, census = {}, {}
    if it.initialize():
        while True:
            sh = it.get()
            bd = sh.geometry.brep_data
            bd = bd if isinstance(bd, str) else bd.decode()
            fn = f'{len(idx)}.brep'
            with open(os.path.join(out, fn), 'w') as fh:
                fh.write(bd)
            idx[sh.guid] = fn
            census[sh.guid] = _census(bd)
            if len(idx) % 1000 == 0:
                log.drain()
            if not it.next():
                break
    log.drain()
    json.dump(idx, open(os.path.join(out, 'index.json'), 'w'))
    log.write(logp)
    with open(os.path.join(os.path.dirname(logp), 'source_brep_census.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['part_id', 'solids', 'shells', 'faces'])
        for g in sorted(census):
            w.writerow([g, *census[g]])
    print(len(idx))


if __name__ == '__main__':
    main()
