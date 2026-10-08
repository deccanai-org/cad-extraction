import sys
p = sys.argv[1]; s = open(p).read()
old = '''    if slot == 2494 and ver == "7.245":
        fixed = dict(type=0x988, p1=0x112, p2=0x172, sec=0x1D8, roll=0x1DE, fw=8)
'''
add = open(sys.argv[2]).read().split(old, 1)[1].split('    if slot in (3204, 3404, 3600):', 1)[0]
assert s.count(old) == 1 and 'ver == "7.243"' not in s
open(p, 'w').write(s.replace(old, old + add)); print('patched', p)
