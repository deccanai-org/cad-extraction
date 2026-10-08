---
name: feedback-keep-context-repo-updated
description: Always keep the CAD CONTEXT.md (private repo) and the public status repo updated with stats and milestones after every meaningful step
metadata:
  type: feedback
---

Dhiren (2026-09-29): "always make sure we are updating this repo here fully with the stats what we are doing,
maintain a context md maybe and keep updating it with important milestones and context always."

Chosen layout (2026-09-29, after being told the status repo is PUBLIC):
- **Private** `dhigdec/cad-extract-context` (local `/Users/dhiren/Downloads/Deccan/cad-extract-context/`):
  full `CONTEXT.md` (state, stats, S3 map, profiles, decisions, open items) + dated `MILESTONES.md`.
- **Public** `dhigdec/cad-extract-status` (GitHub Pages, local `/Users/dhiren/Downloads/Deccan/cad-extract-status/`):
  anonymous numbers only + `MILESTONES.md` — no client/project names, no account ID, IAM roles, SSO URL or bucket paths.

**Why:** he wants one always-current place with the whole picture so any session (desktop or CLI) can pick up
without re-deriving; the public repo must never leak internal details.

**How to apply:** after any milestone (run finished/paused, numbers changed, decision made, deletion approved,
machines launched/terminated) update CONTEXT.md + MILESTONES.md, commit and push the private repo; push
sanitized stats to the public repo. Never write secret values (keys, tokens, DB passwords) into either —
see [[committed-secrets-risk]]. Numbers must come from verified S3 reads, see [[project_cad_packaged_dataset]]
and [[project-db1-step-conversion]].
