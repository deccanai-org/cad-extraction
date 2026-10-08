import sys, re
from db1dec import load
def db1_guidset(d):
    s = set(m.group().decode().upper() for m in re.finditer(rb'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}', d))
    return s
def ifc_tags(txt):
    tags = re.findall(rb"'ID([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})'", txt)
    fast = re.findall(rb"IFCMECHANICALFASTENER\('[^']*',[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,'ID([0-9A-Fa-f-]{36})'", txt)
    return set(t.decode().upper() for t in tags), set(t.decode().upper() for t in fast)
if __name__ == '__main__':
    d = load(sys.argv[1]); G = db1_guidset(d); txt = open(sys.argv[2], 'rb').read(); T, F = ifc_tags(txt)
    print('db1 guids', len(G), 'ifc tags', len(T), 'joined', len(T & G), 'fasteners', len(F), 'fast joined', len(F & G))
