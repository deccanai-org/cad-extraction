#!/usr/bin/env python3
"""jobq.py TASKS.json --s3 PREFIX [--threads 20] [--mem-gb 150] [--tag NAME]
Runs shell tasks on an agent box under a thread / memory budget. Each task: {name, cmd, threads, mem_gb, deps[], after[], outputs[]}
(deps must succeed; after only orders: it waits until those tasks ended in any state).
Per task: wall / user+sys CPU / max RSS of the largest process in its tree (os.wait4), rc; its declared outputs (paths relative to
the cwd, files or directories) and its log are uploaded to PREFIX/<path> when it ends; status_<tag>.json (all tasks + box load)
is uploaded every 60 s and at the end. A task whose dependency failed is skipped."""
import sys, os, json, time, subprocess, argparse, shlex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tasks'); ap.add_argument('--s3', required=True)
    ap.add_argument('--threads', type=int, default=20); ap.add_argument('--mem-gb', type=float, default=150.0)
    ap.add_argument('--tag', default='jobs')
    a = ap.parse_args()
    tasks = json.load(open(a.tasks))
    os.makedirs('logs', exist_ok=True)
    st = {t['name']: {'state': 'queued', 'threads': t.get('threads', 1), 'mem_gb': t.get('mem_gb', 2)} for t in tasks}
    order = [t['name'] for t in tasks]
    T = {t['name']: t for t in tasks}
    running = {}
    t_start = time.time()
    last_hb = 0

    def up(path, key=None):
        if not os.path.exists(path):
            return
        key = key or path
        cmd = ['aws', 's3', 'cp', '--only-show-errors'] + (['--recursive'] if os.path.isdir(path) else []) + [path, f'{a.s3}/{key}']
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def box():
        try:
            la = open('/proc/loadavg').read().split()[:3]
            mi = {l.split(':')[0]: int(l.split()[1]) for l in open('/proc/meminfo') if l.split(':')[0] in ('MemTotal', 'MemAvailable')}
            return {'load': la, 'mem_avail_gb': round(mi['MemAvailable'] / 2**20, 1), 'mem_total_gb': round(mi['MemTotal'] / 2**20, 1)}
        except Exception:
            return {}

    def heartbeat(final=False):
        doc = {'tag': a.tag, 'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'elapsed_sec': round(time.time() - t_start),
               'final': final, 'box': box(), 'tasks': {n: st[n] for n in order}}
        p = f'status_{a.tag}.json'
        json.dump(doc, open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p)
        up(p)

    while True:
        # launch in list order while the budget allows
        used_t = sum(st[n]['threads'] for n, _ in running.values()); used_m = sum(st[n]['mem_gb'] for n, _ in running.values())
        blocked = False                                   # FIFO for heavy tasks: a later heavy task never overtakes a waiting one
        for n in order:
            s = st[n]
            if s['state'] != 'queued':
                continue
            deps = T[n].get('deps') or []
            if any(st[d]['state'] in ('failed', 'skipped') for d in deps):
                s['state'] = 'skipped'; s['why'] = 'dependency failed'; continue
            if not all(st[d]['state'] == 'done' for d in deps):
                continue
            if not all(st[d]['state'] in ('done', 'failed', 'skipped') for d in T[n].get('after') or []):
                continue                                  # 'after': ordering only (finished in any state), no failure cascade
            light = s['threads'] <= 1 and s['mem_gb'] <= 8
            if blocked and not light:
                continue
            if running and (used_t + s['threads'] > a.threads or used_m + s['mem_gb'] > a.mem_gb):
                blocked = blocked or not light
                continue
            lf = open(f'logs/{n}.log', 'w')
            p = subprocess.Popen(['bash', '-c', T[n]['cmd']], stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
            lf.close()
            running[p.pid] = (n, p)                       # keep the Popen alive: its __del__ must not queue it for reaping
            s.update(state='running', pid=p.pid, started=time.strftime('%H:%M:%SZ', time.gmtime()), t0=time.time())
            used_t += s['threads']; used_m += s['mem_gb']
        if not running and not any(st[n]['state'] == 'queued' for n in order):
            break
        # reap
        try:
            pid, status, ru = os.wait4(-1, os.WNOHANG)
        except ChildProcessError:
            pid = 0
        if pid and pid in running:
            n, po = running.pop(pid); s = st[n]
            rc = os.waitstatus_to_exitcode(status)
            po.returncode = rc                            # reaped here, not by subprocess
            s.update(state='done' if rc == 0 else 'failed', rc=rc, wall_sec=round(time.time() - s.pop('t0'), 1),
                     cpu_sec=round(ru.ru_utime + ru.ru_stime, 1), max_rss_mb=round(ru.ru_maxrss / 1024))
            json.dump(s, open(f'logs/{n}.rusage.json', 'w'))
            for o in T[n].get('outputs') or []:
                up(o)
            up(f'logs/{n}.log'); up(f'logs/{n}.rusage.json')
            heartbeat()
            continue
        if time.time() - last_hb > 60:
            last_hb = time.time(); heartbeat()
        time.sleep(1.0)
    heartbeat(final=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
