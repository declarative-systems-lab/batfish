#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd -P)
MODE="${1:-fast}"
RUN_ID="${MODE}-$(date +%Y%m%d-%H%M%S)"
RESULT_DIR="${ROOT_DIR}/artifact/results/efficiency/${RUN_ID}"

case "${MODE}" in
    lite)
        PROPERTY_ARGUMENTS=(--property 1)
        ;;
    fast)
        PROPERTY_ARGUMENTS=(--property 1)
        ;;
    full)
        PROPERTY_ARGUMENTS=()
        ;;
    *)
        echo "Usage: $0 [lite|fast|full]" >&2
        echo "  lite: run property 1 using the 10-minute profile" >&2
        echo "  fast: run property 1 using the fast profile" >&2
        echo "  full:  run all 10 properties with a 4-hour timeout each" >&2
        exit 2
        ;;
esac

if ! config_values=$(python3 "${ROOT_DIR}/artifact/read_config.py" "${MODE}"); then
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

mkdir -p "${RESULT_DIR}"

BENCHMARK_NAMES=(Bics Columbus USCarrier Internet2)
BENCHMARK_IDS=(bics columbus uscarrier internet2)
BENCHMARK_PATHS=(
    "benchmarks/Internet2"
    "benchmarks/Bics/bgp"
    "benchmarks/Columbus/bgp"
    "benchmarks/USCarrier/bgp"
)

failures=()
for index in "${!BENCHMARK_NAMES[@]}"; do
    name="${BENCHMARK_NAMES[index]}"
    benchmark_id="${BENCHMARK_IDS[index]}"
    path="${BENCHMARK_PATHS[index]}"
    benchmark_output_dir="${RESULT_DIR}/${benchmark_id}"
    mkdir -p "${benchmark_output_dir}"
    command=(
        python3
        "${ROOT_DIR}/run_benchmark.py"
        --all
        --benchmark "${benchmark_id}"
        --threads "${PROFILE_THREADS}"
        --timeout "${TIMEOUT}"
        "${PROPERTY_ARGUMENTS[@]}"
    )
    if [[ "${name}" == "Internet2" ]]; then
        command+=(--internet2)
    fi
    command+=("${ROOT_DIR}/${path}")

    echo "[*] Running ${name} efficiency evaluation (${MODE}) ..."
    if ! SMT_DIRECTORY_PREFIX="${benchmark_output_dir}" "${command[@]}"; then
        failures+=("${name}")
        echo "[!] ${name} failed or reached its timeout; continuing." >&2
    fi
done

reports=()
while IFS= read -r report; do
    reports+=("${report}")
done < <(find "${RESULT_DIR}" -name benchmark_time.csv -type f | sort)
if ((${#reports[@]} == 0)); then
    echo "[!] No benchmark timing reports were generated." >&2
    exit 1
fi

SUMMARY_CSV="${RESULT_DIR}/benchmark_summary.csv"
awk 'FNR == 1 && NR != 1 { next } { print }' "${reports[@]}" > "${SUMMARY_CSV}"

if ! "${PLOT_PYTHON}" "${ROOT_DIR}/datas/plot_efficiency.py" \
    --input "${SUMMARY_CSV}" \
    --output-dir "${RESULT_DIR}/figures" \
    --timeout-seconds "${TIMEOUT_SECONDS}" \
    --mode "${MODE}"; then
    echo "[!] Failed to generate the efficiency figures." >&2
    echo "[!] Timing data remain available at: ${SUMMARY_CSV}" >&2
    exit 1
fi

if ((${#failures[@]} > 0)); then
    echo "[!] Some runs failed or timed out: ${failures[*]}" >&2
fi
echo "[✓] Timing data: ${SUMMARY_CSV}"
echo "[✓] Figures: ${RESULT_DIR}/figures/efficiency.png and efficiency.pdf"
