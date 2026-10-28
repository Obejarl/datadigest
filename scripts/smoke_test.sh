#!/usr/bin/env sh
# Smoke-test a running DataDigest: readiness, then a full profile and a full optimization
# (proves the bundled samples and the SciPy solver are in the image, not just that it boots).
#
#   scripts/smoke_test.sh http://localhost:8000
set -eu
BASE="${1:-http://localhost:8000}"

# With ACCESS_TOKEN set the calls carry it as a bearer token (the server may require one).
api() {
  if [ -n "${ACCESS_TOKEN:-}" ]; then curl -fsS -H "Authorization: Bearer $ACCESS_TOKEN" "$@"; else curl -fsS "$@"; fi
}
PY="${PYTHON:-python3}"  # e.g. PYTHON=.venv/Scripts/python on Windows
json() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "waiting for $BASE/readyz"
i=0
until curl -fsS "$BASE/readyz" >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -ge 40 ] && { echo "API never became ready"; exit 1; }
  sleep 1
done

wait_for() {  # $1 = resource URL, prints the final "status result" line
  i=0
  while :; do
    line=$(api "$1" | json "d['status'], d.get('result_status') or ''")
    case "$line" in
      done*|failed*) echo "$line"; return ;;
    esac
    i=$((i + 1)); [ "$i" -ge 60 ] && { echo "timeout"; return; }
    sleep 1
  done
}

dataset=$(api -X POST "$BASE/api/samples/sales.csv" | json "d['id']")
profile=$(wait_for "$BASE/api/datasets/$dataset")
echo "profile: $profile"
[ "$(echo "$profile" | cut -d' ' -f1)" = "done" ] || exit 1

for kind in production transport assignment knapsack; do
  run=$(api -X POST "$BASE/api/optimize/examples/$kind" | json "d['id']")
  result=$(wait_for "$BASE/api/optimizations/$run")
  echo "$kind: $result"
  [ "$result" = "done optimal" ] || exit 1
done

api "$BASE/api/capacity" | json "'capacity: %s workers recommended' % d['objective']"
echo "smoke test passed"
