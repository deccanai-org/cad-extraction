#!/usr/bin/env python3
"""stepcmp.py A.step B.step [--map OUT.json]

Exact comparison of two ifc2step6 STEP files (one entity per line) up to
  - the FILE_NAME header line (write time; reported, not compared),
  - entity instance numbering: ifc2step6 numbers each part's entities as its worker threads finish, so two runs of the
    same input write the same lines in the same order with different #numbers. Every '#n' (definition and reference) is
    replaced by the LINE NUMBER that defines #n in its own file; the files then compare byte for byte - an exact graph
    identity (same entities, same attributes, same references) given the line order,
  - PRODUCT.id (first attribute of PRODUCT = IFC GlobalId): aligned instead of compared -> map A id -> B id (must be a
    bijection; with --require-ids every id must also be equal).
Prints one JSON line."""
import json, re, sys
REF = re.compile(rb'#(\d+)')
DEF = re.compile(rb'^#(\d+)=')
PROD = re.compile(rb"^(#L\d+=PRODUCT\(')([^']*)('.*)$", re.S)


def defs(path):
    m = {}
    with open(path, 'rb') as f:
        for i, line in enumerate(f):
            d = DEF.match(line)
            if d:
                m[int(d.group(1))] = i
    return m


def canon(line, m):
    return REF.sub(lambda x: b'#L%d' % m.get(int(x.group(1)), -1), line)


def main():
    a, b = sys.argv[1], sys.argv[2]
    mp = sys.argv[sys.argv.index('--map') + 1] if '--map' in sys.argv else None
    ma, mb = defs(a), defs(b)
    out = {'a': a, 'b': b, 'entities_a': len(ma), 'entities_b': len(mb)}
    fa, fb = open(a, 'rb'), open(b, 'rb')
    n = 0; nprod = 0; ndiff = 0; samples = []; amap = {}; bseen = set(); fname = []; renum = 0
    while True:
        la = fa.readline(); lb = fb.readline()
        if not la and not lb:
            break
        n += 1
        if la.startswith(b'FILE_NAME(') and lb.startswith(b'FILE_NAME('):
            fname.append([la.decode('latin-1').strip(), lb.decode('latin-1').strip()])
            continue
        if la != lb:
            renum += 1
        ca, cb = canon(la, ma), canon(lb, mb)
        pa, pb = PROD.match(ca), PROD.match(cb)
        if pa and pb and pa.group(1) == pb.group(1) and pa.group(3) == pb.group(3):
            ga, gb = pa.group(2).decode(), pb.group(2).decode()
            nprod += 1
            if (ga in amap and amap[ga] != gb) or (ga not in amap and gb in bseen):
                ndiff += 1
                if len(samples) < 5:
                    samples.append({'line': n, 'why': 'PRODUCT.id map is not a bijection', 'a': la[:200].decode('latin-1')})
            amap[ga] = gb; bseen.add(gb)
            continue
        if ca == cb:
            continue
        ndiff += 1
        if len(samples) < 5:
            samples.append({'line': n, 'a': la[:300].decode('latin-1'), 'b': lb[:300].decode('latin-1')})
        if not la or not lb:
            rest = fa if la else fb
            for _ in rest:
                ndiff += 1; n += 1
            break
    out.update(lines=n, lines_renumbered=renum, products=nprod, diff_lines=ndiff, identical_modulo_ids=ndiff == 0,
               ids_identical=bool(amap) and all(k == v for k, v in amap.items()), file_name=fname, samples=samples)
    if mp:
        json.dump(amap, open(mp, 'w'))
    print(json.dumps(out))


if __name__ == '__main__':
    main()
