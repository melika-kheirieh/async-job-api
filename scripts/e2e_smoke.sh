#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"

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

  for attempt in {1..30}; do
    if curl -sf "$BASE_URL/docs" > /dev/null; then
      echo "API is ready."
      return 0
    fi

    sleep 1
  done

  echo "API did not become ready."
  compose logs api --tail=100
  exit 1
}

extract_json_field() {
  local field_name="$1"

  python -c "
import json
import sys

data = json.load(sys.stdin)
print(data['$field_name'])
"
}

create_job() {
  curl -sSf -X POST "$BASE_URL/jobs" \
    -H "Content-Type: application/json" \
    -d '{"payload": {"text": "e2e smoke test"}}'
}

get_job() {
  local job_id="$1"

  curl -sSf "$BASE_URL/jobs/$job_id"
}

echo "Starting clean Docker Compose stack..."
compose down -v
compose up -d --build postgres redis api worker

echo "Applying Alembic migrations..."
compose run --rm api alembic upgrade head

wait_for_api

echo "Creating a successful job..."
create_response="$(create_job)"
job_id="$(extract_json_field "id" <<< "$create_response")"

echo "Created job_id=$job_id"
echo "Polling job status..."

for attempt in {1..30}; do
  job_response="$(get_job "$job_id")"
  status="$(extract_json_field "status" <<< "$job_response")"

  echo "Attempt $attempt: status=$status"

  if [ "$status" = "completed" ]; then
    echo "E2E smoke test passed."
    exit 0
  fi

  if [ "$status" = "failed" ]; then
    echo "Job failed unexpectedly."
    echo "$job_response"
    compose logs worker --tail=100
    exit 1
  fi

  sleep 1
done

echo "Job did not complete in time."
get_job "$job_id" || true
compose logs worker --tail=100
exit 1