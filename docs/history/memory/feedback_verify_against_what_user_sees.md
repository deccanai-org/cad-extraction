---
name: feedback_verify_against_what_user_sees
description: "Before reporting a defect in Dhiren's system, confirm it against the artifact he actually sees — not the first API endpoint that looks authoritative"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1ccfd16c-63a4-4d05-b182-566a82de899a
---

When auditing one of Dhiren's systems, **verify a defect against the surface he
actually looks at before reporting it.** Reproduce it the way he would.

**Why:** On 2026-07-19 I audited the Deccan wiki mirror and reported systemic
content loss — 53.8% section retention, "~59,000 words missing", "the site's
'verified complete' claim is wrong." All of it was wrong. I had been measuring
`/pages/{id}` (a lossy derived JSON extraction) while the site renders
`/pages/{id}/html` (complete). Correct answer: 99.81% coverage, zero scraper
defects. Six corrections in one session; five were mine catching my own
measurement bugs, but the decisive one was Dhiren opening his own site and
Ctrl-F'ing text my report called absent. He then had to catch a *second*
instance of the same class before I stopped patching heuristics and fixed the
root cause. His words: "i dont want such errors to be there."

**How to apply:**
- When multiple endpoints/tables/artifacts could be "the data", establish which
  one the product actually serves BEFORE measuring. Ask if unclear.
- Reproduce any claimed defect through the user-facing surface before reporting
  it. One Ctrl-F beats a thousand-page scan built on the wrong input.
- Repeated false positives of the same shape mean the comparison target is
  wrong. Stop adding special cases; re-point the comparison.
- Measurement bugs are not symmetric — every one of mine inflated apparent
  damage. Treat an alarming result as a prompt to re-verify the instrument, and
  state uncertainty before he has to correct me, not after.
- Related: [[project_deccan_wiki_mirror_qa]].
