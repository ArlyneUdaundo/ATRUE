#!/usr/bin/env bash
set -euo pipefail

# The repository includes any tracked media assets; serve them locally when
# Supabase Storage has not yet been configured.
export SERVE_MEDIA_FILES=True

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use the bundled repository media if a stale Blueprint setting points to an
# unavailable Render disk. Supabase is the permanent user-upload store.
if [[ "${MEDIA_ROOT:-}" == /var/data/* ]] && ! mountpoint -q /var/data; then
  export MEDIA_ROOT="$PROJECT_ROOT/media"
fi

if [[ -n "${SUPABASE_URL:-}" && -n "${SUPABASE_S3_ENDPOINT:-}" && \
      -n "${SUPABASE_S3_ACCESS_KEY_ID:-}" && \
      -n "${SUPABASE_S3_SECRET_ACCESS_KEY:-}" && \
      -n "${SUPABASE_STORAGE_REGION:-}" && \
      -n "${SUPABASE_STORAGE_BUCKET:-}" && \
      -n "${SUPABASE_PRIVATE_BUCKET:-}" ]]; then
  echo "User upload storage: Supabase Storage"
elif mountpoint -q /var/data; then
  echo "User upload storage: persistent Render disk at ${MEDIA_ROOT:-$PROJECT_ROOT/media}"
else
  echo "User upload storage: local ephemeral fallback at ${MEDIA_ROOT:-$PROJECT_ROOT/media}; configure Supabase Storage to retain uploads across restarts/deploys"
fi

if [[ -n "${MEDIA_ROOT:-}" && "$MEDIA_ROOT" != "$PROJECT_ROOT/media" ]]; then
  mkdir -p "$MEDIA_ROOT"

  # Seed the configured media directory with the assets tracked in the repo.
  # Never overwrite files already there, including user uploads.
  cp -rn "$PROJECT_ROOT"/media/. "$MEDIA_ROOT"/
fi

# Keep one worker to bound memory on small Render instances. Threads allow
# more requests to wait on database and storage I/O without blocking the worker.
GUNICORN_WORKERS="${GUNICORN_WORKERS:-${WEB_CONCURRENCY:-1}}"
GUNICORN_THREADS="${GUNICORN_THREADS:-8}"

exec python -m gunicorn atrue_core.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers "$GUNICORN_WORKERS" \
  --threads "$GUNICORN_THREADS" \
  --worker-class gthread \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
