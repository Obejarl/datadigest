#!/usr/bin/env sh
# Smoke-test a running DataDigest: readiness, then six full profiles of the bundled samples
# (proves the samples and the statistics stack are in the image, not just that it boots;
# six jobs queued at once also give every worker something to do).
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

ids=""
for sample in sales.csv tr_survey.csv sales.csv tr_survey.csv sales.csv tr_survey.csv; do
  ids="$ids $(api -X POST "$BASE/api/samples/$sample" | json "d['id']")"
done
for dataset in $ids; do
  profile=$(wait_for "$BASE/api/datasets/$dataset")
  echo "profile $dataset: $profile"
  [ "$(echo "$profile" | cut -d' ' -f1)" = "done" ] || exit 1
done
api "$BASE/api/datasets/$dataset/profile" | json "'quality score: %s' % d['summary']['quality']['score']"

api "$BASE/api/capacity" | json "'capacity: %s workers recommended' % d['objective']"
echo "smoke test passed"
