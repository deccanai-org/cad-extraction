"""audit_patch.py KIT_DIR : insert a read-only per-bolt dump (env DB1_AUDIT_DUMP=path.json.gz) into db1step.py of a kit copy.
No geometry or bookkeeping is changed; the dump is written next to the stats just before st['parts_list'] = plist (both paths)."""
import sys, os
p = os.path.join(sys.argv[1], 'db1step.py')
s = open(p).read()
if 'DB1_AUDIT_DUMP' in s:
    print('already patched'); sys.exit(0)

OLD = """    st['parts_list'] = plist
    hz = [m for m in M if not m.get('cut') and abs(m['x'][2]) < 0.1 and m['L'] > 500]
    yv = sum(1 for m in hz if abs(m['y'][2]) > 0.996) / len(hz) if hz else None
    hzI = [m for m in hz if m.get('prof') and section_for(m['prof'], cat)[0] == 'I']"""
OLD_DUMP = """    if os.environ.get('DB1_AUDIT_DUMP'):
        import gzip as _gz
        _hc = collections.Counter(i for v in part_bolts.values() for i in v)
        _gm = {m.get('pid'): m for m in M if m.get('bolt')}
        _bd = []
        for _i, bb in enumerate(BL):
            sg = bb.get('std') or {}
            gm = _gm.get(bb.get('pid')) or {}
            _bd.append({'g': bb.get('pid'), 'prof': gm.get('prof'), 'mat': gm.get('mat'), 'standard': bb.get('standard'), 'd': bb.get('d'),
                        'd_stored': bb.get('d_stored'), 'L': bb.get('L'), 'src': (sg.get('source') or 'table') if sg else None,
                        'family': sg.get('family'), 'mapping': sg.get('mapping'), 'head_af': sg.get('head_af'), 'head_h': sg.get('head_h'),
                        'nut_af': sg.get('nut_af'), 'nut_h': sg.get('nut_h'), 'washer_t': sg.get('washer_t'), 'washer_od': sg.get('washer_od'),
                        'tol': bb.get('tol'), 'holes_only': bb.get('holes_only'), 'wh': bb.get('wash_head'), 'wn': bb.get('wash_nut'),
                        'w2': bb.get('wash_2'), 'nuts': bb.get('nuts'), 'axial_decoded': bb.get('axial_decoded'), 'head_up': bb.get('head_up'),
                        'shift': bb.get('shift'), 'washer_exact': db1bolts.washer_exact(bb), 'washer_dims': db1bolts.washer_dims(bb),
                        'holes': _hc.get(_i, 0), 'plies': len(spans[_i]) if _i < len(spans) else None})
        json.dump({'path': 'old', 'bolts': _bd}, _gz.open(os.environ['DB1_AUDIT_DUMP'], 'wt'), default=str)
"""
NEW = """    st['parts_list'] = plist
    st['cuts_applied'] = applied"""
NEW_DUMP = """    if os.environ.get('DB1_AUDIT_DUMP'):
        import gzip as _gz
        _hc = collections.Counter(id(x[0]) for v in HP.values() for x in v)
        _bd = []; _gr = []
        for g in bgroups:
            bl_ = BG.get(g['seq']) or []
            _gr.append({'g': g['seq'], 'prof': g.get('prof'), 'standard': g.get('standard'), 'd': g.get('d'), 'L': g.get('L'), 'tol': g.get('tol'),
                        'flagbits': g.get('flagbits'), 'slot_parts': g.get('slot_parts'), 'slot_x': g.get('slot_x'), 'slot_y': g.get('slot_y'),
                        'n': len(g.get('uv') or []), 'placed': len(bl_)})
            for bb in bl_:
                sg = bb.get('std') or {}
                _bd.append({'g': g['seq'], 'prof': g.get('prof'), 'standard': bb.get('standard'), 'd': bb.get('d'), 'd_stored': bb.get('d_stored'),
                            'L': bb.get('L'), 'src': (sg.get('source') or 'table') if sg else None, 'family': sg.get('family'),
                            'mapping': sg.get('mapping'), 'head_af': sg.get('head_af'), 'head_h': sg.get('head_h'), 'nut_af': sg.get('nut_af'),
                            'nut_h': sg.get('nut_h'), 'washer_t': sg.get('washer_t'), 'washer_od': sg.get('washer_od'), 'tol': bb.get('tol'),
                            'holes_only': bb.get('holes_only'), 'wh': bb.get('wash_head'), 'wn': bb.get('wash_nut'), 'w2': bb.get('wash_2'),
                            'nuts': bb.get('nuts'), 'axial_decoded': bb.get('axial_decoded'), 'axial': bb.get('axial'), 'head_up': bb.get('head_up'),
                            'washer_exact': db1bolts.washer_exact(bb), 'washer_dims': db1bolts.washer_dims(bb), 'holes': _hc.get(id(bb), 0)})
        json.dump({'path': 'v2', 'bolts': _bd, 'groups': _gr}, _gz.open(os.environ['DB1_AUDIT_DUMP'], 'wt'), default=str)
"""
assert s.count(OLD) == 1, 'old anchor'
assert s.count(NEW) == 1, 'new anchor'
s = s.replace(OLD, OLD_DUMP + OLD).replace(NEW, NEW_DUMP + NEW)
open(p, 'w').write(s)
print('patched', p)
