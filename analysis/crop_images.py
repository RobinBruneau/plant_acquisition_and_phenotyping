"""Crop every calibrated view around the leaves, using the reprojected green mesh.

Usage:
    python crop_images.py ACQ_DIR [ACQ_DIR ...]

Each ACQ_DIR must hold image/, cameras.xml and mesh_green.ply. Crops are written to
ACQ_DIR/image_crop/ under the original file names, with the boxes in image_crop/crops.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from mesh_io import load_mesh
from reproject_check import _find_image, load_cameras, project

MARGIN_PX = 10


def crop_box(uv, width, height, margin=MARGIN_PX):
    """Bounding box (x0, y0, x1, y1) of Nx2 pixel points plus margin, clipped to the image.

    x1/y1 are exclusive. Returns None if the box does not intersect the image.
    """
    if len(uv) == 0:
        return None
    x0, y0 = np.floor(uv.min(axis=0)).astype(int) - margin
    x1, y1 = np.floor(uv.max(axis=0)).astype(int) + 1 + margin
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, width), min(y1, height)
    if x0 >= x1 or y0 >= y1:
        return None
    return int(x0), int(y0), int(x1), int(y1)


def crop_acquisition(acq_dir, views=None):
    """Crop the views of one acquisition (all aligned cameras, or only the labels in `views`)."""
    vertices, _, _ = load_mesh(acq_dir / "mesh_green.ply")
    cameras, unaligned = load_cameras(acq_dir / "cameras.xml")
    out_dir = acq_dir / "image_crop"
    out_dir.mkdir(exist_ok=True)

    crops = {}
    for cam in cameras:
        label, calib = cam["label"], cam["calib"]
        if views and label not in views:
            continue
        image_path = _find_image(acq_dir / "image", label)
        if image_path is None:
            print(f"SKIP  {label}: image not found")
            continue
        image = Image.open(image_path)
        if image.size != (calib["width"], calib["height"]):
            print(f"SKIP  {label}: image size {image.size} differs from calibration")
            continue
        uv, in_front = project(vertices, cam["world_to_cam"], calib)
        box = crop_box(uv[in_front], calib["width"], calib["height"])
        if box is None:
            print(f"SKIP  {label}: mesh projects outside the image")
            continue
        image.crop(box).save(out_dir / image_path.name)
        crops[image_path.name] = box
        print(f"OK    {label}: box {box}")

    for label in unaligned:
        print(f"SKIP  {label}: camera not aligned")
    with open(out_dir / "crops.json", "w") as fh:
        json.dump({"margin_px": MARGIN_PX,
                   "box_format": "[x0, y0, x1, y1] in original image pixels, x1/y1 exclusive",
                   "crops": crops}, fh, indent=1)
    return crops


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acq_dirs", type=Path, nargs="+")
    args = parser.parse_args()
    for acq_dir in args.acq_dirs:
        print(f"== {acq_dir}")
        crops = crop_acquisition(acq_dir)
        print(f"{len(crops)} crops written to {acq_dir / 'image_crop'}")


if __name__ == "__main__":
    main()
