"""Drop oversized detections (whole-plant / whole-image boxes) from the leaf segmentations.

Usage (conda env `phenotyping`):
    python clean_segmentation.py ACQ_DIR [ACQ_DIR ...]

Reads ACQ_DIR/image_crop_seg/results_*.json and writes the filtered JSON and a redrawn overlay
to ACQ_DIR/image_crop_seg_clean/. No model is run.
"""
import argparse
import json
from pathlib import Path

MAX_BOX_AREA_FRACTION = 0.25


def drop_large_boxes(results, max_fraction=MAX_BOX_AREA_FRACTION):
    """Return a copy of a results dict without the boxes larger than max_fraction of the image area."""
    limit = max_fraction * results["img_width"] * results["img_height"]
    kept = [a for a in results["annotations"]
            if (a["bbox"][2] - a["bbox"][0]) * (a["bbox"][3] - a["bbox"][1]) <= limit]
    return {**results, "annotations": kept, "total_leaves_detected": len(kept),
            "max_box_area_fraction": max_fraction}


def main():
    # imported here so that drop_large_boxes stays usable without the Grounded-SAM-2 stack
    import numpy as np
    import pycocotools.mask as mask_util
    from segment_leaves import save_overlay

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acq_dirs", type=Path, nargs="+")
    args = parser.parse_args()
    for acq_dir in args.acq_dirs:
        out_dir = acq_dir / "image_crop_seg_clean"
        out_dir.mkdir(exist_ok=True)
        n_before = n_after = 0
        for json_path in sorted((acq_dir / "image_crop_seg").glob("results_*.json")):
            with open(json_path) as fh:
                results = json.load(fh)
            clean = drop_large_boxes(results)
            n_before += len(results["annotations"])
            n_after += len(clean["annotations"])
            with open(out_dir / json_path.name, "w") as fh:
                json.dump(clean, fh, indent=4)
            annotations = clean["annotations"]
            masks = (np.stack([mask_util.decode(a["segmentation"]) for a in annotations]) if annotations
                     else np.zeros((0, clean["img_height"], clean["img_width"])))
            save_overlay(acq_dir / "image_crop" / clean["image_name"],
                         out_dir / f"segmented_{Path(clean['image_name']).stem}.jpg",
                         np.array([a["bbox"] for a in annotations]).reshape(-1, 4), masks,
                         [a["confidence_score"] for a in annotations])
        print(f"{acq_dir.name}: kept {n_after}/{n_before} detections -> {out_dir}")


if __name__ == "__main__":
    main()
