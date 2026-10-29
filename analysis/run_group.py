"""Run the analysis pipeline on every acquisition of a group (study) folder.

Usage (any Python 3, no dependency; each step runs in the conda env --env):
    python run_group.py GROUP_DIR [--metashape METASHAPE_SH] [--reference ACQ_DIR] [--dry-run]

GROUP_DIR holds one folder per acquisition (any subfolder with an image/ folder). With --metashape (path of
metashape.sh of Metashape Professional, default: $METASHAPE), the acquisitions without cameras.xml are first
reconstructed by reconstruct.py. Without it, mesh.obj (or mesh.ply) and cameras.xml must have been exported
from Metashape by hand. Acquisitions without them are listed and skipped. A step is skipped for an acquisition
whose output already exists, so the command can be re-run after adding acquisitions; delete an output to redo it.
Steps:
    reconstruct           mesh.ply, cameras.xml   (Metashape Pro, long)
    filter_green          mesh -> mesh_green.ply
    crop_images           image_crop/
    segment_leaves        image_crop_seg/         (Grounded-SAM-2, GPU)
    clean_segmentation    image_crop_seg_clean/
    segment_leaves_3d     mesh_green_leaves.*
    leaf_axes             leaf_axes.*
    leaf_traits           GROUP_DIR/results/leaf_traits.csv, plant_traits.csv and figures (always re-run)
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# (script, output marking the step done in ACQ_DIR)
# shortcut: a step interrupted mid-way leaves its output folder, which then counts as done; delete it to redo
STEPS = [
    ("crop_images.py", "image_crop/crops.json"),
    ("segment_leaves.py", "image_crop_seg"),
    ("clean_segmentation.py", "image_crop_seg_clean"),
    ("segment_leaves_3d.py", "mesh_green_leaves.json"),
    ("leaf_axes.py", "leaf_axes.json"),
]


def find_mesh(acq_dir):
    return next((acq_dir / n for n in ("mesh.ply", "mesh.obj") if (acq_dir / n).is_file()), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("group_dir", type=Path)
    parser.add_argument("--env", default="phenotyping", help="conda env of the steps (default: phenotyping)")
    parser.add_argument("--metashape", type=Path, default=os.environ.get("METASHAPE"),
                        help="metashape.sh of Metashape Pro, to reconstruct the acquisitions without cameras.xml")
    parser.add_argument("--align-downscale", type=int, default=0, help="reconstruction: 0 Highest, 1 High, 2 Medium (default: 0)")
    parser.add_argument("--depth-downscale", type=int, default=1, help="reconstruction: 1 Ultra, 2 High, 4 Medium (default: 1)")
    parser.add_argument("--out-dir", type=Path, help="group results folder (default: GROUP_DIR/results)")
    parser.add_argument("--reference", type=Path,
                        help="acquisition whose camera rig sets the units; use the same one for all compared groups "
                             "(default: the first acquisition of the group)")
    parser.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    args = parser.parse_args()

    group = args.group_dir.resolve()
    acqs = sorted(d for d in group.iterdir() if (d / "image").is_dir())
    if not acqs:
        parser.error(f"no acquisition (subfolder with image/) in {group}")
    to_reconstruct = [d for d in acqs if not (d / "cameras.xml").exists()]
    if args.metashape and to_reconstruct:
        cmd = [str(args.metashape), "-platform", "offscreen", "-r", str(HERE / "reconstruct.py"), *map(str, to_reconstruct),
               "--align-downscale", str(args.align_downscale), "--depth-downscale", str(args.depth_downscale)]
        print("$ " + " ".join(cmd), flush=True)
        if not args.dry_run:
            subprocess.run(cmd)  # failed acquisitions have no cameras.xml and are listed below; the others go on
    ready = [d for d in acqs if find_mesh(d) and (d / "cameras.xml").is_file()]
    for d in acqs:
        if d not in ready:
            print(f"WAIT  {d.name}: no mesh.obj/mesh.ply + cameras.xml (reconstruction missing or failed)")
    if not ready:
        return 1
    out_dir = (args.out_dir or group / "results").resolve()

    def run(script, extra):
        cmd = ["conda", "run", "--no-capture-output", "-n", args.env,
               "python", str(HERE / script), *map(str, extra)]
        print("$ " + " ".join(cmd), flush=True)
        if not args.dry_run and subprocess.run(cmd).returncode:
            sys.exit(f"step {script} failed, stopping")

    for d in ready:
        if not (d / "mesh_green.ply").exists():
            run("filter_green.py", [find_mesh(d), d / "mesh_green.ply"])
    for script, output in STEPS:
        todo = [d for d in ready if not (d / output).exists()]
        if script == "leaf_axes.py" and todo:
            todo = ready  # its side-ratio figure pools all acquisitions
            run(script, [*todo, "--out-dir", out_dir])
        elif todo:
            run(script, todo)
    reference = ["--reference", args.reference.resolve()] if args.reference else []
    run("leaf_traits.py", [*ready, "--out-dir", out_dir, *reference])
    print(f"done: {len(ready)}/{len(acqs)} acquisitions -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
