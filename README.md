# SpecLens

SpecLens extracts **localized subspecifications (subspecs)** from network configurations.
Built on Batfish simulation states and Minesweeper verification encodings, it derives
sound localized constraints on individual routers, configuration lines, and fields 
that explain how they preserve a verified network property.

- Project Website: [SpecLens](https://declarative-systems-lab.github.io/SpecLens)
- User Study Interface: [SpecLens User Study](https://declarative-systems-lab.github.io/SpecLens/userstudy)

## User Study and Benchmarks

The [`user study`](user-study) directory contains the easy and hard user study networks.
The [`benchmarks`](benchmarks) directory contains synthetic and real-world benchmark configurations,
including Bics, Columbus, USCarrier, Internet2, FatTrees, and Lines.

Each runnable work directory contains:

- `configs/`: network device configurations.
- `properties.json`: one or more network properties.

---

## Install

Run the installation script from the repository root to set up the environment.
`install.sh` detects the platform, generates `.bazelrc`, and installs the
dependencies below.

```bash
./install.sh
```

Supported platforms:

- **Linux (x86_64)**: Debian/Ubuntu with `apt-get`. Tested on Ubuntu 22.04 and
  Ubuntu 24.04.
- **macOS (arm64)**: Apple Silicon with [Homebrew](https://brew.sh/). The
  script installs Homebrew if it is missing and configures Z3 JNI for Java
  tests.

The script installs:

- OpenJDK 11
- Bazelisk (as `bazel`)
- Z3 4.14.0 and its Java bindings
- Python 3, pip, and Jupyter Notebook
- utilities including `wget`, `unzip`, and `rsync`

On macOS, it also sets `JAVA_HOME` in `~/.zshrc` and `~/.bashrc`.

SpecLens additionally requires Python 3.10 or later at runtime.

---

## Test

Run the user study task1 network through Batfish, Minesweeper, and SpecLens:

```bash
python3 run_benchmarks.py user-study/userstudy_task1
```

The runner uses the standard SubSpec workflow (`--subspec`) by default. Select
one of the following workflow options:

- `--subspec`: runs the standard SubSpec workflow.
- `--noscope`: runs the SubSpec NoScope baseline.
- `--fullsym`: runs the SubSpec FullSym baseline.
- `--all`: runs SubSpec, NoScope, and FullSym in sequence.

SpecLens uses one worker thread and a four-hour timeout by default. Override
these settings with `-t/--threads` and `--timeout`, respectively.

For each property in the SubSpec and NoScope workflows, the runner:

1. computes the simulation state with Batfish;
2. generates the verification encoding with Minesweeper;
3. checks consistency between the simulation state and verification encoding; and
4. computes line-level and field-level subspecifications with SpecLens.

The FullSym workflow instead prepares the global encoding and its SubSpec
baseline before computing line-level and field-level subspecifications.

Generated artifacts are stored under `smts/smt_output_xxxx/`. Final SubSpec,
NoScope, and FullSym results are written to `4_subspec/`, `5_subspec_noscope/`,
and `6_subspec_fullsym/`, respectively. Stage timings and standard SubSpec
counts are written to `benchmark_time.csv`. 
Run `python3 run_benchmarks.py -h` to list all options.

---

## Consistency Check

In the SubSpec and NoScope workflows, SpecLens checks consistency between
the simulation state and verification encoding before computing subspecifications.

For the Internet2 real-world configurations, enable compatibility refinement:

```bash
python3 run_benchmarks.py --internet2 benchmarks/Internet2
```

This option disables external BGP environment inputs in violation checks and
refines inconsistent assume-guarantee constraints using Z3 models.

---

## Repository Layout

- `projects/`: Batfish and Minesweeper source code.
- `speclens/`: SpecLens plugin source code, utilities, and pipeline tools.
- `benchmarks/`: benchmark configurations and properties.
- `user-study/`: user study task configurations and properties.
- `smts/`: generated simulation, encoding, and subspecification outputs.
- `datas/`: user study and benchmarks datas.
- `install.sh`: installs Linux or macOS dependencies, Jupyter Notebook, and
  generates `.bazelrc`.
- `run_benchmarks.py`: runs the selected workflow for every property in a work directory.
