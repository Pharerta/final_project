#!/usr/bin/env bash
set -euo pipefail

# Перехід у директорію скрипта (без абсолютних шляхів)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# Використовуємо .venv, якщо створено через setup.sh; інакше системний Python 3.11+
PY_CMD=""
if [ -x ".venv/bin/python" ]; then
    PY_CMD=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
    PY_CMD=".venv/Scripts/python.exe"
else
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c "import sys; assert sys.version_info >= (3, 11)" >/dev/null 2>&1; then
                PY_CMD="$candidate"
                break
            fi
        fi
    done
fi

if [ -z "$PY_CMD" ]; then
    echo "[ПОМИЛКА] Python 3.11+ не знайдено. Запустіть ./setup.sh або встановіть Python 3.11+." >&2
    exit 1
fi

case "${1:-}" in
    demo)
        shift
        exec "$PY_CMD" -X utf8 src/demo.py "$@"
        ;;
    test|tests)
        shift
        exec "$PY_CMD" -m pytest "$@"
        ;;
    *)
        exec "$PY_CMD" -X utf8 src/main.py "$@"
        ;;
esac
