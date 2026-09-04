# Data Analysis Notebook

`evaluation.ipynb` prepares the evaluation data and generates the user-study,
efficiency, and scalability figures.

The notebook must be run with `datas/` as the current working directory. It
imports the local `utils` package and reads data from the following directories:

- `1_userstudy/`
- `2_efficiency/`
- `3_scalability/`

Generated figures are written below `figs/`.

For automated reproduction with the `lite`, `fast`, and `full` profiles, see
the [artifact evaluation guide](../artifact/README.md).

## Run locally with JupyterLab

Jupyter is an optional analysis dependency and is not installed by the main
`install.sh` script. Create an isolated Python environment when you need to run
the notebook:

```bash
cd datas
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install jupyterlab ipykernel pandas numpy matplotlib
python -m jupyter lab evaluation.ipynb
```

JupyterLab will open the notebook in a browser. Select the `.venv` Python kernel
if prompted.

## Run from an editor

Editors with notebook support can run `evaluation.ipynb` without starting JupyterLab
manually. Create the virtual environment above, open the repository in the
editor, and select `datas/.venv/bin/python` as the notebook kernel.

## Run in a hosted notebook

The notebook can also run in a hosted environment such as Google Colab without
installing Jupyter locally. Upload or clone the complete repository, install any
missing Python packages, and change the working directory to `datas/` before
running the cells. Uploading only `evaluation.ipynb` is not sufficient because it
depends on the local `utils` package and data directories.

Opening the notebook as a static file in a browser allows inspection of its
cells, but executing them still requires a Python kernel, either locally or in
a hosted environment.
