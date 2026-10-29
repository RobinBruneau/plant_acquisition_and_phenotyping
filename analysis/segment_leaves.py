"""Segment leaves on the cropped views with Grounded-SAM-2 (Grounding DINO boxes -> SAM 2 masks).

Usage (conda env `phenotyping`):
    python segment_leaves.py ACQ_DIR [ACQ_DIR ...]

For every image of ACQ_DIR/image_crop/, writes to ACQ_DIR/image_crop_seg/:
    segmented_<name>.jpg  annotated overlay
    results_<name>.json   boxes, RLE masks and scores, in crop pixel coordinates
Adapted from Grounded-SAM-2/demo_perso.py (same models, prompt and thresholds).
"""
import argparse
import json
import os
import sys
from pathlib import Path

GSAM2_ROOT = Path(os.environ.get("GSAM2_ROOT", Path(__file__).resolve().parent.parent / "third_party" / "Grounded-SAM-2"))
# the Grounded-SAM-2 packages, configs and checkpoints are resolved relative to its repo root
sys.path.insert(0, str(GSAM2_ROOT))

import cv2
import numpy as np
import pycocotools.mask as mask_util
import supervision as sv
import torch
from grounding_dino.groundingdino.util.inference import load_image, load_model, predict
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
from torchvision.ops import box_convert

TEXT_PROMPT = "plant leaf."
SAM2_CHECKPOINT = "./checkpoints/sam2.1_hiera_large.pt"
SAM2_MODEL_CONFIG = "configs/sam2.1/sam2.1_hiera_l.yaml"
GROUNDING_DINO_CONFIG = "grounding_dino/groundingdino/config/GroundingDINO_SwinT_OGC.py"
GROUNDING_DINO_CHECKPOINT = "gdino_checkpoints/groundingdino_swint_ogc.pth"
BOX_THRESHOLD = 0.1
TEXT_THRESHOLD = 0.1
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def single_mask_to_rle(mask):
    rle = mask_util.encode(np.array(mask[:, :, None], order="F", dtype="uint8"))[0]
    rle["counts"] = rle["counts"].decode("utf-8")
    return rle


def save_overlay(img_path, out_path, boxes, masks, confidences):
    """Write the image annotated with masks, boxes and confidence labels."""
    detections = sv.Detections(xyxy=np.asarray(boxes, dtype=float), mask=np.asarray(masks, dtype=bool),
                               class_id=np.arange(len(boxes)))
    annotated = sv.MaskAnnotator().annotate(scene=cv2.imread(str(img_path)), detections=detections)
    annotated = sv.BoxAnnotator().annotate(scene=annotated, detections=detections)
    annotated = sv.LabelAnnotator().annotate(scene=annotated, detections=detections,
                                             labels=[f"Leaf {c:.2f}" for c in confidences])
    cv2.imwrite(str(out_path), annotated)


def segment_image(img_path, out_dir, sam2_predictor, grounding_model):
    """Segment one image; return the number of leaves found (0 if no detection)."""
    image_source, image = load_image(str(img_path))
    sam2_predictor.set_image(image_source)
    boxes, confidences, labels = predict(
        model=grounding_model, image=image, caption=TEXT_PROMPT,
        box_threshold=BOX_THRESHOLD, text_threshold=TEXT_THRESHOLD, device=DEVICE,
    )
    if len(boxes) == 0:
        return 0

    h, w, _ = image_source.shape
    boxes = boxes * torch.Tensor([w, h, w, h])
    input_boxes = box_convert(boxes=boxes, in_fmt="cxcywh", out_fmt="xyxy").numpy()
    with torch.autocast(device_type=DEVICE, dtype=torch.bfloat16):
        masks, scores, _ = sam2_predictor.predict(
            point_coords=None, point_labels=None, box=input_boxes, multimask_output=False,
        )
    if masks.ndim == 4:
        masks = masks.squeeze(1)
    confidences = [float(c) for c in confidences.numpy()]
    scores = [float(s) for s in np.asarray(scores).reshape(len(masks), -1)[:, 0]]

    save_overlay(img_path, out_dir / f"segmented_{img_path.stem}.jpg", input_boxes, masks, confidences)

    results = {
        "image_name": img_path.name,
        "total_leaves_detected": len(masks),
        "annotations": [
            {"class_name": "leaf", "bbox": box.tolist(), "segmentation": single_mask_to_rle(mask),
             "confidence_score": conf, "sam2_score": score}
            for box, mask, conf, score in zip(input_boxes, masks, confidences, scores)
        ],
        "box_format": "xyxy",
        "img_width": w,
        "img_height": h,
    }
    with open(out_dir / f"results_{img_path.stem}.json", "w") as fh:
        json.dump(results, fh, indent=4)
    return len(masks)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acq_dirs", type=Path, nargs="+")
    parser.add_argument("--views", nargs="+", metavar="LABEL", help="only these image stems (default: all)")
    args = parser.parse_args()
    acq_dirs = [d.resolve() for d in args.acq_dirs]

    os.chdir(GSAM2_ROOT)
    if torch.cuda.is_available() and torch.cuda.get_device_properties(0).major >= 8:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    sam2_predictor = SAM2ImagePredictor(build_sam2(SAM2_MODEL_CONFIG, SAM2_CHECKPOINT, device=DEVICE))
    grounding_model = load_model(model_config_path=GROUNDING_DINO_CONFIG,
                                 model_checkpoint_path=GROUNDING_DINO_CHECKPOINT, device=DEVICE)
    print(f"Models loaded on {DEVICE}")

    failed = []
    for acq_dir in acq_dirs:
        out_dir = acq_dir / "image_crop_seg"
        out_dir.mkdir(exist_ok=True)
        image_paths = sorted(p for p in (acq_dir / "image_crop").glob("*.png")
                             if not args.views or p.stem in args.views)
        print(f"== {acq_dir}: {len(image_paths)} images -> {out_dir}")
        for img_path in image_paths:
            # one bad image must not abort a batch of several hundred; failures are listed at the end
            try:
                n = segment_image(img_path, out_dir, sam2_predictor, grounding_model)
                print(f"{'OK  ' if n else 'NONE'}  {img_path.stem}: {n} leaves")
            except Exception as exc:
                failed.append(f"{acq_dir.name}/{img_path.name}: {exc}")
                print(f"FAIL  {img_path.stem}: {exc}")
    print(f"\n{len(failed)} failed images")
    for line in failed:
        print(f"  {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
