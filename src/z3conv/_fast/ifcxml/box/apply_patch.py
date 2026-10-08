#!/usr/bin/env python3
"""apply_patch.py WORKER_IN WORKER_OUT - apply the ifcxml2spf integration to a fleet IFC worker.py (data-3 kit or data-4
kit). Pure text edits keyed on the unchanged code blocks (FILES tuple, sniff's XML test, the schema == 'ifcxml' branch);
fails loudly if a block is not found. Idempotent (an already patched worker is copied unchanged)."""
import re, sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
if 'XML2SPF' in s:
    open(dst, 'w').write(s); print('already patched'); sys.exit(0)
m = re.search(r"\nFILES = \((?:[^()]*)\)\n", s)
assert m, 'FILES tuple not found'
files = m.group(0)
files2 = files.rstrip('\n')[:-1].rstrip() + ", 'ifcxml2spf.py')\n"
add = ("XML2SPF = os.path.join(HERE, 'ifcxml2spf.py')          # ifcXML (ISO 10303-28 / IFC4 ifcXML) -> SPF, validated converter\n"
       "if os.path.exists(XML2SPF):\n    CODE = CODE + '+x1'\n")
s = s[:m.start()] + files2 + add + s[m.end():]
old = """    if head.lstrip()[:5] == b'<?xml' or b'<ifcXML' in head[:4096] or b'iso_10303_28' in head[:4096]:
        rec['format'] = 'ifcxml'; return 'ifcxml'"""
new = """    h0 = head.lstrip(b'\\xef\\xbb\\xbf \\r\\n\\t')
    if h0[:1] == b'<' or head[:2] in (b'\\xff\\xfe', b'\\xfe\\xff') or b'<ifcXML' in head[:4096] or b'iso_10303_28' in head[:4096]:
        rec['format'] = 'ifcxml'; return 'ifcxml'"""
assert old in s, 'sniff XML test not found'
s = s.replace(old, new)
old = """    if schema == 'ifcxml':
        x = src if src.lower().endswith('.ifcxml') else src + '.ifcXML'
        if x != src: os.replace(src, x)
        src = x
    else:"""
new = """    if schema == 'ifcxml' and os.path.exists(XML2SPF):
        # ifcXML -> SPF (every instance / value from the XML; nothing invented), then the normal SPF path
        spf = os.path.join(d, 'from_ifcxml.ifc'); xrep = os.path.join(d, 'ifcxml2spf.json')
        rcx = fl.run(jid, [PY, XML2SPF, src, spf, '--report', xrep], os.path.join(d, 'ifcxml2spf.log'), 3 * 3600, mem_frac=0.85)
        try:
            xr = json.load(open(xrep))
        except Exception:
            xr = {'status': 'error', 'rc': rcx, 'log': tail_of(os.path.join(d, 'ifcxml2spf.log'), 400)}
        rec['ifcxml'] = {k: xr.get(k) for k in ('version', 'status', 'reason', 'schema', 'container', 'member', 'xml_bytes',
                                                 'xml_root', 'first_elements', 'instances', 'references',
                                                 'dangling_references', 'value_errors', 'unknown_xml_names', 'sec')}
        rec['ifcxml']['rc'] = rcx
        if rcx == 2:
            root = (xr.get('xml_root') or '')
            reason = 'not_ifc_xml_tekla_export_to_revit' if root in ('NewDataSet', 'DocumentElement') else 'not_ifc_xml'
            return dict(rec, status='fail', reason=reason, detail=(xr.get('reason') or '')[:200])
        if rcx not in (0, 4) or not os.path.exists(spf):
            return dict(rec, status='fail', reason={3: 'ifcxml_parse_error', 5: 'ifcxml_unsupported_schema'}.get(rcx, 'ifcxml_convert_error'),
                        detail=(xr.get('reason') or str(xr.get('value_errors') or '')[:200]), log_tail=tail_of(os.path.join(d, 'ifcxml2spf.log')))
        rec.setdefault('input_fix', []).append('ifcxml_converted_to_spf' if rcx == 0 else 'ifcxml_converted_to_spf_with_dangling_references')
        src = spf
        try:
            schema = sniff(src, rec)
        except Fail as e:
            return dict(rec, status='fail', reason=e.reason, detail=e.detail)
        rec['format'] = 'ifcxml'
    if schema == 'ifcxml':
        x = src if src.lower().endswith('.ifcxml') else src + '.ifcXML'
        if x != src: os.replace(src, x)
        src = x
    else:"""
assert old in s, "schema == 'ifcxml' branch not found"
s = s.replace(old, new)
compile(s, dst, 'exec')
open(dst, 'w').write(s)
print('patched', src, '->', dst)
