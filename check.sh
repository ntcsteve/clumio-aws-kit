#!/usr/bin/env bash
# Checks this repository before every commit. Offline: it never calls AWS or Clumio.
# It reads only what git would ship (tracked files, and new files that .gitignore doesn't exclude),
# so your own terraform.tfvars, state and .terraform/ never fail it, and never leave your machine.
# Runs on macOS's stock bash 3.2. Needs git, python3, make, Terraform 1.10+ and the Terraform registry.
# The scans take seconds; the suites take a few minutes.
#   Scans:
#   1. shell scripts         every *.sh parses
#   2. terraform fmt         every .tf is formatted
#      evidence              every capture in proof/evidence matches its checksums
#   3. no state or plans     by name, and by content (a renamed state file still holds "lineage")
#   4. no credentials        AWS access keys, unredacted session tokens or secret keys, a Clumio token
#   5. no account numbers    any 12-digit number outside the stand-ins below
#   6. relative links        every relative link in a Markdown file points at a file that ships
#   7. setting rules agree   account, Region, unit and mode are checked the same way in setup/, both
#                            modules and status.py, so a fix to one copy can't silently miss another
#   Suites, on a copy of what ships (never your .terraform, terraform.tfvars or state):
#   8. setup                 validates with its lock file; the shipped placeholders stop the plan
#   9. module tests          each module, and the proof lab, refuses what it must (mock providers)
#  10. preview golden tests what the security team sees matches the reviewed output exactly
#  11. status tests          status.py's checks, against fake AWS and Clumio answers that filter as Clumio does
#      Makefile tests        the order make enforces, and its after-checks, against a stand-in terraform
#  12. self-test             tests/check_test.sh proves each scan passes and fails when it should
# CHECK_SCANS_ONLY=1 runs the scans only. tests/check_test.sh sets it, so this never loops.
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
COPIES="$(mktemp -d)"
trap 'rm -rf "$SHIPPED" "$COPIES"' EXIT
git ls-files -co --exclude-standard -z > "$SHIPPED"

# 1. Shell scripts parse, and they and status.py can run (make calls them directly).
BAD=""
while IFS= read -r -d '' file; do
  case "$file" in
    *.sh) { bash -n "$file" 2> /dev/null && [ -x "$file" ]; } || BAD="$BAD $file" ;;
    */status.py) [ -x "$file" ] || BAD="$BAD $file" ;;
  esac
done < "$SHIPPED"
[ -z "$BAD" ] && pass "shell scripts parse and are executable" \
  || flunk "shell scripts parse and are executable:$BAD (run: bash -n <file>; chmod +x <file>)"

# 2b. Evidence is unchanged since capture: every folder matches its _sha256.txt.
if [ -x proof/verify-evidence.sh ]; then
  proof/verify-evidence.sh > /dev/null 2>&1 && pass "evidence unchanged since capture" \
    || flunk "evidence unchanged since capture (run proof/verify-evidence.sh to see which file)"
fi

# 2. Terraform files are formatted. Each folder that holds a .tf is checked on its own.
TF_DIRS="$(tr '\0' '\n' < "$SHIPPED" | grep '\.tf$' | xargs -n1 dirname 2> /dev/null | sort -u || true)"
if [ -z "$TF_DIRS" ]; then
  pass "terraform fmt (no .tf files yet)"
else
  BAD=""
  for dir in $TF_DIRS; do terraform fmt -check "$dir" > /dev/null 2>&1 || BAD="$BAD $dir"; done
  [ -z "$BAD" ] && pass "terraform fmt" || flunk "terraform fmt:$BAD (run: terraform fmt <folder>)"
fi

# 3 to 7 read file contents, so they share one Python pass. Each prints its own PASS or FAIL line.
python3 - "$SHIPPED" << 'PY' || FAILED=1
import os, re, sys

# Stand-ins the docs may use for an AWS account. Anything else with 12 digits is treated as real.
# 000000000000 is the tail of Clumio's Global unit ID, 00000000-0000-0000-0000-000000000000.
# 137112412989 is Amazon's own account, the public owner of Amazon Linux images (in the EC2 evidence).
STAND_INS = {"123456789012", "111111111111", "222222222222", "333333333333", "000000000000", "137112412989"}
STATE_NAME = re.compile(r"(^|/)([^/]*\.tfstate(\.[^/]*)?|tfplan|[^/]*\.tfplan)$")
ACCESS_KEY = re.compile(r"\b(?:AKIA|ASIA)(?!X{16}\b)[A-Z0-9]{16}\b")  # ASIAXXXXXXXXXXXXXXXX is the evidence's masked form
SECRET_FIELD = re.compile(r'"(?:sessionToken|SessionToken|secretAccessKey|SecretAccessKey)"\s*:\s*"(?!REDACTED")[^"]+"')
CLUMIO_TOKEN = re.compile(r"CLUMIO_API_TOKEN=[A-Za-z0-9._-]{20,}")
# Twelve digits on their own. A UUID's last group can be all digits (a KMS key ID): skip only that,
# so an account inside a name such as orders-<account>-us-west-2 is still caught.
ACCOUNT = re.compile(r"(?<![0-9A-Za-z])(?<![0-9a-fA-F]{4}-)\d{12}(?![0-9A-Za-z])")
LOCK_HASH = re.compile(r'^\s*"(?:h1|zh):')
LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)#\s]+)")

shipped = [p for p in open(sys.argv[1], "rb").read().decode().split("\0") if p]
shipped_set = set(shipped)
findings = {"no state or plan files": [], "no credentials": [], "no account numbers": [], "relative links resolve": [],
            "setting rules agree": []}

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

# 7. One rule per setting. Terraform states it as regex(...) or contains([...]); status.py as a pattern.
def tf_rules(path):
    text = open(path, encoding="utf-8").read()
    rules = {name: re.search(r'regex\("([^"]*)",\s*var\.' + name + r'\)', text) for name in ("account_id", "region", "organizational_unit")}
    rules = {name: "^(global|" + m.group(1)[1:-1] + ")$" if name == "organizational_unit" else m.group(1) for name, m in rules.items() if m}
    mode = re.search(r'contains\(\[([^\]]*)\],\s*var\.mode\)', text)
    if mode:
        rules["mode"] = "^(" + "|".join(re.findall(r'"([^"]+)"', mode.group(1))) + ")$"
    return rules

copies = {path: tf_rules(path) for path in ("setup/variables.tf", "modules/connection/variables.tf", "modules/profile/variables.tf", "proof/lab/variables.tf")
          if path in shipped_set}
if "setup/status.py" in shipped_set:
    shapes = re.search(r"SETTING_SHAPES = \{(.*?)\n\}", open("setup/status.py", encoding="utf-8").read(), re.S)
    copies["setup/status.py"] = dict(re.findall(r'"(\w+)": \(r"([^"]*)"', shapes.group(1))) if shapes else {}
for name in ("account_id", "region", "organizational_unit", "mode"):
    seen = {path: rules[name] for path, rules in copies.items() if name in rules}
    if len(set(seen.values())) > 1:
        findings["setting rules agree"].append(f"{name} differs: " + "; ".join(f"{path} {rule}" for path, rule in sorted(seen.items())))
for path, rules in copies.items():
    expected = {"account_id", "region"} | (set() if path.startswith("proof/") else {"mode"}) | ({"organizational_unit"} if path.startswith("setup/") else set())
    if not expected <= set(rules):
        findings["setting rules agree"].append(f"{path}: can't find the rule for {', '.join(sorted(expected - set(rules)))}")

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

if [ "${CHECK_SCANS_ONLY:-0}" = 1 ]; then
  echo "SKIP  suites and self-test (CHECK_SCANS_ONLY=1)"
  [ "$FAILED" = 0 ] && echo "ALL CHECKS PASS" || { echo "CHECKS FAILED"; exit 1; }
  exit 0
fi

# The suites run on a copy of what ships, so local working files never change a result.
xargs -0 tar -cf - < "$SHIPPED" | tar -xf - -C "$COPIES"

# 8. setup validates with its committed lock file, and the shipped placeholders stop the plan.
if (cd "$COPIES/setup" && terraform init -backend=false -input=false -lockfile=readonly > /dev/null 2>&1 \
    && terraform validate -no-color > /dev/null 2>&1); then
  pass "setup: terraform validate"
  out="$(cd "$COPIES/setup" && cp settings.example terraform.tfvars && terraform plan -input=false -no-color 2>&1 || true)"
  MISSING=""
  for setting in account_id region organizational_unit mode; do
    grep -q "Set $setting in terraform.tfvars" <<< "$out" || MISSING="$MISSING $setting"
  done
  # With those four set, the PITR placeholder must still stop it. Terraform wraps long messages, so join lines.
  out="$(cd "$COPIES/setup" && sed -e 's/"ACCOUNT-ID-REPLACE-THIS"/"123456789012"/' -e 's/"REGION-REPLACE-THIS"/"us-west-2"/' \
    -e 's/"UNIT-REPLACE-THIS"/"global"/' -e 's/"MODE-REPLACE-THIS"/"trial"/' settings.example > terraform.tfvars \
    && terraform plan -input=false -no-color 2>&1 | tr '\n' ' ' || true)"
  grep -q "Set pitr_retention_days in terraform.tfvars" <<< "$out" || MISSING="$MISSING pitr_retention_days"
  [ -z "$MISSING" ] && pass "setup: the shipped placeholders stop the plan" \
    || flunk "setup: these placeholders did not stop the plan:$MISSING"
else
  flunk "setup: terraform init or validate (lock file out of date? run them in setup/ to see why)"
fi

# 9. Each module refuses what it must, with mock providers.
for module in modules/connection modules/connection/iam modules/profile proof/lab; do
  (cd "$COPIES/$module" && terraform init -backend=false -input=false > /dev/null 2>&1 && terraform test -no-color > /dev/null 2>&1) \
    && pass "$module: tests" || flunk "$module: tests (run terraform test in $module to see why)"
done

# 10. The preview renders exactly what the security team reviewed.
"$COPIES/setup/preview/test/test.sh" > /dev/null 2>&1 && pass "setup/preview: golden tests" \
  || flunk "setup/preview: golden tests (run setup/preview/test/test.sh to see the diff)"

# 11. status.py's checks, against fake AWS and Clumio answers.
(cd "$COPIES/setup" && python3 -W error -m unittest discover -s tests > /dev/null 2>&1) && pass "setup/status.py: tests" \
  || flunk "setup/status.py: tests (run: python3 -m unittest discover -s tests, in setup/)"

# 11c. The evidence capture masks the account and unit, and writes a manifest shasum verifies.
(cd "$COPIES/proof" && python3 -W error -m unittest discover -s tests > /dev/null 2>&1) && pass "proof/capture.py: tests" \
  || flunk "proof/capture.py: tests (run: python3 -m unittest discover -s tests, in proof/)"

# 11b. The order the Makefile enforces, and its checks after each apply, against a stand-in terraform.
"$COPIES/setup/tests/make_test.sh" > /dev/null 2>&1 && pass "setup/Makefile: tests" \
  || flunk "setup/Makefile: tests (run setup/tests/make_test.sh to see which case)"

# 12. The scans above, proven against cases that must pass and must fail.
tests/check_test.sh > /dev/null 2>&1 && pass "self-test: tests/check_test.sh" \
  || flunk "self-test: tests/check_test.sh (run it to see which case)"

[ "$FAILED" = 0 ] && echo "ALL CHECKS PASS" || { echo "CHECKS FAILED"; exit 1; }
