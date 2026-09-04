# SpecLens Artifact Evaluation

This directory contains the scripts used to reproduce the efficiency and
scalability results. Each script runs the selected experiments, collects the
timing CSV files, and generates PNG and PDF figures.

## Reference Environment

The paper results were collected on the following machine:

- CPU: Intel(R) Core(TM) i9-10900X CPU at 3.70 GHz
- Memory: 256 GB DDR4 at 3200 MT/s
- Operating system: Ubuntu 22.04.5 LTS (`x86_64`)
- Python: 3.10.12
- OpenJDK: 11.0.32
- Bazel: 4.0.0
- Z3: 4.14.0

Runtime can vary across machines. The functional results and overall trends
should remain consistent.

## Setup

Run all commands from the repository root as a normal user. Do not run the
complete installer with `sudo`.

```bash
./install.sh
```

Run a small benchmark to confirm the installation:

```bash
python3 run_benchmark.py benchmarks/FatTrees/fattree4pol
```

This smoke test uses the standard runner defaults. The reproduction scripts
below use the thread count and timeout selected in `artifact/config.json`.

The installer also installs NumPy and Matplotlib, which the artifact scripts
use to generate figures. Jupyter and pandas remain optional dependencies for
the analysis notebook and are documented separately.

The installer and supported operating systems are documented in the main
[`README.md`](../README.md). Notebook-based analysis is documented in
[`datas/README.md`](../datas/README.md).

### User Study

The user study cannot be rerun automatically because it requires human
participants. The artifact provides the anonymized measurements under
[`datas/1_userstudy/`](../datas/1_userstudy/). Evaluators can use
[`datas/evaluation.ipynb`](../datas/evaluation.ipynb) to inspect the data and
regenerate the user-study figures; no user recruitment or data collection is
required.

## Reproduction Profiles

The profiles are defined in `artifact/config.json`:

- `lite`: 20 device threads and a 10-minute timeout for each workflow
- `fast`: 20 device threads and a 30-minute timeout for each workflow
- `full`: 20 device threads and a four-hour timeout for each workflow

The `lite` profile is available for the smoke and efficiency runners. The
scalability runners accept `fast` or `full`.

The router and prefix scalability experiments use the configured thread count.
The thread scalability experiment instead evaluates 1, 4, 8, 12, 16, and 20
threads. Its timeout still comes from the selected profile.

## Smoke Test

Run one `fattree4pol` property through all three workflows with the `lite`
profile, then generate a timing CSV and figures:

```bash
./artifact/run_smoke.sh
```

This is the recommended evaluator sanity check. It exercises Batfish,
Minesweeper, SpecLens, timing collection, and plotting without running the full
evaluation matrix. Each workflow is limited to 10 minutes.

The same `lite` timeout can be applied to property 1 of all four efficiency
benchmarks with:

```bash
./artifact/run_efficiency.sh lite
```

## Fast Reproduction

The fast profile runs one property for each efficiency benchmark and applies a
30-minute workflow timeout to all experiments:

```bash
./artifact/run_efficiency.sh fast
./artifact/run_scalability_routers.sh fast
./artifact/run_scalability_prefixes.sh fast
./artifact/run_scalability_threads.sh fast
```

Estimated times on the reference machine, derived from the bundled CSV data:

- Efficiency: approximately 2 hours 41 minutes
- Router scalability: approximately 3 hours 46 minutes
- Prefix scalability: approximately 4 hours 56 minutes
- Thread scalability: approximately 5 hours 40 minutes
- Complete fast reproduction: approximately 17 hours

The commands are independent and may be run separately or concurrently when
sufficient CPU and memory are available. Concurrent execution changes timing
measurements and is not recommended when comparing against the paper results.

## Full Reproduction

The full profile runs all ten properties for each efficiency benchmark and
uses the paper's four-hour workflow timeout:

```bash
./artifact/run_efficiency.sh full
./artifact/run_scalability_routers.sh full
./artifact/run_scalability_prefixes.sh full
./artifact/run_scalability_threads.sh full
```

Estimated times on the reference machine:

- Efficiency: approximately 7 days
- Router scalability: approximately 21 hours 16 minutes
- Prefix scalability: approximately 21 hours 39 minutes
- Thread scalability: approximately 27 hours 30 minutes
- Complete full reproduction: approximately 10 days

These are sequential wall-clock estimates, not CPU time. Timeout-heavy results
make the estimates upper-bound oriented.

## Experiments

### Efficiency

`run_efficiency.sh` evaluates Bics, Columbus, USCarrier, and Internet2 with the
SubSpec, NoScope, and FullSym workflows.

- `fast`: property 1 from each benchmark
- `lite`: property 1 from each benchmark with a 10-minute workflow timeout
- `full`: all ten properties from each benchmark
- Figure: `efficiency.png` and `efficiency.pdf`

### Router Scalability

`run_scalability_routers.sh` evaluates:

- `fattree4pol`
- `fattree12pol`
- `fattree16pol`
- `fattree20pol`
- `fattree24pol`
- `fattree32pol`

Figure: `fig-scalability-fattrees.png` and
`fig-scalability-fattrees.pdf`.

### Prefix Scalability

`run_scalability_prefixes.sh` evaluates:

- `line10`
- `line100`
- `line1000`
- `line2000`
- `line5000`
- `line10000`

Figure: `fig-scalability-lines.png` and `fig-scalability-lines.pdf`.

### Thread Scalability

`run_scalability_threads.sh` evaluates `fattree24pol` with 1, 4, 8, 12, 16,
and 20 parallel threads.

Figure: `fig-scalability-threads.png` and
`fig-scalability-threads.pdf`.

## Outputs

Each run uses a timestamped directory and does not overwrite bundled results:

```text
artifact/results/efficiency/<profile>-<timestamp>/
artifact/results/scalability/<experiment>-<profile>-<timestamp>/
artifact/results/smoke/lite-<timestamp>/
```

Each result directory contains:

- Per-property intermediate outputs under benchmark or experiment-point
  subdirectories
- `benchmark_summary.csv`: combined timing data used for plotting
- `figures/*.png`: raster figures for inspection
- `figures/*.pdf`: vector figures for publication

Bundled paper data are stored in:

- `datas/2_efficiency/benchmark_summary.csv`
- `datas/3_scalability/benchmark_summary.csv`

## Timing Semantics

`step1.0` is the sum of:

- Batfish dataplane simulation time
- Minesweeper `Encoder.initConfigurationConstants()` time

The remaining Minesweeper symbolic-encoding time is not recorded as a separate
component because it is effectively represented by the router-local slice
encoding time (`step1.2`). The sum of the reported stages therefore closely
approximates the end-to-end runtime without counting the same work twice.

SubSpec, NoScope, and FullSym each have an independent deadline. A workflow's
line (`-l`) and field (`-f`) stages share that deadline, so a timeout is counted
once for the workflow.

After one workflow times out, the runner continues with the next selected
workflow. After one benchmark or scalability point fails, the artifact script
continues with the remaining points and reports the failure at the end.

## Data Analysis

The optional notebook in `datas/evaluation.ipynb` regenerates figures from the
bundled CSV files. Setup and usage are described in
[`datas/README.md`](../datas/README.md).
