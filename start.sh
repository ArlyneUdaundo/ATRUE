#!/usr/bin/env bash
set -euo pipefail

# The repository includes the project's existing media assets. Serve them on
# Render Free even when the optional persistent-disk environment variables
# have not been configured.
export SERVE_MEDIA_FILES="${SERVE_MEDIA_FILES:-True}"

if [[ -n "${MEDIA_ROOT:-}" ]]; then
  mkdir -p "$MEDIA_ROOT"

  # Seed the configured media directory with the assets tracked in the repo.
  # Never overwrite files already there, including user uploads.
  cp -rn media/. "$MEDIA_ROOT"/
fi

exec python -m gunicorn atrue_core.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers 1 \
  --threads 4 \
  --worker-class gthread \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
