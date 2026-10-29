# Plant acquisition and phenotyping

Multi-view acquisition and 3D phenotyping of Arabidopsis rosettes: a GUI drives the acquisition,
Metashape reconstructs each plant, and the analysis turns every reconstruction into leaf and plant
traits, then compares groups of plants.

```
acquisition/   acquisition GUI (acquisition_manger.py) and its web page / test bridge server
analysis/      analysis pipeline (one script per step) and group comparison
envs/          install script of the conda env
third_party/   Grounded-SAM-2 (git submodule, pinned)
```

## Install

```bash
git clone --recursive https://github.com/RobinBruneau/plant_acquisition_and_phenotyping.git
cd plant_acquisition_and_phenotyping
bash envs/install.sh        # conda env `phenotyping` + Grounded-SAM-2 weights (~1.4 GB)
```

Needs conda, an NVIDIA GPU and a CUDA 12.8 toolkit (`nvcc`, `CUDA_HOME`). Set
`TORCH_CUDA_ARCH_LIST` for a GPU other than an RTX 40xx (default `8.9`).

## Data layout

All acquisitions of one group (study condition, e.g. healthy plants) sit in one folder:

```
GROUP_DIR/
  acq_000/
    image/side_NNN.png, top_NNN.png   input views, NNN = angle / 10 (read-only)
    mesh.ply (or mesh.obj)            Metashape mesh with vertex colors (not a texture)
    cameras.xml                       Metashape "Export Cameras" (Agisoft XML)
  acq_001/ ...
```

## 3D reconstruction

With Metashape **Professional** (Python scripting is not available in the Standard edition),
`analysis/reconstruct.py` reconstructs every acquisition that has no `cameras.xml` yet: one camera
sensor per view prefix (`side_`, `top_`), alignment "Highest", depth maps "Ultra", mild filtering,
mesh with vertex colors, export of `mesh.ply`, `cameras.xml` and the project `metashape/project.psx`.
It runs inside `run_group.py` when Metashape is given:

```bash
export METASHAPE=/path/to/metashape-pro/metashape.sh   # or --metashape
```

Keep the default quality: the 3D leaf segmentation is tuned on such fine meshes. Without Metashape Pro,
reconstruct in the GUI and export `mesh.obj` (vertex colors) and `cameras.xml` into each acquisition folder.

## Analyse a group

```bash
python analysis/run_group.py GROUP_DIR
```

Each step runs in the `phenotyping` env (`--env` to use another one), only on the acquisitions that
have a reconstruction and lack that step's output, so the command can be re-run as acquisitions are added.

| Step | Writes in `acq_*/` |
|---|---|
| `reconstruct.py` Metashape Pro, if `--metashape`/`$METASHAPE` | `mesh.ply`, `cameras.xml`, `metashape/` |
| `filter_green.py` keeps the green part of the mesh | `mesh_green.ply` |
| `crop_images.py` crops the views around the plant | `image_crop/` |
| `segment_leaves.py` 2D leaf masks, Grounded-SAM-2 (GPU) | `image_crop_seg/` |
| `clean_segmentation.py` drops whole-plant detections | `image_crop_seg_clean/` |
| `segment_leaves_3d.py` lifts the masks to 3D leaves | `mesh_green_leaves.ply/json` |
| `leaf_axes.py` leaf axes and cross-sections | `leaf_axes.ply/json` |
| `leaf_traits.py` traits of the group | `GROUP_DIR/results/` |

`GROUP_DIR/results/` holds `leaf_traits.csv` (one row per leaf), `plant_traits.csv` (one row per
plant) and summary figures. Every script also runs alone, see its `--help`.

**Units.** Each reconstruction has an arbitrary scale. All acquisitions are rescaled to the camera rig
of one reference acquisition (`--reference`, default: the first of the group), so sizes compare
between plants but are uncalibrated mesh units, not millimetres. **Groups that will be compared must
use the same `--reference`.**

## Compare groups

```bash
python analysis/compare_groups.py GROUP_A GROUP_B [GROUP_C ...] --out-dir comparison/
```

The statistical unit is the plant (leaf traits are first reduced to their median per plant).
Each trait is tested with Mann-Whitney U (2 groups) or Kruskal-Wallis (more), and p-values are adjusted
over all traits with Benjamini-Hochberg (q). Writes `plant_table.csv`, `group_comparison.csv` (sorted
by p) and `group_comparison.png`. A warning is raised if the groups use different rig references.

## Tests

```bash
conda activate phenotyping && cd analysis && pytest test_tools.py
```
