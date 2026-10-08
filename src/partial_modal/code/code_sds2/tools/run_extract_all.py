import json, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concurrent.futures import ProcessPoolExecutor
import extract, exact
M = json.load(open('models.json'))
def one(m):
    out = 'out/' + m['stem']
    info = extract.extract(m['ifc_local'], out)
    exact.main(out, m['step_local'])
    return m['stem'], info
if __name__ == '__main__':
    with ProcessPoolExecutor(8) as ex:
        R = list(ex.map(one, M))
    tot = collections.Counter()
    for stem, info in R:
        print(stem[:55].ljust(55), info['parts'], info['status'])
        for k, v in info['status'].items(): tot[k] += v
    print('TOTAL', dict(tot))
