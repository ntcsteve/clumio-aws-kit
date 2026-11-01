#!/usr/bin/env bash
# Checks extract.py against saved plans (account 123456789012, ap-southeast-2), made from real
# read-only plans at aws-template 0.42.0 with the account masked. Each case's
# output must match its expected/ exactly, so any change to what the security team sees shows
# up as a diff. Then runs preview.sh itself, with stand-ins: it finds its files, and each of its three
# endings exits as it should.
#   regulated/  S3 + RDS + EC2/EBS, prefix + path "/", role tags, boundary, pass-role deny list
#   defaults/   the shipped settings: no prefix, path "/clumio/", S3 + RDS + EC2/EBS (one policy lands at "/")
#
#   ./test.sh            compare
#   ./test.sh --update   accept the current output as expected (review the diff first)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUN="$(mktemp -d)"
trap 'rm -rf "$RUN"' EXIT
FAILED=0

for case in regulated defaults; do
  mkdir -p "$RUN/$case/pack/policies" "$RUN/$case/work"
  python3 "$HERE/../extract.py" "$HERE/$case/plan.json" "$RUN/$case/pack" 123456789012 ap-southeast-2 "$RUN/$case/work" \
    > "$RUN/$case/pack/stdout.txt"
  cp "$RUN/$case/work/deploy-check.tsv" "$RUN/$case/pack/"
  if [ "${1:-}" = "--update" ]; then
    rm -rf "$HERE/$case/expected" && cp -R "$RUN/$case/pack" "$HERE/$case/expected" && echo "updated $case/expected/"
  elif diff -r "$HERE/$case/expected" "$RUN/$case/pack"; then
    echo "PASS: $case"
  else
    echo "FAIL: $case output changed (see diff above)"; FAILED=1
  fi
done

# preview.sh itself: in a copy of the repo's layout, with a stand-in aws that's never signed in, it
# must find 1-connect's settings and the IAM module, and stop only at the sign-in. The goldens above
# never run it, so a wrong path here would otherwise reach a user first.
REPO="$(cd "$HERE/../../.." && pwd)"
TREE="$RUN/tree"
mkdir -p "$TREE/0-check" "$TREE/1-connect" "$TREE/modules/connection" "$RUN/bin"
cp -R "$REPO/0-check/preview" "$TREE/0-check/"
cp -R "$REPO/modules/connection/iam" "$TREE/modules/connection/"
cp "$REPO/1-connect/variables.tf" "$REPO/1-connect/versions.tf" "$TREE/1-connect/"
cp "$REPO/1-connect/settings.example" "$TREE/1-connect/terraform.tfvars"
printf '#!/bin/sh\nexit 255\n' > "$RUN/bin/aws" && chmod +x "$RUN/bin/aws"
said="$(PATH="$RUN/bin:$PATH" "$TREE/0-check/preview/preview.sh" 2>&1 || true)"
if grep -q "not signed in to AWS" <<< "$said"; then
  echo "PASS: preview.sh finds 1-connect and the IAM module"
else
  echo "FAIL: preview.sh stopped before the sign-in:"; sed 's/^/  /' <<< "$said"; FAILED=1
fi

# Its three endings: the exit code a script or an agent reads must match the word a person reads, and
# the pack must survive either way, because security reviews it. Stand-in aws and terraform reach the
# end offline. The account differs from the saved plan's: preview.sh refuses a pack showing its own.
cat > "$RUN/bin/terraform" << EOF
#!/bin/sh
[ "\$1" = show ] && cat "$HERE/defaults/plan.json"
exit 0
EOF
cat > "$RUN/bin/aws" << 'EOF'
#!/bin/sh
case "$*" in
  *"--query Account"*) echo 333333333333 ;;
  *"--query Arn"*) echo "$STUB_ARN" ;;
  *simulate-principal-policy*)
    [ "$STUB_SIMULATOR" != refused ] || { echo "An error occurred (AccessDenied)" >&2; exit 254; }
    printf 'iam:CreateRole\t%s\n' "$STUB_SIMULATOR" ;;
esac
EOF
chmod +x "$RUN/bin/terraform" "$RUN/bin/aws"

check_ending() {  # who is signed in, what the simulator answers, the word, the exit code
  local said code=0
  rm -rf "$RUN"/clumio-iam-preview-*
  said="$(cd "$RUN" && PATH="$RUN/bin:$PATH" STUB_ARN="$1" STUB_SIMULATOR="$2" "$TREE/0-check/preview/preview.sh" 2>&1)" || code=$?
  if grep -q "^  $3:" <<< "$said" && [ "$code" = "$4" ] && ls -d "$RUN"/clumio-iam-preview-* > /dev/null 2>&1; then
    echo "PASS: preview.sh $3 ($2) exits $4 and keeps the pack"
  else
    echo "FAIL: preview.sh $3 ($2) should exit $4 and keep the pack; exit $code"; FAILED=1
  fi
}
DEPLOY_USER="arn:aws:iam::333333333333:user/deploy"
check_ending "$DEPLOY_USER" allowed READY 0
check_ending "$DEPLOY_USER" implicitDeny BLOCKED 1
check_ending "$DEPLOY_USER" refused "CANNOT CHECK" 2
check_ending "arn:aws:iam::333333333333:root" allowed "CANNOT CHECK" 2
exit "$FAILED"
