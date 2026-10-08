---
name: feedback-agent-shared-control-writes
description: Subagents/fixers must never write shared fleet kit/control files; a swapped `aws s3 cp - s3://key` emptied sds2/pybin.txt (2026-10-02)
metadata:
  type: feedback
---

On 2026-10-02 01:14Z a workflow fixer meant to read `_control/z3conv/sds2/pybin.txt` but wrote `aws s3 cp - s3://…/pybin.txt`.
That replaced the file with an empty object, so every SDS2 worker that started or reloaded in the next 3 minutes got PYBIN=$W/ and
could not launch. It was restored from the previous S3 version (bucket versioned) at 01:17Z with the owner's OK. The owner said:
"make sure it never happens again".

**Why:** the fleet reads small shared _control files (pybin.txt, env.json, rules.json, priority.json, kit dirs) at every start or
reload, so a single bad write takes down a whole pipeline.

**How to apply:**
- Every agent brief that touches S3 must say: write only under your own prefix (agentjobs/<slug>, pfix/<slug>, fixes/<slug>,
  agentwork/<slug>). Releases go through the builder only.
- Reads are `aws s3 cp s3://… -` or `s3api get-object`, never `- s3://…`.
- Fleet code must survive bad control files: validate each value, keep the last good copy, don't let an empty download replace a
  non-empty file, and have the coordinator self-heal from S3 versions.
- If an agent's own write or restore is blocked, ask the owner before doing it for the agent; don't do it on the agent's behalf.

Related: [[feedback-fleet-worker-lessons]].
