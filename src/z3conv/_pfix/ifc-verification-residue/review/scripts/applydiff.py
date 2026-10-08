# applydiff.py FILE DIFF : apply a unified diff's hunks to FILE by exact context match (each old block must occur once)
import sys
path, dp = sys.argv[1], sys.argv[2]
s = open(path).read(); lines = open(dp).read().split('\n')
hunks = []; cur = None
for l in lines:
    if l.startswith('@@'):
        cur = ([], []); hunks.append(cur); continue
    if cur is None or l.startswith('--- ') or l.startswith('+++ '):
        continue
    if l.startswith('+'):
        cur[1].append(l[1:])
    elif l.startswith('-'):
        cur[0].append(l[1:])
    elif l.startswith(' ') or l == '':
        cur[0].append(l[1:]); cur[1].append(l[1:])
for old, new in hunks:
    while old and old[-1] == '' and new and new[-1] == '':
        old.pop(); new.pop()
    o = '\n'.join(old) + '\n'; n = '\n'.join(new) + '\n'
    assert s.count(o) == 1, ('context matches', s.count(o), o[:200])
    s = s.replace(o, n)
open(path, 'w').write(s); print('applied', len(hunks), 'hunks to', path)
