"""Apply the stand-in remap to the kit worker (z3conv/sds2/worker.py) and the grader (z3conv/grade/worker.py) by anchored
string replacement (the files are edited concurrently; this avoids line-number drift).
usage: python apply_standin_remap.py <sds2/worker.py> <grade/worker.py>   (edits in place; prints what changed)"""
import sys, re
HELPER = '''JOIST_DESIG = re.compile(r'^\\s*\\d+(?:\\.\\d+)?\\s*(KCS|K|LH|DLH|SLH)', re.I)


def member_standin(b, nm, mt):
    """pieces-csv row of kind 'member' (a member written without SDS2 pieces) -> (stand-in type, real type).
    Decided by the SECTION, not the member type: v4 reads 7.0/7.1 member types one slot off (BAHAMAR 7.135: joists
    labelled BEAM / COLUMN / MISC), and Revit-imported jobs type W-shape framing JOIST (bghjk 7.331: 1,303 rolled
    members labelled JOIST)."""
    if b in ('joist_openweb_catalog', 'joist_openweb_standin'):
        return 'joist_openweb_from_designation', 'joist ' + (nm or mt)
    if JOIST_DESIG.match(nm or ''):
        return 'joist_as_envelope_box', 'joist ' + nm
    if b == 'member_undetailed_profile' or (b == 'joist_envelope_approx' and nm):
        return 'member_undetailed_nominal_profile', f'{mt or "member"} {nm.split("x")[0] if nm else ""} without material in the job'.replace('  ', ' ')
    return 'member_as_envelope', f'{mt or "member"} without piece data'


'''
KIT_OLD = '''                if 'joist' in b:
                    standins[('joist_as_envelope_box', 'joist ' + (nm or mt))] += 1
                else:
                    standins[('member_as_envelope', f'{mt or "member"} without piece data')] += 1'''
KIT_NEW = '''                standins[member_standin(b, nm, mt)] += 1'''
GRADE_OLD = '''                st[('joist_as_envelope_box', 'joist ' + (nm or mt)) if 'joist' in b else ('member_as_envelope', f'{mt or "member"} without piece data')] += 1'''
GRADE_NEW = '''                st[member_standin(b, nm, mt)] += 1'''


def patch(path, anchor, old, new):
    s = open(path).read()
    if 'def member_standin(' in s:
        print(path, 'already patched'); return
    assert s.count(old) == 1, f'{path}: stand-in block not found exactly once'
    assert s.count(anchor) == 1, f'{path}: anchor not found'
    s = s.replace(anchor, HELPER + anchor, 1).replace(old, new, 1)
    open(path, 'w').write(s); print(path, 'patched')


if __name__ == '__main__':
    patch(sys.argv[1], 'def piece_inventory(pieces_csv, skipped_csv, s2):', KIT_OLD, KIT_NEW)
    patch(sys.argv[2], 'def piece_inventory_text(pieces_txt, skipped_txt, s2):', GRADE_OLD, GRADE_NEW)
