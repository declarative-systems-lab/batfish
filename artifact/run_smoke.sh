#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd -P)
RUN_ID="lite-$(date +%Y%m%d-%H%M%S)"
RESULT_DIR="${ROOT_DIR}/artifact/results/smoke/${RUN_ID}"
OUTPUT_ROOT="${RESULT_DIR}/fattree4pol"

if ! config_values=$(python3 "${ROOT_DIR}/artifact/read_config.py" lite); then
    exit 1
fi
read -r PROFILE_THREADS TIMEOUT TIMEOUT_SECONDS <<< "${config_values}"

if [[ -x "${ROOT_DIR}/datas/.venv/bin/python" ]]; then
    PLOT_PYTHON="${ROOT_DIR}/datas/.venv/bin/python"
else
    PLOT_PYTHON=python3
fi
if ! "${PLOT_PYTHON}" -c 'import matplotlib' >/dev/null 2>&1; then
    echo "[!] Missing artifact plotting dependency: Matplotlib." >&2
    echo "[!] Run './install.sh' from the repository root, then retry." >&2
    echo "[!] Python interpreter: ${PLOT_PYTHON}" >&2
    exit 1
fi

mkdir -p "${OUTPUT_ROOT}"
echo "[*] Running the SpecLens smoke evaluation (lite) ..."
run_succeeded=true
if ! SMT_DIRECTORY_PREFIX="${OUTPUT_ROOT}" python3 "${ROOT_DIR}/run_benchmark.py" \
    --all \
    --property 1 \
    --benchmark smoke \
    --threads "${PROFILE_THREADS}" \
    --timeout "${TIMEOUT}" \
    "${ROOT_DIR}/benchmarks/FatTrees/fattree4pol"; then
    run_succeeded=false
    echo "[!] The smoke benchmark failed or reached a workflow timeout." >&2
fi

reports=()
while IFS= read -r report; do
    reports+=("${report}")
done < <(find "${OUTPUT_ROOT}" -name benchmark_time.csv -type f | sort)
if ((${#reports[@]} != 1)); then
    echo "[!] Expected one timing report, found ${#reports[@]}." >&2
    exit 1
fi

SUMMARY_CSV="${RESULT_DIR}/benchmark_summary.csv"
cp "${reports[0]}" "${SUMMARY_CSV}"
if ! "${PLOT_PYTHON}" "${ROOT_DIR}/datas/plot_efficiency.py" \
    --input "${SUMMARY_CSV}" \
    --output-dir "${RESULT_DIR}/figures" \
    --timeout-seconds "${TIMEOUT_SECONDS}" \
    --mode lite; then
    echo "[!] Failed to generate the smoke-test figures." >&2
    echo "[!] Timing data remain available at: ${SUMMARY_CSV}" >&2
    exit 1
fi

if [[ "${run_succeeded}" != true ]]; then
    echo "[!] Inspect the timing CSV and benchmark output for timeout details." >&2
fi
echo "[✓] Timing data: ${SUMMARY_CSV}"
echo "[✓] Figures: ${RESULT_DIR}/figures/efficiency.png and efficiency.pdf"
