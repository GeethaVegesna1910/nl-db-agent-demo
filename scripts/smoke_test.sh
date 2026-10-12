#!/usr/bin/env bash
# Smoke test: start the whole project with Docker and check that every part
# answers. Prints PASS or FAIL for each check.
#
#   ./scripts/smoke_test.sh
#
# The stack is left running afterwards so you can open it in a browser.
# Stop it with: docker compose down
#
# Note: the "total revenue" check makes one real AI call (a fraction of a cent).

set -u
cd "$(dirname "$0")/.."   # run from the project folder, wherever it was called from

API=http://localhost:8001
SITE=http://localhost:8080
PROMETHEUS=http://localhost:9091
SMOKE_USER=smoke-test     # a made-up user, so your own chats are untouched

failures=0
pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; [ -n "${2:-}" ] && echo "      $2"; failures=$((failures + 1)); }

# Keep asking a URL until it answers, or give up after N seconds.
wait_for() {  # wait_for <url> <seconds>
  local waited=0
  until curl -fsS -o /dev/null --max-time 3 "$1" 2>/dev/null; do
    waited=$((waited + 2))
    [ "$waited" -ge "$2" ] && return 1
    sleep 2
  done
}

echo "Starting the stack (the first build takes a few minutes)..."
if docker compose up -d --build --quiet-pull > /tmp/nldb_smoke_up.log 2>&1; then
  pass "docker compose up -d --build"
else
  fail "docker compose up -d --build" "see /tmp/nldb_smoke_up.log"
  tail -n 15 /tmp/nldb_smoke_up.log
  exit 1
fi

echo "Waiting for the API..."
if ! wait_for "$API/health" 120; then
  fail "API became healthy within 120s" "try: docker compose logs api"
  exit 1
fi

# 1. /health: the server is up and can reach the database.
health=$(curl -fsS --max-time 5 "$API/health" 2>/dev/null)
if echo "$health" | grep -q '"status":"ok"' && echo "$health" | grep -q '"database_connected":true'; then
  pass "GET /health  ->  $health"
else
  fail "GET /health" "got: ${health:-nothing}"
fi

# 2. A real question, end to end: AI -> SQL -> database -> formatted answer.
answer=$(curl -sS --max-time 90 -X POST "$API/query" \
  -H 'Content-Type: application/json' \
  -d "{\"question\": \"total revenue\", \"user_id\": \"$SMOKE_USER\"}" 2>/dev/null)
if echo "$answer" | grep -q '"sql":"' && echo "$answer" | grep -q '"chart":"number"'; then
  summary=$(echo "$answer" | sed -E 's/.*"summary":"([^"]*)".*/\1/')
  pass "POST /query 'total revenue'  ->  $summary"
else
  fail "POST /query 'total revenue'" "got: ${answer:-nothing}  (is ANTHROPIC_API_KEY set in .env, and is the database seeded?)"
fi

# 3. /metrics: the counters exist and have counted the question above.
metrics=$(curl -fsS --max-time 5 "$API/metrics" 2>/dev/null)
missing=""
for name in nldb_http_requests_total nldb_http_request_duration_seconds_count \
            nldb_questions_answered_total nldb_questions_rejected_total nldb_errors_total; do
  echo "$metrics" | grep -q "^$name" || missing="$missing $name"
done
answered=$(echo "$metrics" | awk '$1 == "nldb_questions_answered_total" { print $2 }')
if [ -z "$missing" ] && echo "$metrics" | grep -q 'endpoint="/query"'; then
  pass "GET /metrics shows the counters  (questions answered: ${answered:-?})"
else
  fail "GET /metrics shows the counters" "missing:${missing:- the /query request count}"
fi

# 4. The website is being served.
wait_for "$SITE/" 60
site_status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$SITE/")
if [ "$site_status" = "200" ]; then
  pass "Website returns 200  ($SITE)"
else
  fail "Website returns 200" "got HTTP $site_status"
fi

# 5. Prometheus has collected from the API at least once and reports it as up.
#    The first collection happens a few seconds after start, so allow a little time.
up=""
for _ in $(seq 1 20); do
  up=$(curl -s --max-time 5 -G "$PROMETHEUS/api/v1/query" --data-urlencode 'query=up{job="api"}' 2>/dev/null)
  echo "$up" | grep -q '"value":\[[0-9.]*,"1"\]' && break
  sleep 3
done
if echo "$up" | grep -q '"value":\[[0-9.]*,"1"\]'; then
  pass "Prometheus sees the API as up"
else
  fail "Prometheus sees the API as up" "got: ${up:-nothing}"
fi

# Tidy up the chat this test created.
docker compose exec -T postgres psql -q -U postgres -d nl_db_agent \
  -c "DELETE FROM conversations WHERE user_id = '$SMOKE_USER'" > /dev/null 2>&1

echo
if [ "$failures" -eq 0 ]; then
  echo "All checks passed. The stack is still running:"
  echo "  Website     $SITE"
  echo "  API docs    $API/docs"
  echo "  Prometheus  $PROMETHEUS"
  echo "Stop it with: docker compose down"
else
  echo "$failures check(s) failed."
  exit 1
fi
