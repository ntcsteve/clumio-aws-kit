#!/usr/bin/env bash
# Checks extract.py against saved plans (account 123456789012, ap-southeast-2), made from real
# read-only plans at aws-template 0.42.0 with the account masked. Each case's
# output must match its expected/ exactly, so any change to what the security team sees shows
# up as a diff.
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
exit "$FAILED"
