"""chart_report.py REPORT_CMP_TXT OUT.png : per model, |decoded parts - Tekla part list| in the profile buckets the patch changes, before / after"""
import sys, re
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
rows = []
for l in open(sys.argv[1]):
    m = re.match(r'^(\w{16}) report .*changed buckets \d+: \|model-report\| (\d+) -> (\d+)', l)
    if m: rows.append((m.group(1)[:8], int(m.group(2)), int(m.group(3))))
rows.sort(key=lambda r: -r[1])
fig, ax = plt.subplots(figsize=(11, 4.6), facecolor='#fcfcfb'); ax.set_facecolor('#fcfcfb')
x = range(len(rows)); w = 0.4
ax.bar([i - w / 2 for i in x], [r[1] for r in rows], w - 0.04, color='#eb6834', label='deployed kit')
ax.bar([i + w / 2 for i in x], [r[2] for r in rows], w - 0.04, color='#2a78d6', label='cut-not-applied patch')
ax.set_xticks(list(x)); ax.set_xticklabels([r[0] for r in rows], rotation=70, fontsize=7, color='#52514e')
ax.set_ylabel('parts off the Tekla part list', color='#52514e'); ax.tick_params(axis='y', colors='#52514e')
for s in ('top', 'right'): ax.spines[s].set_visible(False)
for s in ('left', 'bottom'): ax.spines[s].set_color('#c9c8c2')
ax.grid(axis='y', color='#e6e5e0', linewidth=0.8); ax.set_axisbelow(True)
tb, ta = sum(r[1] for r in rows), sum(r[2] for r in rows)
ax.set_title(f'{len(rows)} DB1 models with a Tekla part list in the model folder: |decoded - report| part count in the profiles the patch changes ({tb} -> {ta})',
             fontsize=10, color='#0b0b0b', loc='left')
ax.legend(frameon=False, fontsize=9, labelcolor='#0b0b0b')
fig.tight_layout(); fig.savefig(sys.argv[2], dpi=120, facecolor='#fcfcfb'); print('wrote', sys.argv[2], len(rows), tb, ta)
