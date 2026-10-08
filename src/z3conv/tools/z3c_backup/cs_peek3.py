import json
d = json.load(open('/tmp/z3c/conv_status.json'))
u = d['utilization']
tm = ta = tr = 0
print(f"{'host':28} {'pipe':5} cpu load  ifc sds2 pk  memT  avail resv  okC okM capC rc")
for b in u['boxes']:
    g = b.get('gate') or {}
    j = b.get('jobs') or {}
    tm += b.get('mem_total_gb') or 0; ta += b.get('mem_avail_gb') or 0; tr += b.get('reserved_gb') or 0
    print(f"{b['host'][:28]:28} {b['pipeline'][:5]:5} {b['cpus']:3} {b['load']:5.1f} {j.get('ifc',0):3} {j.get('sds2',0):4} {j.get('package',0):2} "
          f"{b.get('mem_total_gb'):5} {b.get('mem_avail_gb'):5} {b.get('reserved_gb'):6} {str(g.get('ok_cpu'))[0]:3} {str(g.get('ok_mem'))[0]:3} "
          f"{g.get('cap_cpu')} {g.get('recent_cores')}  {sorted(set(b) - {'host','pipeline','cpus','load','jobs','worker_processes','mem_total_gb','mem_avail_gb','reserved_gb','gate'})}")
print('total mem', tm, 'avail', ta, 'reserved', round(tr))
print('sds2_per_job', json.dumps(d.get('sds2_per_job'), default=str)[:1500])
