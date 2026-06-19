#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MAX_POLL_ATTEMPTS="${MAX_POLL_ATTEMPTS:-30}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-1}"

compose() {
  docker compose "$@"
}

cleanup() {
  echo "Stopping Docker Compose services..."
  compose down -v
}

trap cleanup EXIT

wait_for_api() {
  echo "Waiting for API..."

  for attempt in $(seq 1 30); do
    if curl -sf "$BASE_URL/docs" > /dev/null; then
      echo "API is ready."
      return 0
    fi

    echo "API not ready yet. attempt=$attempt"
    sleep 1
  done

  echo "API did not become ready."
  compose logs api --tail=100
  exit 1
}

json_value() {
  local expression="$1"

  "$PYTHON_BIN" -c '
import json
import sys

data = json.load(sys.stdin)

for part in sys.argv[1].split("."):
    if part:
        data = data[part]

if isinstance(data, (dict, list)):
    print(json.dumps(data))
else:
    print(data)
' "$expression"
}

json_list_contains_id() {
  local expected_id="$1"

  "$PYTHON_BIN" -c '
import json
import sys

expected_id = str(sys.argv[1])
data = json.load(sys.stdin)

if isinstance(data, dict):
    items = data.get("items", [])
else:
    items = data

if not isinstance(items, list):
    print("Expected a list response or an object with an items list.", file=sys.stderr)
    print(json.dumps(data, indent=2), file=sys.stderr)
    sys.exit(1)

for item in items:
    if isinstance(item, dict) and str(item.get("id")) == expected_id:
        sys.exit(0)

print(f"Expected job id {expected_id} was not found in response.", file=sys.stderr)
print(json.dumps(data, indent=2), file=sys.stderr)
sys.exit(1)
' "$expected_id"
}

assert_equal() {
  local actual="$1"
  local expected="$2"
  local message="$3"

  if [ "$actual" != "$expected" ]; then
    echo "Assertion failed: $message"
    echo "Expected: $expected"
    echo "Actual:   $actual"
    exit 1
  fi
}

post_job() {
  local body="$1"

  curl -sS -f -X POST "$BASE_URL/jobs" \
    -H "Content-Type: application/json" \
    -d "$body"
}

get_job() {
  local job_id="$1"

  curl -sS -f "$BASE_URL/jobs/$job_id"
}

list_jobs() {
  local status="$1"

  curl -sS -f "$BASE_URL/jobs?status=$status&limit=20&offset=0"
}

wait_for_status() {
  local job_id="$1"
  local expected_status="$2"
  local unexpected_terminal_status="${3:-}"

  echo "Polling job_id=$job_id until status=$expected_status..." >&2

  for attempt in $(seq 1 "$MAX_POLL_ATTEMPTS"); do
    local job_response
    local current_status

    job_response="$(get_job "$job_id")"
    current_status="$(json_value "status" <<< "$job_response")"

    echo "job_id=$job_id attempt=$attempt status=$current_status" >&2

    if [ "$current_status" = "$expected_status" ]; then
      echo "$job_response"
      return 0
    fi

    if [ -n "$unexpected_terminal_status" ] && [ "$current_status" = "$unexpected_terminal_status" ]; then
      echo "Job reached unexpected terminal status."
      echo "$job_response"
      compose logs worker --tail=100
      exit 1
    fi

    sleep "$POLL_INTERVAL_SECONDS"
  done

  echo "Job did not reach expected status in time."
  get_job "$job_id" || true
  compose logs worker --tail=100
  exit 1
}

echo "Starting clean Docker Compose stack..."
compose down -v

echo "Starting infrastructure services..."
compose up -d --build postgres redis

echo "Applying Alembic migrations..."
compose run --rm api alembic upgrade head

echo "Starting API and worker services..."
compose up -d --build api worker

wait_for_api

echo
echo "Scenario 1: successful job reaches completed"

success_response="$(post_job '{"payload": {"text": "e2e success"}}')"
success_id="$(json_value "id" <<< "$success_response")"

echo "Created success job_id=$success_id"

success_job="$(wait_for_status "$success_id" "completed" "failed")"
success_status="$(json_value "status" <<< "$success_job")"

assert_equal "$success_status" "completed" "successful job should complete"

echo "Success job completed."

echo
echo "Scenario 2: failure job reaches failed and stores error_message"

failure_response="$(post_job '{"payload": {"text": "e2e failure", "fail": true}}')"
failure_id="$(json_value "id" <<< "$failure_response")"

echo "Created failure job_id=$failure_id"

failure_job="$(wait_for_status "$failure_id" "failed" "completed")"
failure_status="$(json_value "status" <<< "$failure_job")"
failure_error="$(json_value "error_message" <<< "$failure_job")"

assert_equal "$failure_status" "failed" "failure job should fail"

if [ -z "$failure_error" ] || [ "$failure_error" = "None" ] || [ "$failure_error" = "null" ]; then
  echo "Failure job did not store error_message."
  echo "$failure_job"
  exit 1
fi

echo "Failure job failed with error_message=$failure_error"

echo
echo "Scenario 3: duplicate idempotency key returns the same job id"

idempotent_body='{"payload": {"text": "e2e idempotency"}, "idempotency_key": "e2e-smoke-idempotency-key"}'

first_idempotent_response="$(post_job "$idempotent_body")"
second_idempotent_response="$(post_job "$idempotent_body")"

first_id="$(json_value "id" <<< "$first_idempotent_response")"
second_id="$(json_value "id" <<< "$second_idempotent_response")"

assert_equal "$second_id" "$first_id" "duplicate idempotency key should return existing job"

echo "Idempotency check passed. job_id=$first_id"

echo
echo "Scenario 4: list endpoint shows completed jobs"

completed_jobs_response="$(list_jobs "completed")"
json_list_contains_id "$success_id" <<< "$completed_jobs_response"

echo "Completed jobs list contains job_id=$success_id"

echo
echo "Scenario 5: list endpoint shows failed jobs"

failed_jobs_response="$(list_jobs "failed")"
json_list_contains_id "$failure_id" <<< "$failed_jobs_response"

echo "Failed jobs list contains job_id=$failure_id"

echo
echo "Docker e2e smoke test passed."