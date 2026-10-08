import sys, re
pat = re.compile(sys.argv[1])
n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
w = int(sys.argv[3]) if len(sys.argv) > 3 else 300
txt = open('/Users/dhiren/.claude/projects/-Users-dhiren/ade10ab2-0f3c-4a7b-ac14-b166ccf4e19e.jsonl', encoding='utf-8', errors='replace').read()
hits = [m.start() for m in pat.finditer(txt)]
print(len(hits), 'hits')
for h in hits[-n:]:
    print('---', txt[max(0, h - w):h + w].replace('\\n', '\n'))
