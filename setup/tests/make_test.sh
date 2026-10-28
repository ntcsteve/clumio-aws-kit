#!/usr/bin/env bash
# Tests for setup/Makefile: the order it enforces, and the checks after each apply. Runs the real Makefile against
# a stand-in `terraform` that records each call and answers as told, so no AWS, no Clumio, no network.
# Runs on macOS's stock bash 3.2 and GNU Make 3.81. Run: setup/tests/make_test.sh
set -euo pipefail

SETUP="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILED=0
CASES=0

# The stand-in. Its answers come from files in its folder: apply.exit, plan.exit, state.txt, plan.txt.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/terraform" << 'STUB'
#!/usr/bin/env bash
here="$(cd "$(dirname "$0")" && pwd)"
echo "terraform $*" >> "$here/calls.log"
answer() { [ -f "$here/$1" ] && cat "$here/$1" || echo "$2"; }
case "$1" in
  init) exit 0 ;;
  apply) exit "$(answer apply.exit 0)" ;;
  state) [ -f "$here/state.txt" ] && cat "$here/state.txt"; exit 0 ;;
  plan)
    for arg in "$@"; do case "$arg" in -out=*) : > "${arg#-out=}" ;; esac; done
    [ -f "$here/plan.txt" ] && cat "$here/plan.txt"
    exit "$(answer plan.exit 0)" ;;
esac
STUB
chmod +x "$WORK/bin/terraform"

# A stand-in status.py, copied into each case's folder: records how it was called, exits as told
# (status.exit for plain status, teardown.exit for --teardown, preview.exit for --preview).
cat > "$WORK/status.py" << 'STUB'
#!/usr/bin/env bash
here="$(dirname "$0")"; bin="$(dirname "$(command -v terraform)")"
echo "status.py $*" >> "$bin/calls.log"
case "$1" in --teardown) f=teardown.exit ;; --preview) f=preview.exit ;; *) f=status.exit ;; esac
[ -f "$bin/$f" ] && exit "$(cat "$bin/$f")"; exit 0
STUB
chmod +x "$WORK/status.py"

# run_case <name> <make target> <setup command> <expected exit: 0 or 1> <check command, run after>
run_case() {
  local name="$1" target="$2" setup="$3" expected="$4" check="$5" folder output status
  CASES=$((CASES + 1))
  folder="$WORK/case$CASES"
  mkdir -p "$folder"
  cp "$SETUP/Makefile" "$WORK/status.py" "$folder/"
  rm -f "$WORK/bin/"{calls.log,apply.exit,plan.exit,state.txt,plan.txt,status.exit,teardown.exit,preview.exit}
  (cd "$folder" && eval "$setup")
  set +e
  output="$(cd "$folder" && PATH="$WORK/bin:$PATH" make -s "$target" 2>&1)"
  status=$?
  set -e
  [ "$status" -ne 0 ] && status=1
  if [ "$status" = "$expected" ] && (cd "$folder" && CALLS="$WORK/bin/calls.log" OUTPUT="$output" eval "$check"); then
    printf 'ok    %s\n' "$name"
  else
    printf 'FAIL  %s: exit %s (expected %s)\n' "$name" "$status" "$expected"
    sed 's/^/        /' <<< "$output"
    [ -f "$WORK/bin/calls.log" ] && sed 's/^/        call: /' "$WORK/bin/calls.log"
    FAILED=1
  fi
}

run_case "apply refuses without a saved plan" apply ":" 1 \
  'grep -q "No saved plan" <<< "$OUTPUT" && ! grep -q "apply" "$CALLS" 2>/dev/null'
run_case "apply runs the saved plan, finds no changes, then shows status" apply ": > tfplan" 0 \
  'grep -q "terraform apply -input=false tfplan" "$CALLS" && grep -q "PASS  No changes" <<< "$OUTPUT" && [ ! -f tfplan ] && grep -qx "status.py *" "$CALLS"'
run_case "apply fails when status finds something a person must fix" apply ": > tfplan; echo 1 > $WORK/bin/status.exit" 1 \
  'grep -q "PASS  No changes" <<< "$OUTPUT"'
run_case "apply fails when a new plan still shows changes" apply ": > tfplan; echo 2 > $WORK/bin/plan.exit" 1 \
  'grep -q "FAIL  A new plan still shows changes" <<< "$OUTPUT"'
run_case "a failed apply stops, and its plan is removed" apply ": > tfplan; echo 1 > $WORK/bin/apply.exit" 1 \
  '[ ! -f tfplan ] && ! grep -q -- "-detailed-exitcode" "$CALLS"'
run_case "apply runs a teardown plan, then finds nothing left" apply \
  ": > teardown.tfplan; printf 'data.aws_region.here\nmodule.connection.data.aws_caller_identity.signed_in\n' > $WORK/bin/state.txt" 0 \
  'grep -q "terraform apply -input=false teardown.tfplan" "$CALLS" && grep -q "PASS  Everything this folder created is gone" <<< "$OUTPUT" && [ ! -f teardown.tfplan ]'
run_case "apply fails when a teardown leaves something behind" apply \
  ": > teardown.tfplan; echo module.connection.clumio_aws_connection.this > $WORK/bin/state.txt" 1 \
  'grep -q "FAIL  Still in Terraform.s state" <<< "$OUTPUT" && grep -q "clumio_aws_connection.this" <<< "$OUTPUT"'
run_case "plan drops its saved plan when the preview refuses it" plan "echo 1 > $WORK/bin/preview.exit" 1 \
  '[ ! -f tfplan ] && grep -q "The plan was not kept" <<< "$OUTPUT"'
run_case "plan saves tfplan, previews it, and removes a stale teardown plan" plan ": > teardown.tfplan" 0 \
  '[ -f tfplan ] && [ ! -f teardown.tfplan ] && grep -q "status.py --preview" "$CALLS" && grep -q "Next: read the plan" <<< "$OUTPUT"'
run_case "teardown checks first, saves a destroy plan, and removes a stale plan" teardown ": > tfplan" 0 \
  '[ -f teardown.tfplan ] && [ ! -f tfplan ] && grep -q "status.py --teardown" "$CALLS" && grep -q "terraform plan -destroy" "$CALLS"'
run_case "teardown saves nothing while a backup runs, or in production" teardown "echo 1 > $WORK/bin/teardown.exit" 1 \
  '[ ! -f teardown.tfplan ] && ! grep -q "terraform plan -destroy" "$CALLS"'
run_case "status shows coverage" status ":" 0 'grep -qx "status.py *" "$CALLS"'
run_case "a failed plan stops make" plan "echo 1 > $WORK/bin/plan.exit" 1 \
  '! grep -q "Next: read the plan above" <<< "$OUTPUT"'
[ "$FAILED" = 0 ] && echo "Makefile tests: all $CASES cases pass" || { echo "Makefile tests: FAILED"; exit 1; }
