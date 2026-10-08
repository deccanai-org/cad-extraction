"""Score one candidate IFC against a STEP (separate process: IFC memory is released when it exits).
usage: python -m ifcstepverify.score_worker <ifc> <step_keys.json> <out.json>"""
import sys, json, collections
import ifcopenshell
from .ifcmodel import physical, step_name, guid_uuid


def score(ifc, names, uuids):
    f = ifcopenshell.open(ifc)
    els = physical(f)
    c = dict(schema=f.schema, physical_elements=len(els), types=dict(sorted(collections.Counter(e.is_a() for e in els).items())))
    if uuids:
        gid = {guid_uuid(e) for e in els}; hit = uuids & gid
        c.update(match_key="GlobalId", overlap=round(len(hit) / max(1, max(len(uuids), len(gid))), 6), precision=round(len(hit) / max(1, len(uuids)), 6),
                 missing_in_step=len(gid - uuids), extra_in_step=len(uuids - gid), keys=sorted(hit))
    else:
        byname = collections.Counter(step_name(e) for e in els)
        bytag = collections.Counter((getattr(e, "Tag", None) or "") for e in els)
        tot = sum(names.values())
        ov = lambda C_: sum(min(C_[k], names[k]) for k in names) / max(1, max(tot, sum(C_.values())))
        a, b = ov(byname), ov(bytag)
        use = byname if a >= b else bytag
        c.update(match_key="Name" if a >= b else "Tag", overlap=round(max(a, b), 6),
                 precision=round(sum(min(use[k], names[k]) for k in names) / max(1, tot), 6),
                 missing_in_step=sum(max(0, use[k] - names.get(k, 0)) for k in use),
                 extra_in_step=sum(max(0, names[k] - use.get(k, 0)) for k in names), keys=dict(sorted(use.items())))
    return c


if __name__ == "__main__":
    ifc, kp, outp = sys.argv[1:4]
    K = json.load(open(kp, encoding="utf-8"))
    try:
        res = score(ifc, collections.Counter(K["names"]), set(K["uuids"]))
    except Exception as e:
        res = dict(error=f"{type(e).__name__}: {e}"[:300])
    json.dump(res, open(outp, "w", encoding="utf-8"))
