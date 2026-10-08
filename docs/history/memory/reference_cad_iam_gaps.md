---
name: reference_cad_iam_gaps
description: What the annotationprod SSO role can and cannot do on the CAD fleet
metadata:
  type: reference
---

Role `AWSReservedSSO_annotationprod-s3-access` (profile `annotationprod-publish`).

**UPDATE 2026-10-06: RunInstances WORKS when the launch tags `Project=cad`** (exact value; `Project=cad-disk-extract`
is denied). Proven pattern: `/tmp/z3c/launch_pm_v4.sh` / `cad-db1-convert/src/launch_fleet.sh` - AMI ami-0ee11497c4eac651d,
subnet-0eeba63763d7eb0da, sg-088de8e930b87b429, profile cad-disk-extract-ec2, shutdown=terminate. Dry-run first.
I wrongly told Dhiren launches were blocked because I used the wrong tag - always dry-run with Project=cad.

**Previously denied (before the policy change):** `ec2:RunInstances`, `ec2:CreateTags`, `iam:PassRole`, `ssm:GetParameter`,
`pricing:GetProducts`, `s3:GetBucketCORS`. Verified in BOTH ap-south-1 and ap-south-2,
and the EC2 instance role `cad-disk-extract-ec2` is denied RunInstances too.
Note AWS validates the AMI *before* authorization — a bad AMI returns
`InvalidAMIID.NotFound` and masks the real denial. Test with a valid regional AMI.

**Allowed:** Describe*, Start/Stop/TerminateInstances, ssm:SendCommand, S3 on
`cad-disk-extract/*` only (a new top-level prefix like `cad-packaged/` is denied —
that is why the packaged tree lives under `cad-disk-extract/dataset/`).

The asymmetry matters: the role can **destroy** capacity but not **create** it, so once
the fleet was terminated it could not be rebuilt. Minimal policy to fix drafted at
`~/Downloads/cad-launch-policy.json` (RunInstances + CreateTags-at-launch +
PassRole scoped to `cad-disk-extract-ec2`).

Second identity: IAM user `dhiren@deccan.ai` (profile `bim`, static keys, read-only
Get/List). Reaches `bim-census-work-874846752452` (the lead's projpkg4 bucket) which the
SSO role cannot, and can read `annotationprod` — useful for monitoring when SSO expires,
but no SSM. See [[project_cad_packaged_dataset]].
