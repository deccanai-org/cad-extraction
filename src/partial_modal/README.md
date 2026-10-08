# partial_modal — pmp: partial-tier completion pipeline on Modal

Full description: `docs/README.md`. Entry points: `app/modal_app.py` (Modal app), `jobs/make_jobs.py` + `jobs/presign.py`
(inputs via pre-signed URLs; no AWS keys on Modal), `publish/box.py` (publish bundles into `3d_partial/<pid>/scripts/`),
`complete/` (db1 / sds2_ifc / standards completion tracks), `overlay/` (colour-coded issue models), `status/` (public page).
Scope: 5-sample tests; scaling needs the owner's cost approval.
