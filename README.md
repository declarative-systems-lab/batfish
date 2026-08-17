# SpecLens

SpecLens extracts **localized subspecifications (subspecs)** from network configurations.
Built on Batfish simulation states and Minesweeper verification encodings, it derives
sound localized constraints on individual routers, configuration lines, and fields 
that explain how they preserve a verified network property.

- Project website: [SpecLens](https://declarative-systems-lab.github.io/SpecLens)
- User study: [SpecLens User Study](https://declarative-systems-lab.github.io/SpecLens/userstudy)

## User Study and Benchmarks

The [`user-study`](user-study) directory contains the easy and hard user-study networks.
The [`benchmarks`](benchmarks) directory contains synthetic and real-world benchmark configurations,
including Bics, Columbus, USCarrier, Internet2, FatTrees, and Lines.

Each runnable work directory contains:

- `configs/`: network device configurations.
- `properties.json`: one or more network properties.

## Workflows

The top-level runner supports three subspecification workflows:

- `--subspec`: runs the SubSpec pipeline.
- `--noscope`: runs the SubSpec NoScope baseline pipeline.
- `--fullsym`: runs the SubSpec FullSym baseline pipeline.

---

## Install

Run the following installation script to set up the environment.
The installation script has been tested on Ubuntu 22.04 and Ubuntu 24.04.

```bash
./install.sh
```

SpecLens requires:

- Python 3.10 or later.
- OpenJDK 11.
- Bazelisk/Bazel.
- Z3 and its Java bindings.
- Standard utilities including `wget`, `unzip`, and `rsync`.

---

## Test

Run the user-study task1 network through the Batfish, Minesweeper, and SpecLens.
The subspecifications are stored in directory `smts/smt_output_xxxx/4_subspec/`.
Use `python3 run_benchmarks.py -h` to list more options.

```bash
python3 run_benchmarks.py --subspec user-study/userstudy_task1
```

For every network, the command:

1. computes the simulation state with Batfish;
2. generates the verification encoding with Minesweeper;
3. checks consistency between the simulation state and verification encoding; and
4. computes line-level and field-level subspecifications with SpecLens.

---

## Consistency Check

Before computing subspecifications, SpecLens checks consistency between
the simulation state and verification encoding.

For the Internet2 real-world configurations, enable compatibility refinement:

```bash
python3 run_benchmarks.py --subspec --internet2 benchmarks/Internet2
```

This option disables external BGP environment inputs in violation checks and
refines inconsistent assume-guarantee constraints using Z3 models.

---

## Repository Layout

- `projects/`: Batfish and Minesweeper source code.
- `speclens/`: SpecLens plugin source code, utilities, and pipeline tools.
- `benchmarks/`: benchmark configurations and properties.
- `user-study/`: user-study configurations and properties.
- `smts/`: generated simulation, encoding, and subspecification outputs.
- `install.sh`: installs the Linux dependencies and generates `.bazelrc`.
- `run_benchmarks.py`: runs the selected workflow for every property in a work directory.
