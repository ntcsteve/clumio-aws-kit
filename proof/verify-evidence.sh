#!/usr/bin/env bash
# Checks every evidence capture against its sha256 manifest. Read-only, offline, needs no credentials.
#
#   proof/verify-evidence.sh
#
# It catches a file changed after capture. It can't catch an added file or a regenerated manifest: for
# that, keep the root hash it prints somewhere outside this repository, and compare it later.
# Each folder is checked from inside, because the manifests hold relative paths.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
FOLDERS=0; FILES=0; FAILED=0
MANIFESTS="$(find "$HERE/evidence" -name _sha256.txt | sort)"
for manifest in $MANIFESTS; do
  dir="$(dirname "$manifest")"
  FOLDERS=$((FOLDERS + 1))
  RESULT="$(cd "$dir" && shasum -a 256 -c _sha256.txt 2>&1)"
  OK="$(grep -c ': OK$' <<< "$RESULT")"
  BAD="$(grep -vc ': OK$' <<< "$RESULT")"
  FILES=$((FILES + OK)); FAILED=$((FAILED + BAD))
  [ "$BAD" = 0 ] || { echo "FAILED  ${dir#$HERE/}: $BAD file(s)"; grep -v ': OK$' <<< "$RESULT" | sed 's/^/          /'; }
done
echo "$FOLDERS captures, $FILES files verified, $FAILED failures"
echo "root hash of all manifests: $(cat $MANIFESTS | shasum -a 256 | cut -d' ' -f1)"
[ "$FAILED" = 0 ] && [ "$FOLDERS" -gt 0 ] && echo "RESULT: OK" || { echo "RESULT: EVIDENCE CHANGED OR MISSING"; exit 1; }
