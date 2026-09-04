#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd -P)
EXPERIMENT="${1:?missing scalability experiment}"
MODE="${2:-fast}"

case "${MODE}" in
    fast|full) ;;
    *)
        echo "[!] Usage: $0 {routers|prefixes|threads} {fast|full}" >&2
        exit 2
        ;;
esac

if ! config_values=$(python3 "${ROOT_DIR}/artifact/read_config.py" "${MODE}"); then
    exit 1
fi
read -r PROFILE_THREADS TIMEOUT TIMEOUT_SECONDS <<< "${config_values}"

case "${EXPERIMENT}" in
    routers)
        BENCHMARK="fattrees"
        VALUES=(4 12 16 20 24 32)
        PATHS=(
            benchmarks/FatTrees/fattree4pol
            benchmarks/FatTrees/fattree12pol
            benchmarks/FatTrees/fattree16pol
            benchmarks/FatTrees/fattree20pol
            benchmarks/FatTrees/fattree24pol
            benchmarks/FatTrees/fattree32pol
        )
        ;;
    prefixes)
        BENCHMARK="lines"
        VALUES=(10 100 1000 2000 5000 10000)
        PATHS=(
            benchmarks/Lines/line10
            benchmarks/Lines/line100
            benchmarks/Lines/line1000
            benchmarks/Lines/line2000
            benchmarks/Lines/line5000
            benchmarks/Lines/line10000
        )
        ;;
    threads)
        BENCHMARK="threads"
        VALUES=(1 4 8 12 16 20)
        PATHS=(
            benchmarks/FatTrees/fattree24pol
            benchmarks/FatTrees/fattree24pol
            benchmarks/FatTrees/fattree24pol
            benchmarks/FatTrees/fattree24pol
            benchmarks/FatTrees/fattree24pol
            benchmarks/FatTrees/fattree24pol
        )
        ;;
    *)
        echo "[!] Unknown scalability experiment: ${EXPERIMENT}" >&2
        exit 2
        ;;
esac

if [[ -x "${ROOT_DIR}/datas/.venv/bin/python" ]]; then
    PLOT_PYTHON="${ROOT_DIR}/datas/.venv/bin/python"
else
    PLOT_PYTHON=python3
fi
if ! "${PLOT_PYTHON}" -c 'import matplotlib, numpy' >/dev/null 2>&1; then
    echo "[!] Missing artifact plotting dependencies: NumPy or Matplotlib." >&2
    echo "[!] Run './install.sh' from the repository root, then retry." >&2
    echo "[!] Python interpreter: ${PLOT_PYTHON}" >&2
    exit 1
fi

RUN_ID="${MODE}-$(date +%Y%m%d-%H%M%S)"
RESULT_DIR="${ROOT_DIR}/artifact/results/scalability/${EXPERIMENT}-${RUN_ID}"
SUMMARY_CSV="${RESULT_DIR}/benchmark_summary.csv"
mkdir -p "${RESULT_DIR}"

failures=()
report_count=0
for index in "${!VALUES[@]}"; do
    value="${VALUES[index]}"
    if [[ "${EXPERIMENT}" == "threads" ]]; then
        threads="${value}"
    else
        threads="${PROFILE_THREADS}"
    fi
    work_directory="${ROOT_DIR}/${PATHS[index]}"
    point_output_dir="${RESULT_DIR}/point-${value}"
    mkdir -p "${point_output_dir}"

    case "${EXPERIMENT}" in
        routers) printf -v case_name 'smt_output_fattree%02dpol' "${value}" ;;
        prefixes) printf -v case_name 'smt_output_line%05d' "${value}" ;;
        threads) printf -v case_name 'smt_output_fattree24pol_thread%02d' "${value}" ;;
    esac

    echo "[*] Running ${EXPERIMENT} scalability point ${value} (${threads} threads, ${MODE}) ..."
    command=(
        python3 "${ROOT_DIR}/run_benchmark.py"
        --all
        --property 1
        --benchmark "${BENCHMARK}"
        --threads "${threads}"
        --timeout "${TIMEOUT}"
        "${work_directory}"
    )
    if ! SMT_DIRECTORY_PREFIX="${point_output_dir}" "${command[@]}"; then
        failures+=("${value}")
        echo "[!] Point ${value} failed or reached a workflow timeout; continuing." >&2
    fi

    reports=()
    while IFS= read -r report; do
        reports+=("${report}")
    done < <(find "${point_output_dir}" -name benchmark_time.csv -type f | sort)
    if ((${#reports[@]} != 1)); then
        echo "[!] Expected one timing report for point ${value}, found ${#reports[@]}." >&2
        continue
    fi
    if ((report_count == 0)); then
        head -n 1 "${reports[0]}" > "${SUMMARY_CSV}"
    fi
    awk -F, -v OFS=, -v benchmark="${BENCHMARK}" -v case_name="${case_name}" \
        'NR == 2 { $1 = benchmark; $2 = case_name; print }' \
        "${reports[0]}" >> "${SUMMARY_CSV}"
    ((report_count += 1))
done

if ((report_count == 0)); then
    echo "[!] No scalability timing reports were generated." >&2
    exit 1
fi

if ! "${PLOT_PYTHON}" "${ROOT_DIR}/datas/plot_scalability.py" \
    --input "${SUMMARY_CSV}" \
    --dataset "${BENCHMARK}" \
    --timeout-seconds "${TIMEOUT_SECONDS}" \
    --mode "${MODE}" \
    --output-dir "${RESULT_DIR}/figures"; then
    echo "[!] Failed to generate the ${EXPERIMENT} scalability figures." >&2
    echo "[!] Timing data remain available at: ${SUMMARY_CSV}" >&2
    exit 1
fi

if ((${#failures[@]} > 0)); then
    echo "[!] Some points failed or timed out: ${failures[*]}" >&2
fi
echo "[✓] Timing data: ${SUMMARY_CSV}"
echo "[✓] Figures: ${RESULT_DIR}/figures/fig-scalability-${BENCHMARK}.png and .pdf"
