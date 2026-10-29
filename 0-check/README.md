# Step 0: Check

Two read-only checks, before anything exists. Nothing is created.

## Before you begin

You need:

1. Terraform 1.10 or later, the AWS CLI v2, and Python 3.9 or later. macOS's own Python works. On Windows, use WSL.
2. An AWS sign-in to the account you're connecting, such as `aws sso login --profile <name>`, then `export AWS_PROFILE=<name>` in the same shell, so every step uses it.
3. A Clumio API token, from the Clumio console under Administration, Access management, API tokens.

Put your Clumio details in your shell, so the token never lands in a file:

```bash
export CLUMIO_API_BASE_URL=https://us-west-2.api.clumio.com   # your portal's API URL, from the table below
read -rs CLUMIO_API_TOKEN && export CLUMIO_API_TOKEN          # paste the token, then press Enter; nothing shows
```

Your API URL depends on the Clumio portal you sign in to ([source](https://registry.terraform.io/providers/clumio-code/clumio/latest/docs)):

| Clumio portal | `CLUMIO_API_BASE_URL` |
|---|---|
| portal.clumio.com, west.portal.clumio.com | `https://us-west-2.api.clumio.com` |
| east.portal.clumio.com | `https://us-east-1.api.clumio.com` |
| canada.portal.clumio.com | `https://ca-central-1.ca.api.clumio.com` |
| eu1.portal.clumio.com | `https://eu-central-1.de.api.clumio.com` |
| au.portal.clumio.com | `https://ap-southeast-2.au.api.clumio.com` |
| jp.portal.clumio.com | Ask your Clumio administrator |

Steps 0 and 3 run from the repository's root folder, in this same shell. Keep the same token and API URL throughout: a token from another Clumio tenant can't see what an earlier step created.

Then make step 1's settings file. Preflight and the preview read it, so what you check is what you create:

```bash
cp 1-connect/settings.example 1-connect/terraform.tfvars
```

In `1-connect/terraform.tfvars`, set `account_id`, `region`, `organizational_unit`, `mode` and `workloads`.

## 1. Preflight

```bash
tools/status.py --preflight
```

It checks your tools, settings, AWS sign-in, Clumio token, organizational unit, Region, free rule slots, and whether the account is already connected. Each line says PASS, NOTE (read it before you go on), FAIL (it says what to fix) or SKIP (waits on an earlier FAIL). With `organizational_unit` unset, it lists the units you can choose.

## 2. Preview Clumio's IAM

```bash
0-check/preview/preview.sh
```

It shows every IAM role, policy and permission Clumio will create in your account, and checks whether your sign-in may create them. It writes a review pack, `clumio-iam-preview-<region>-<time>/`, in the folder you run it from: give it to your security team.

It ends with one of three results:

- **READY**: your sign-in may create all of it.
- **BLOCKED**: it lists each missing permission. Grant them, then run it again.
- **CANNOT CHECK**: it can't test your sign-in. Either you're the account's root user, which the IAM simulator can't test, or your role may not read itself (`iam:GetRole`) or use the simulator (`iam:SimulatePrincipalPolicy`). Have someone who can, such as your security team, run it for the identity that will deploy: `0-check/preview/preview.sh --as <its role ARN>`.

If a CI/CD role deploys for you, check that role the same way, with `--as`.

Proven live on 2026-10-29: an IAM user holding only the generated deploy policy planned, applied and destroyed `1-connect` (S3, RDS) and `2-protect-s3`, with no access errors.

## Next

[Step 1: connect](../1-connect/README.md).
