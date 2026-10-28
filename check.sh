#!/usr/bin/env bash
# Checks this repository before every commit. Offline: it never calls AWS or Clumio.
# It reads only what git would ship (tracked files, and new files that .gitignore doesn't exclude),
# so your own terraform.tfvars, state and .terraform/ never fail it, and never leave your machine.
# Runs on macOS's stock bash 3.2. Needs git and python3; Terraform 1.10+ once the repo holds .tf files.
#   1. shell scripts         every *.sh parses
#   2. terraform fmt         every .tf is formatted
#   3. no state or plans     by name, and by content (a renamed state file still holds "lineage")
#   4. no credentials        AWS access keys, unredacted session tokens or secret keys, a Clumio token
#   5. no account numbers    any 12-digit number outside the stand-ins below
#   6. relative links        every relative link in a Markdown file points at a file that ships
#   7. self-test             tests/check_test.sh proves each check passes and fails when it should
#                            (skipped with CHECK_SELFTEST=off, which those tests set, so this never loops)
set -euo pipefail

cd "$(dirname "$0")"
FAILED=0
pass() { printf 'PASS  %s\n' "$1"; }
flunk() { printf 'FAIL  %s\n' "$1"; FAILED=1; }

if ! git rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  echo "FAIL  not a git repository: check.sh reads what git would ship. Run it inside the repo."
  exit 1
fi
SHIPPED="$(mktemp)"
trap 'rm -f "$SHIPPED"' EXIT
git ls-files -co --exclude-standard -z > "$SHIPPED"

# 1. Shell scripts parse.
BAD=""
while IFS= read -r -d '' file; do
  case "$file" in *.sh) bash -n "$file" 2> /dev/null || BAD="$BAD $file" ;; esac
done < "$SHIPPED"
[ -z "$BAD" ] && pass "shell scripts parse" || flunk "shell scripts parse:$BAD (run: bash -n <file>)"

# 2. Terraform files are formatted. Each folder that holds a .tf is checked on its own.
TF_DIRS="$(tr '\0' '\n' < "$SHIPPED" | grep '\.tf$' | xargs -n1 dirname 2> /dev/null | sort -u || true)"
if [ -z "$TF_DIRS" ]; then
  pass "terraform fmt (no .tf files yet)"
else
  BAD=""
  for dir in $TF_DIRS; do terraform fmt -check "$dir" > /dev/null 2>&1 || BAD="$BAD $dir"; done
  [ -z "$BAD" ] && pass "terraform fmt" || flunk "terraform fmt:$BAD (run: terraform fmt <folder>)"
fi

# 3 to 6 read file contents, so they share one Python pass. Each prints its own PASS or FAIL line.
python3 - "$SHIPPED" << 'PY' || FAILED=1
import os, re, sys

# Stand-ins the docs may use for an AWS account. Anything else with 12 digits is treated as real.
STAND_INS = {"123456789012", "111111111111", "222222222222", "333333333333"}
STATE_NAME = re.compile(r"(^|/)([^/]*\.tfstate(\.[^/]*)?|tfplan|[^/]*\.tfplan)$")
ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
SECRET_FIELD = re.compile(r'"(?:sessionToken|SessionToken|secretAccessKey|SecretAccessKey)"\s*:\s*"(?!REDACTED")[^"]+"')
CLUMIO_TOKEN = re.compile(r"CLUMIO_API_TOKEN=[A-Za-z0-9._-]{20,}")
ACCOUNT = re.compile(r"(?<![0-9A-Za-z])\d{12}(?![0-9A-Za-z])")
LOCK_HASH = re.compile(r'^\s*"(?:h1|zh):')
LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)#\s]+)")

shipped = [p for p in open(sys.argv[1], "rb").read().decode().split("\0") if p]
shipped_set = set(shipped)
findings = {"no state or plan files": [], "no credentials": [], "no account numbers": [], "relative links resolve": []}

def is_shipped(path):
    """A link target ships if it is a shipped file, or a folder holding one."""
    path = os.path.normpath(path)
    return path in shipped_set or any(p.startswith(path + "/") for p in shipped)

for path in shipped:
    if STATE_NAME.search(path):
        findings["no state or plan files"].append(f"{path}: a state or plan file")
        continue
    try:
        text = open(path, "rb").read().decode("utf-8")
    except (UnicodeDecodeError, OSError):
        continue  # Images and other binaries: nothing here can hold text secrets we can read.
    if path == "check.sh":
        continue  # This file holds the patterns and stand-ins it looks for, and has no Markdown links.
    if '"lineage"' in text and '"terraform_version"' in text:
        findings["no state or plan files"].append(f"{path}: Terraform state under another name")
    if ACCESS_KEY.search(text) or SECRET_FIELD.search(text) or CLUMIO_TOKEN.search(text):
        findings["no credentials"].append(f"{path}: an access key, secret, session token or Clumio token")
    for line in text.splitlines():
        if path.endswith(".terraform.lock.hcl") and LOCK_HASH.match(line):
            continue  # Provider hashes are long hex runs, not account numbers.
        for number in ACCOUNT.findall(line):
            if number not in STAND_INS:
                findings["no account numbers"].append(f"{path}: 12-digit number {number[:2]}********** (use 123456789012)")
    if path.endswith(".md"):
        for target in LINK.findall(text):
            if not is_shipped(os.path.join(os.path.dirname(path), target)):
                findings["relative links resolve"].append(f"{path}: broken link {target}")

failed = False
for check, found in findings.items():
    if found:
        failed = True
        print(f"FAIL  {check}")
        for line in sorted(set(found))[:20]:
            print(f"        {line}")
    else:
        print(f"PASS  {check}")
sys.exit(1 if failed else 0)
PY

# 7. The checks above, proven against cases that must pass and must fail.
if [ "${CHECK_SELFTEST:-on}" = off ]; then
  echo "SKIP  self-test (CHECK_SELFTEST=off)"
else
  tests/check_test.sh > /dev/null 2>&1 && pass "self-test: tests/check_test.sh" \
    || flunk "self-test: tests/check_test.sh (run it to see which case)"
fi

[ "$FAILED" = 0 ] && echo "ALL CHECKS PASS" || { echo "CHECKS FAILED"; exit 1; }
