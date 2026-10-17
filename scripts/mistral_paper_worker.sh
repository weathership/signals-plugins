#!/usr/bin/env bash
# Registers signals-preprint-analysis with Mistral so executions show in Studio.
# The SDK lives in its own venv. It is not installed into the Hermes lock:
# mistralai-workflows needs mistralai>=2.9, and Hermes pins mistralai==2.4.8.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${MISTRAL_WORKFLOW_VENV:-${ROOT}/.devenv/mistral-workflow-venv}"
HOME_DIR="${HERMES_HOME:-${HOME}/.hermes}"

if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "DENY: workflow venv missing at ${VENV}" >&2
  echo "  uv venv ${VENV} --python 3.12 && uv pip install --python ${VENV}/bin/python 'mistralai-workflows>=3.15,<4'" >&2
  exit 1
fi

if [[ -z "${MISTRAL_API_KEY:-}" && -f "${HOME_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME_DIR}/.env"
  set +a
fi
if [[ -z "${MISTRAL_API_KEY:-}" ]]; then
  echo "DENY: MISTRAL_API_KEY is unset" >&2
  exit 1
fi

export DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-signals-preprints}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd "${ROOT}"
exec "${VENV}/bin/python" "${ROOT}/scripts/hermes_paper_workflow.py"
