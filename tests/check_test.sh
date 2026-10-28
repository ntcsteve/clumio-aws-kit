#!/usr/bin/env bash
# Tests for ../check.sh. Each case copies the repo as git would ship it into a temporary folder,
# changes one thing, runs check.sh there, and expects it to pass, or to fail at the named check.
# The copy runs check.sh with CHECK_SELFTEST=off, so check.sh never calls these tests again.
# Runs on macOS's stock bash 3.2. Needs git and python3; no network, no AWS, no Clumio.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILED=0
CASES=0

# Stand-ins built at run time, so this file never holds a value check.sh refuses.
ACCOUNT="98765""4321098"       # a real-looking account number, outside the allowlist
ACCESS_KEY="AKIA""Q3EXAMPLEKEY7WZX" # the shape of an AWS access key ID: AKIA and 16 more

# A fresh copy of what git would ship from this repo, in its own git repo.
fresh_copy() {
  local copy="$WORK/$1"
  mkdir -p "$copy"
  (cd "$ROOT" && git ls-files -co --exclude-standard -z | xargs -0 tar -cf -) | tar -xf - -C "$copy"
  (cd "$copy" && git init -q -b main)
  echo "$copy"
}

# expect_result <case name> <pass|fail> <text the output must hold, or ""> <setup command, run in the copy>
expect_result() {
  local name="$1" expected="$2" must_say="$3" setup="$4" copy output status
  CASES=$((CASES + 1))
  copy="$(fresh_copy "case$CASES")"
  (cd "$copy" && eval "$setup")
  set +e
  output="$(cd "$copy" && CHECK_SELFTEST=off ./check.sh 2>&1)"
  status=$?
  set -e
  if [ "$expected" = pass ] && [ "$status" -eq 0 ]; then
    printf 'ok    %s\n' "$name"
  elif [ "$expected" = fail ] && [ "$status" -ne 0 ] && grep -qF -- "$must_say" <<< "$output"; then
    printf 'ok    %s\n' "$name"
  else
    printf 'FAIL  %s: expected %s%s, got exit %s\n' "$name" "$expected" "${must_say:+ at \"$must_say\"}" "$status"
    sed 's/^/        /' <<< "$output"
    FAILED=1
  fi
}

# A minimal Terraform state, its two marker keys split so this file isn't state itself.
STATE='{"version": 4, "terraform_''version": "1.15.5", "serial": 1, "line''age": "5f1c2e9a-7b3d-4c1e-9a2b-8d7e6f5a4b3c", "outputs": {}, "resources": []}'

expect_result "clean tree passes" pass "" ":"
expect_result "a real, ignored terraform.tfvars and state are left alone" pass "" \
  "mkdir -p setup && printf 'account_id = \"$ACCOUNT\"\n' > setup/terraform.tfvars && printf '%s' '$STATE' > setup/terraform.tfstate"
expect_result "a force-added state file fails" fail "FAIL  no state or plan files" \
  "mkdir -p setup && printf '%s' '$STATE' > setup/terraform.tfstate && git add -f setup/terraform.tfstate"
expect_result "a state file under another name fails" fail "FAIL  no state or plan files" \
  "printf '%s' '$STATE' > notes.json"
expect_result "a force-added plan fails" fail "FAIL  no state or plan files" \
  "mkdir -p setup && printf 'PK' > setup/tfplan && git add -f setup/tfplan"
expect_result "an account number in a doc fails" fail "FAIL  no account numbers" \
  "printf 'Connect account $ACCOUNT first.\n' > notes.md"
expect_result "an access key fails" fail "FAIL  no credentials" \
  "printf 'aws_access_key_id = $ACCESS_KEY\n' > notes.md"
expect_result "12-digit runs inside lock-file hashes pass" pass "" \
  "mkdir -p setup && printf 'provider \"x\" {\n  hashes = [\n    \"zh:$ACCOUNT\",\n  ]\n}\n' > setup/.terraform.lock.hcl"
expect_result "a broken relative link fails" fail "FAIL  relative links resolve" \
  "printf 'See [the guide](docs/missing.md).\n' > notes.md"

[ "$FAILED" = 0 ] && echo "check.sh tests: all $CASES cases pass" || { echo "check.sh tests: FAILED"; exit 1; }
