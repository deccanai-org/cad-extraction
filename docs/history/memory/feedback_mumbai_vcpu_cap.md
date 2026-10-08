---
name: feedback-mumbai-vcpu-cap
description: "CAD fleet may use at most 700 vCPU in Mumbai (ap-south-1) — team cap, NOT the 2,000 service quota; Hyderabad has its own 320 quota"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e018bae4-0ec8-4915-b8e9-61ca8ae96814
  modified: 2026-09-24T21:55:43.023Z
---

Never exceed **700 vCPU of CAD instances in ap-south-1 (Mumbai)**. The EC2 service quota
reads 2,000 — that is NOT the limit; the 700 cap is a team rule Dhiren reminded me of on
2026-09-24 after I planned a 5 x r7i.24xlarge (480 vCPU) add-on that would have breached it.

**Why:** shared account; other teams' instances run in Mumbai and the cap was agreed for the CAD work.

**How to apply:** before every launch, sum vCPU of running `Project=cad` / `cad-*` instances in
ap-south-1 (include the Windows box and any RE/validation box) and keep the total <= 700.
Put overflow capacity in **ap-south-2 (Hyderabad)**: quota 320 vCPU, ~18 already used by
hyd-medium + hyd-status. S3 bucket is in Mumbai, so cross-region transfer is billed —
prefer Hyderabad for CPU-heavy / small-output work (DB1 decode), Mumbai for big-output work.
Related: [[reference_cad_iam_gaps]] (launch permission now granted, Project=cad tag required).
