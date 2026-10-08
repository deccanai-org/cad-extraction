#!/usr/bin/env python3
"""Coordinator hook for automatic packaging (call once per coordinator round, after build_index wrote index.jsonl.gz).

    import coord_hook
    blk = coord_hook.round(write=True)        # -> dict for conv_status['packaging']

What one round does (pkg.pkg_delta):
  1. shipped set = rows of the current index that pass pkgcore.ship_decision (class 1; verified where a verifier merges)
  2. minus the packaging ledger (compacted from _state/packaging/ledger_parts/) -> 'package' jobs, one per affected project
     (create when the project does not exist yet, update otherwise); a shipped STEP whose step_key or ETag changed -> refresh
  3. models / placements that left the shipped set -> appended to _state/packaging/removals_pending.jsonl (never applied here)
  4. writes the jobs list (PKG_JOBS_KEY), the immutable index snapshot the jobs use, status.json, ledger.jsonl + ledger_index.json
Jobs whose project still has an open (unfinished) job are not re-emitted: the job id is stable for the same delta, so an open job
keeps its id; a project lock (_state/packaging/locks/) guarantees one writer per project anyway.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault('PKG_ALLOW_WRITE', '1')
import pkg


def round(write=True, adapter='zen3', policy=None):
    jobs, status = pkg.pkg_delta(adapter, policy=policy, write=write)
    return status


if __name__ == '__main__':
    import json
    print(json.dumps(round(write='--write' in sys.argv), indent=1))
