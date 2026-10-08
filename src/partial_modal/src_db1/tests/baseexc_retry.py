"""baseexc_retry.py - how Modal treats stage.HostUnsuitable (a BaseException) raised out of a function (no data, no model).

Checks the plug-in path's retry contract: (1) Modal re-runs the input (retries=) on a new container
(single_use_containers=True) after the function raised a BaseException subclass, and (2) what the CALLER sees when every
attempt raised it: the app's orchestrate._call retries on `except Exception`, so the client-side error must be an
Exception (not a BaseException that would escape the app's loop).
  .venv/bin/modal run src_db1/tests/baseexc_retry.py
"""
import json, os

import modal

app = modal.App('pmp-src-db1-baseexc')
img = modal.Image.debian_slim(python_version='3.11')


class HostUnsuitable(BaseException):
    """same shape as stage.HostUnsuitable"""


@app.function(image=img, cpu=0.25, memory=256, single_use_containers=True,
              retries=modal.Retries(max_retries=2, backoff_coefficient=1.0, initial_delay=1.0))
def always_unsuitable(x: int):
    print('attempt in task', os.environ.get('MODAL_TASK_ID'), flush=True)
    raise HostUnsuitable('src_db1 host_unsuitable: test')


@app.function(image=img, cpu=0.25, memory=256, single_use_containers=True,
              retries=modal.Retries(max_retries=1, backoff_coefficient=1.0, initial_delay=1.0))
def unsuitable_container_only_class(x: int):
    """the class lives in a module the CALLER cannot import (as stage.py loaded by the app's plugins.load)"""
    print('attempt in task', os.environ.get('MODAL_TASK_ID'), flush=True)
    E = type('HostUnsuitable', (BaseException,), {'__module__': 'pmp_plugin_src_db1'})
    raise E('src_db1 host_unsuitable: test (container-only class)')


@app.function(image=img, cpu=0.25, memory=256, single_use_containers=True,
              retries=modal.Retries(max_retries=1, backoff_coefficient=1.0, initial_delay=1.0))
def unsuitable_exit(x: int):
    """hard exit of the container process"""
    print('attempt in task', os.environ.get('MODAL_TASK_ID'), flush=True)
    os._exit(75)


def _call(fn):
    try:
        fn.remote(1)
        return 'returned (unexpected)'
    except Exception as e:                      # what orchestrate._call catches
        return {'caught_as_Exception': True, 'type': f'{type(e).__module__}.{type(e).__name__}', 'msg': str(e)[:300]}
    except BaseException as e:                  # would escape orchestrate._call
        return {'caught_as_Exception': False, 'type': f'{type(e).__module__}.{type(e).__name__}', 'msg': str(e)[:300]}


@app.local_entrypoint()
def main(which: str = 'class,container_only,exit'):
    res = {}
    for w in which.split(','):
        res[w] = _call({'class': always_unsuitable, 'container_only': unsuitable_container_only_class,
                        'exit': unsuitable_exit}[w])
    print(json.dumps(res, indent=1))
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', 'baseexc_retry.json')
    json.dump(res, open(p, 'w'), indent=1)
