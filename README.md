# SpecLens

SpecLens extracts localized subspecifications from network configurations. It
combines Batfish simulation states with Minesweeper verification encodings to
explain how routers, configuration lines, and fields preserve a network
property.

- [Project Website](https://declarative-systems-lab.github.io/SpecLens)
- [User Study Interface](https://declarative-systems-lab.github.io/SpecLens/userstudy)

## Quick Start

From the repository root:

```bash
./install.sh
python3 run_benchmark.py benchmarks/FatTrees/fattree4pol
```

### Installation

Supported platforms:

- Ubuntu 22.04 and Ubuntu 24.04 (`x86_64`)
- macOS 13.7.2 or later on Apple Silicon (`arm64`)

Other Debian/Ubuntu-based Linux distributions may work if they provide
`apt-get` and glibc 2.35 or newer, but they have not been tested.

The installer configures `.bazelrc` and installs OpenJDK 11, Bazelisk, Python 3,
and the Z3 native libraries. On macOS, Homebrew is installed automatically if
needed. Run the script as a normal user; it requests elevated access only when
required.

### Benchmark

A work directory must be below `benchmarks/` or `user-study/` and contain:

- `configs/`: network device configurations
- `properties.json`: one or more verification properties

Each property creates a numbered output directory under `smts/smt_output_xxxx/`. 
The directory contains:

- `4_subspec/`: localized subspecifications (field-level and line-level)
- `benchmark_time.csv`: runtime and #subspec data

## Workflows

The runner processes every property in the selected work directory. Available
workflows are:

- `--subspec`: standard SubSpec workflow and the default (output: `4_subspec/`)
- `--noscope`: NoScope baseline (output: `5_subspec_noscope/`)
- `--fullsym`: FullSym baseline (output: `6_subspec_fullsym/`)
- `--all`: run SubSpec, NoScope, and FullSym

### Options

- `--threads N`: maximum concurrent device tasks (default: `1`)
- `--timeout DURATION`: timeout for each property's SpecLens workflow (default:
  `4h`); accepts seconds or a compact duration such as `30m`, `2s`, or `4h30m2s`
- `--internet2`: enable compatibility refinement for Internet2 SubSpec or
  NoScope runs
- `--help`, `-h`: show all command-line options and exit

Example:

```bash
python3 run_benchmark.py --threads 4 --timeout 2h benchmarks/FatTrees/fattree4pol
```

Internet2 example:

```bash
python3 run_benchmark.py --internet2 benchmarks/Internet2
```

## User Study

User-study configurations and properties are stored in `user-study/`. 
Run a task with community subspecification enabled:

```bash
python3 run_benchmark.py --community user-study/userstudy_task1
```

See the [user study instructions](user-study/README.md) and the
[online user study interface](https://declarative-systems-lab.github.io/SpecLens/userstudy).

## Data Analysis

The optional analysis notebook and its isolated Python setup are documented in
the [data analysis instructions](datas/README.md).
Jupyter is not installed by `install.sh`.

## Repository Layout

- `projects/`: Batfish and Minesweeper source code
- `speclens/`: SpecLens implementation and pipeline tools
- `benchmarks/`: benchmark configurations and properties
- `user-study/`: user study configurations and properties
- `datas/`: evaluation data and analysis notebook
- `smts/`: generated outputs
- `install.sh`: Linux and macOS environment setup
- `run_benchmark.py`: benchmark pipeline entry point
