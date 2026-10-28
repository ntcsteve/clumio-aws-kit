#!/usr/bin/env bash
# Preview every IAM role, policy and permission the connection will create in your AWS account,
# BEFORE anything is created, and check whether the deploy role may create them. Uses setup's own
# settings (terraform.tfvars), variables and versions, so what you approve is what gets created.
#
#   ./preview.sh [--as <role ARN>]          (make preview runs it, with --as from DEPLOY_ROLE)
#
# Account and Region come from setup/terraform.tfvars; sign in to that account.
# --as checks another identity (such as the CI/CD deploy role) instead of your own.
# Runs `terraform plan` only, in a throwaway folder that is deleted afterwards, so there
# is nothing left to apply. Needs: an AWS sign-in (read-only is enough), terraform, python3.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SETUP="$(cd "$HERE/.." && pwd)"
IAM_MODULE="$(cd "$SETUP/../modules/connection/iam" && pwd)"
AS_ARN=""
OUT=""
FINISHED=0

fail() { echo "FAIL: $*" >&2; exit 1; }
usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
value() { [ $# -ge 2 ] && [ -n "$2" ] || fail "$1 needs a value (see --help)"; }   # works on macOS bash 3.2

while [ $# -gt 0 ]; do
  case "$1" in
    --as)      value "$@"; AS_ARN="$2"; shift 2 ;;
    -h|--help) usage ;;
    *)         fail "unknown option: $1 (see --help)" ;;
  esac
done

# --- Check inputs before touching anything -------------------------------------
for f in variables.tf versions.tf; do
  [ -f "$SETUP/$f" ] || fail "$SETUP/$f not found"
done
[ -f "$SETUP/terraform.tfvars" ] \
  || fail "$SETUP/terraform.tfvars not found. Create it: cp settings.example terraform.tfvars, in setup/"
# Clumio's template version is pinned once, in the IAM module, on the line after its source.
MODULE_VERSION="$(awk '/source *= *"clumio-code\/aws-template\/clumio"/ { getline; print }' "$IAM_MODULE/main.tf" \
  | sed -nE 's/^ *version *= *"([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p')"
[ -n "$MODULE_VERSION" ] || fail "no exact module version in $IAM_MODULE/main.tf (expected version = \"x.y.z\" under the aws-template source)"
# A backend here would make the preview plan against real state and drop replacements silently.
! grep -q 'backend *"' "$SETUP/versions.tf" || fail "$SETUP/versions.tf has a backend block: move it to backend.tf"
command -v terraform > /dev/null || fail "terraform not found"
command -v python3 > /dev/null   || fail "python3 not found"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" \
  || fail "not signed in to AWS (read-only is enough)"

WORK="$(mktemp -d)"
# The config never outlives the run; a pack that didn't finish is removed, never left half-written.
trap 'rm -rf "$WORK"; [ "$FINISHED" = 1 ] || [ -z "$OUT" ] || rm -rf "$OUT"' EXIT

# --- A throwaway config: the connection's IAM module with setup's settings --------
# Same versions.tf, variables.tf (and its checks) and terraform.tfvars as setup. Values Clumio
# issues at connect time get stand-ins (they must match extract.py), so every document renders.
# The Clumio provider can never reach Clumio.
cp "$SETUP/versions.tf" "$SETUP/variables.tf" "$SETUP/terraform.tfvars" "$WORK/"
[ ! -f "$SETUP/.terraform.lock.hcl" ] || cp "$SETUP/.terraform.lock.hcl" "$WORK/"   # same provider builds as setup
cat > "$WORK/main.tf" <<EOF
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
}
provider "clumio" {
  clumio_api_token    = "preview-only"
  clumio_api_base_url = "https://preview.invalid"
}
# The same IAM module the connection calls, so what security approves is what gets created.
module "clumio_iam" {
  source = "$IAM_MODULE"
  connection = {
    token                 = "PREVIEWCLUMIOTOKEN"
    role_external_id      = "PREVIEWEXTERNALID"
    account_native_id     = var.account_id
    aws_region            = var.region
    clumio_aws_account_id = "111111111111"
    data_plane_account_id = "222222222222"
  }
  iam_prefix               = var.iam_prefix
  iam_path                 = var.iam_path
  workloads                = var.workloads
  role_tags                = var.role_tags
  permissions_boundary_arn = var.permissions_boundary_arn
  pass_role_deny_list      = var.pass_role_deny_list
}
EOF

echo "Previewing Clumio's IAM with the settings in $SETUP/terraform.tfvars (module $MODULE_VERSION)..."
( cd "$WORK" && terraform init -input=false -no-color > init.log 2>&1 ) || { cat "$WORK/init.log"; fail "terraform init"; }
( cd "$WORK" && terraform plan -input=false -no-color -out=plan.bin > plan.log 2>&1 ) \
  || { cat "$WORK/plan.log"; fail "terraform plan: see the error above (\"account ID not allowed\": sign in to account_id)"; }
( cd "$WORK" && terraform show -json plan.bin > plan.json )
REGION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["variables"]["region"]["value"])' "$WORK/plan.json")"
OUT="$(pwd)/clumio-iam-preview-$REGION-$(date -u +%Y%m%dT%H%M%SZ)"

# --- Plan -> review pack, then make sure nothing sensitive is in it -------------
mkdir -p "$OUT/policies"
python3 "$HERE/extract.py" "$WORK/plan.json" "$OUT" "$ACCOUNT" "$REGION" "$WORK"

# --- Can the deploy role do all of it? Ask the IAM policy simulator. -----
# It evaluates the identity's policies, permissions boundaries and SCPs (not resource control
# policies), with the request's Region, tags and boundary as context. It needs
# iam:SimulatePrincipalPolicy. One named result: READY, BLOCKED, CANNOT CHECK.
check_identity() {
  local caller principal denied="" actions arn context results
  caller="$(aws sts get-caller-identity --query Arn --output text)"
  if [ -n "$AS_ARN" ]; then
    principal="$AS_ARN"
  elif [[ "$caller" == *":root" ]]; then
    echo "CANNOT CHECK: you are the account root user, which can do all of it (the simulator can't test root). Run: make preview DEPLOY_ROLE=<deploy role ARN>"; return
  elif [[ "$caller" == *":assumed-role/"* ]]; then   # SSO or assumed role: the simulator needs the role's IAM ARN
    local role_name="${caller#*:assumed-role/}"; role_name="${role_name%%/*}"
    principal="$(aws iam get-role --role-name "$role_name" --query Role.Arn --output text 2>/dev/null)" \
      || { echo "CANNOT CHECK: can't read your role ($role_name) with iam:GetRole. Ask security to run: make preview DEPLOY_ROLE=<deploy role ARN>"; return; }
  else
    principal="$caller"
  fi
  local line
  while IFS= read -r line; do
    # Unmask the whole line: the ARN and its context (iam:PolicyARN) must name the real account.
    line="${line//<ACCOUNT_ID>/$ACCOUNT}"; line="${line//<CLUMIO_TOKEN>/PREVIEWCLUMIOTOKEN}"
    IFS=$'\t' read -r actions arn context <<< "$line"
    # shellcheck disable=SC2086  # actions is a space-separated list on purpose
    results="$(aws iam simulate-principal-policy --policy-source-arn "$principal" --action-names $actions \
      --resource-arns "$arn" --context-entries "$context" \
      --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output text 2>&1)" \
      || { echo "CANNOT CHECK: the IAM simulator refused (${results##*: }). It needs iam:SimulatePrincipalPolicy on $principal."; return; }
    denied+="$(awk -v r="$arn" '$2 != "allowed" { printf "  %-14s %-34s %s\n", $2, $1, r }' <<< "$results")"$'\n'
  done < "$WORK/deploy-check.tsv"
  denied="$(grep -v '^$' <<< "$denied" || true)"
  if [ -z "$denied" ]; then
    echo "READY: $principal may do every action above."
  else
    echo "BLOCKED: $principal is missing these (implicitDeny: not granted; explicitDeny: denied by a policy or SCP):"
    echo "$denied"
    echo "Fix: in policies/deploy-role-policy.json replace <ACCOUNT_ID> with your account ID, grant it, then run this again."
  fi
}
echo
echo "Can the deploy role do it?"
CHECK="$(check_identity)"; CHECK="${CHECK//$ACCOUNT/<ACCOUNT_ID>}"   # ARNs and AWS error text carry the account ID
echo "$CHECK" | sed 's/^/  /'
printf '\n## Can the deploy role do it?\n\n```\n%s\n```\n' "$CHECK" >> "$OUT/summary.md"

grep -rq "$ACCOUNT" "$OUT" && fail "account ID found unmasked in the output; nothing written"
FINISHED=1
echo
echo "Next: give this folder to your security team (account ID masked):"
echo "  $OUT/summary.md      the full picture, same headings as above"
echo "  $OUT/policies/       every policy as JSON, ready to review or create"
