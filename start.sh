#!/usr/bin/env bash
set -euo pipefail

# The repository includes the project's existing media assets. Serve them on
# Render Free even when the optional persistent-disk environment variables
# have not been configured.
export SERVE_MEDIA_FILES=True

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# A Blueprint can provide this path even when the service is still on Free.
# Use the bundled repository media unless /var/data is actually mounted.
if [[ "${MEDIA_ROOT:-}" == /var/data/* ]] && ! mountpoint -q /var/data; then
  export MEDIA_ROOT="$PROJECT_ROOT/media"
fi

if [[ -n "${MEDIA_ROOT:-}" && "$MEDIA_ROOT" != "$PROJECT_ROOT/media" ]]; then
  mkdir -p "$MEDIA_ROOT"

  # Seed the configured media directory with the assets tracked in the repo.
  # Never overwrite files already there, including user uploads.
  cp -rn "$PROJECT_ROOT"/media/. "$MEDIA_ROOT"/
fi

exec python -m gunicorn atrue_core.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers 1 \
  --threads 4 \
  --worker-class gthread \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
