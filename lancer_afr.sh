#!/bin/sh
# Lance l'interface AFR sous Linux / macOS.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "Python introuvable : installer Python 3.9 ou plus recent."
    exit 1
fi

"$PYTHON" run_afr.py "$@"
