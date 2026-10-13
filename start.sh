#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${MEDIA_ROOT:-}" ]]; then
  mkdir -p "$MEDIA_ROOT"

  # Seed the persistent disk with the media assets tracked in the repository.
  # Never overwrite files already on the disk, including user uploads.
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
