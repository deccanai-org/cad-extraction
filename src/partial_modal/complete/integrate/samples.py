"""the 5 new samples: tag -> model id / folder / baseline tree (local copy of the baseline run's scripts tree)"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # partial_modal
COMPLETE = os.path.join(ROOT, 'complete')
SHORT = {'n1_db1_small': 'n1', 'n2_db1_addon': 'n2', 'n3_ifc_approx': 'n3', 'n4_ifc_c2s': 'n4', 'n5_sds2': 'n5'}


def jobs():
    out = {}
    for ln in open(os.path.join(ROOT, 'jobs', 'new5.jsonl')):
        if ln.strip():
            r = json.loads(ln)
            out[r['tag']] = r
    return out


def baseline_tree(tag, root=None):
    """the baseline scripts/<model_folder>/ tree: a track-supplied tree (n3) wins over the baseline run's copy"""
    j = jobs().get(tag)
    if not j:
        return None
    for tr in ('db1', 'sds2_ifc', 'standards', 'estimate', 'integrate'):
        t = os.path.join(root or COMPLETE, tr, 'out', tag, 'scripts_tree', j['model_folder'])
        if os.path.exists(os.path.join(t, 'schedules', 'parts.csv')):
            return t
    t = os.path.join(ROOT, 'testB_results', SHORT[tag], 'scripts', j['model_folder'])
    return t if os.path.isdir(t) else None
