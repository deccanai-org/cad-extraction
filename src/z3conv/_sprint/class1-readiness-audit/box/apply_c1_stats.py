"""apply_c1_stats.py KIT_DIR : class1-readiness-audit bookkeeping fixes in db1step.py bolt_stats / bolt-group name tags (anchor-checked,
idempotent; applies on kit k, kit k + hole-tolerance-residue, and after apply_c1_patch.py). No geometry is changed.
  old path (6.87 / 7.01 / 7.24, convert_old):
    * 'nominal_head_nut_written' = bolts written WITH a shank and no head/nut table (holes-only bolts write no head / nut; build_index
      counted them as bolt_nominal_head_nut via bolts - standard_table_geometry)
    * slotted groups (slot x / y stored in fields 1 / 2 of the bolt string) are cut round: new name tag + 'slotted_bolts_cut_round'
      (code k cut them round silently: no tag, no standin -> a model could reach class 1 with round holes where Tekla cuts slots)
  v2 path (engines >= 7.5, _convert): bolt_stats gains the keys build_index reads (standard_table_geometry, nominal_head_nut_written,
    holes_nominal_clearance, washers, washers_nominal, washer_side_inferred, bolts_shifted_to_plies, bolts_axial_unknown,
    slotted_bolts_cut_round). Code k left them out, so build_index counted EVERY bolt as head/nut nominal and EVERY hole as nominal
    clearance (holes_nominal_clearance missing -> holes_cut) whatever the decoded tolerance / geometry source.
  v2 washer name tag uses db1bolts.washer_exact (code k: 'washer_t or ISO family', which called an ISO-family bolt with no ISO 7089 size exact)."""
import os, sys
K = sys.argv[1]
sp = os.path.join(K, 'db1step.py'); s = open(sp).read()
if 'c1audit-stats' in s:
    print('db1step.py stats already patched'); sys.exit(0)

HELPERS = """def _c1_name(prefix, tags, limit=120):
    # c1audit-stats: STEP PRODUCT names are cut at 120 characters (ifc2step6 step_str): the [approx: ...] marker must survive the cut
    # (code k: long family strings pushed it past 120 -> step_check approx_products missed it), and exact groups get no marker at all
    # (codes c-k wrote '[approx: ]' on every old-engine bolt group, exact or not)
    prefix = ' '.join(str(prefix or '').split())
    if not tags:
        return prefix[:limit]
    tag = '[approx: ' + '; '.join(tags) + ']'
    if len(tag) > limit - 10:
        tag = tag[:limit - 11] + ']'
    return (prefix[:max(0, limit - len(tag) - 1)].rstrip() + ' ' + tag).strip()


def _c1_slot(bb):
    # c1audit-stats: the bolt's group stores a slot length (old-engine string fields 1 / 2; htr kits carry bb['slot'])
    sl = bb.get('slot')
    if sl is None:
        p = (bb.get('_prof') or '').split('/')
        try:
            sl = (float(p[1]), float(p[2]))
        except (IndexError, ValueError):
            sl = (0.0, 0.0)
    return any(abs(float(x)) > 1e-9 for x in sl)


def _c1_v2_stats(bgroups, BG, holes_cut, holes_tol, db1bolts):
    # c1audit-stats: v2 bolt_stats in the keys build_index.classify_db1 reads
    BL2 = [bb for g in bgroups for bb in (BG.get(g['seq']) or [])]
    sl = {g['seq']: bool((g.get('slot_parts') or 0) and ((g.get('slot_x') or 0) > 0 or (g.get('slot_y') or 0) > 0)) for g in bgroups}
    W = lambda bb: (bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0)
    live = [bb for bb in BL2 if not bb.get('holes_only')]
    return dict(bolts=len(BL2), standard_table_geometry=sum(1 for bb in BL2 if bb.get('std')),
                nominal_head_nut_bolts=sum(1 for bb in BL2 if not bb.get('std')),
                nominal_head_nut_written=sum(1 for bb in live if not bb.get('std')),
                holes_nominal_clearance=holes_cut - holes_tol, holes_only_bolts=len(BL2) - len(live),
                washers=sum(W(bb) for bb in live), washers_nominal=sum(W(bb) for bb in live if not db1bolts.washer_exact(bb)),
                washer_side_inferred=sum(1 for bb in live if bb.get('wash_2')),
                bolts_shifted_to_plies=sum(1 for bb in live if bb.get('head_up') and not bb.get('axial_decoded')),
                bolts_axial_unknown=sum(1 for bb in live if not bb.get('head_up')),
                slotted_bolts_cut_round=sum(1 for bb in BL2 if sl.get(bb.get('pid'))),
                model_catalog_bolts=sum(1 for bb in BL2 if (bb.get('std') or {}).get('source') == 'model_catalog'))


"""

R = [
    # helpers before _convert
    ("def _convert(db1_path, out_ifc, cat, layout=None, variants=(), allow_full=True):\n",
     HELPERS + "def _convert(db1_path, out_ifc, cat, layout=None, variants=(), allow_full=True):\n"),
    # old path: carry the group string on each bolt (slot fields)
    ("""            if m.get('bolt') and not m.get('cut'):
                for b in db1bolts.bolts_of(m):
                    BL.append(b)""",
     """            if m.get('bolt') and not m.get('cut'):
                for b in db1bolts.bolts_of(m):
                    b.setdefault('_prof', m.get('prof'))      # c1audit-stats
                    BL.append(b)"""),
    # old path: name tag for slotted groups
    ("""                    if any(bb.get('wash_2') for bb in bl):
                        tags.append('washer 2 side inferred (flag digit 3)')""",
     """                    if any(bb.get('wash_2') for bb in bl):
                        tags.append('washer 2 side inferred (flag digit 3)')
                if any(_c1_slot(bb) for bb in bl):          # c1audit-stats: slot x / y stored, slotted plies not decoded -> cut round
                    tags.append('slotted holes cut as round holes (slotted parts not decoded)')"""),
    # old path: stats keys
    ("'nominal_head_nut_bolts': sum(1 for bb in BL if not bb.get('std')),",
     "'nominal_head_nut_bolts': sum(1 for bb in BL if not bb.get('std')),\n"
     "                            'nominal_head_nut_written': sum(1 for bb in BL if not bb.get('std') and not bb.get('holes_only')),   # c1audit-stats\n"
     "                            'slotted_bolts_cut_round': sum(1 for bb in BL if _c1_slot(bb)),\n"
     "                            'bolts_axial_unknown': sum(1 for bb in BL if not bb.get('holes_only') and not bb.get('axial_decoded') and not bb.get('shift')),"),
    # old path: bolt-group name through _c1_name
    ("""                e = out.bolt_group(f"{nm} [approx: {'; '.join(tags)}]".replace('  ', ' '), bl)""",
     """                e = out.bolt_group(_c1_name(nm, tags), bl)   # c1audit-stats"""),
    # v2 path: bolt-group name through _c1_name
    ("""        nm = f"{nm} [approx: {'; '.join(tags)}]" if tags else nm
        e = out.bolt_group(nm.replace('  ', ' '), bl)""",
     """        e = out.bolt_group(_c1_name(nm, tags), bl)   # c1audit-stats"""),
    # v2 path: washer name tag = washer_exact
    ("        if any(bb.get('wash_head') or bb.get('wash_nut') or bb.get('wash_2') for bb in bl) and not (sg and (sg.get('washer_t') or 'ISO' in sg.get('family', ''))):",
     "        if any(bb.get('wash_head') or bb.get('wash_nut') or bb.get('wash_2') for bb in bl) and not all(db1bolts.washer_exact(bb) for bb in bl):   # c1audit-stats"),
]
for old, new in R:
    assert s.count(old) == 1, f'anchor not unique / missing: {old[:80]!r}'
    s = s.replace(old, new)
# v2 path: after the st['bolt_stats'] = dict(...) statement (kit k: no grader keys; kit m: grader keys present, these override /
# complete them: holes-only bolts excluded from head/nut nominal, washer_exact-only washer rule, axial unknown, slotted, catalog)
import re
mm = list(re.finditer(r"\n( +)writer='db1bolts2 v2 \(7\.5x-[^']*'\)\n", s))
assert len(mm) == 1, 'v2 writer anchor'
ind = mm[0].group(1)
base = ' ' * 8
s = s[:mm[0].end()] + base + "st['bolt_stats'].update(_c1_v2_stats(bgroups, BG, holes_cut, holes_tol, db1bolts))   # c1audit-stats\n" + s[mm[0].end():]
open(sp, 'w').write(s)
print('db1step.py stats patched')
