#!/usr/bin/env bash
# Regenerate the DeepTutor code knowledge graph (one command).
# Requires `graphifyy` installed in the python you point at it:
#   pip install graphifyy
#   PY=/path/to/venv/bin/python ./regenerate_graph.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO"

PY="${PYTHON:-python}"
exec "$PY" scripts/codegraph/regenerate.py "$@"
