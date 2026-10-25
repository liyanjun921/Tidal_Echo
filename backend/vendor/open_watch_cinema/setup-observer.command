#!/bin/bash
set -u
cd "$(dirname "$0")"

printf '\n========================================\n'
printf ' Open Watch Cinema · Observer setup\n'
printf '========================================\n\n'

if ! command -v python3 >/dev/null 2>&1; then
  printf 'Python 3 was not found. Install Python 3, then run this file again.\n\n'
  read -r -p 'Press Return to close...'
  exit 1
fi

if [ ! -x "observer/.venv/bin/python" ]; then
  printf 'Creating observer/.venv...\n'
  python3 -m venv observer/.venv || {
    printf '\nCould not create the virtual environment.\n'
    read -r -p 'Press Return to close...'
    exit 1
  }
fi

PYTHON="observer/.venv/bin/python"
printf 'Installing the optional headless OpenCV observer...\n'
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r observer/requirements.txt
INSTALL_CODE=$?

if [ "$INSTALL_CODE" -eq 0 ]; then
  printf '\nObserver health:\n'
  "$PYTHON" observer/worker.py health
else
  printf '\nObserver installation failed with exit code %s.\n' "$INSTALL_CODE"
fi

printf '\n'
read -r -p 'Press Return to close...'
exit "$INSTALL_CODE"
