# Secrets and personal-data scan

Scan run 2026-10-08 over every file in the repo (7.7k files; `.git` excluded). No values are reproduced here.

## Patterns checked
- AWS access keys `AKIA…` / `ASIA…`, `aws_secret_access_key`, `aws_session_token =` assignments
- `-----BEGIN … PRIVATE KEY`, `*.pem`, `*.key`, `id_*`, `.env*`, `.awsenv`, `credentials*`, `*.p12`
- GitHub tokens `gho_/ghp_/ghs_/ghu_`, Slack `xox?-`, OpenRouter `sk-or-v1`, Anthropic `sk-ant-`, Google `AIza…` / `ya29.`
- `password= / token= / secret= / api_key=` literal assignments of ≥ 16 chars; high-entropy strings within 30 chars of
  secret/key/token; DB connection strings with embedded credentials; pre-signed URL signatures (`X-Amz-Signature`)
- Personal data: payslip / passport / Aadhaar / CV keywords; e-mail addresses and phone numbers

## Result
**0 credential values found.** Remaining pattern hits are code that *handles* credentials without containing them:
`src/partial_modal/src_db1/build_kits.py` (a secret-detection regex), `src/partial_modal/publish/presign_put.py`
(passes role credentials from the instance metadata to boto3), `src/zen2/*` SQL Server scripts (read the SA password
from a root-only file on the box at runtime). No personal documents are included; e-mail addresses present are the
owner's work address and a ransomware marker string used for detection in `zx_worker.py`.

## Excluded / redacted while assembling the repo
- Never copied: `~/.aws/*`, SSO caches, `~/.ssh/*` (incl. the status-site deploy key), `~/.modal.toml`,
  `~/.config/cad-pii` (LLM key), `cad-db1-convert/.awsenv`, `.env` files, any `*.pem`.
- Zenitude-data-2 SharedContent `SSP3D1.ini` (DB login) and `*.cci` (licence connection): not copied; only mentioned by name.
- Memory notes about unrelated projects and all `reference_*_db.md` (database credentials): not copied.
- `docs/history/HANDOFF_CAD_STEP.md`: SSO start-URL instance id redacted (`ssoins-REDACTED`).
- Data: no extracted files, models, STEP/IFC/DB1, archives, report sample assets, project lists or files > 2 MB; only
  small summary JSONs in `docs/evidence/`.
- Venvs, caches and test outputs were not copied.

## How to re-run
```bash
grep -rnIE 'AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key|-----BEGIN|gh[opsu]_[A-Za-z0-9]{30}|xox[abpr]-|sk-or-v1|sk-ant-|AIza[0-9A-Za-z_-]{30}' --exclude-dir=.git .
find . -size +2M -not -path './.git/*'
```
