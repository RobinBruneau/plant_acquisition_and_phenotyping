"""Reproject mesh vertices onto every calibrated view to check a Metashape reconstruction.

Usage:
    python reproject_check.py MESH CAMERAS_XML IMAGES_DIR OUT_DIR

MESH is the exported OBJ/PLY, CAMERAS_XML the Agisoft XML from "Export Cameras".
One overlay JPEG per aligned camera is written to OUT_DIR (red dots = projected vertices).
No occlusion test is done: vertices hidden behind the plant are drawn too.
"""
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

from mesh_io import load_mesh

_CALIB_KEYS = ("f", "cx", "cy", "k1", "k2", "k3", "k4", "p1", "p2", "b1", "b2")


def _similarity(el):
    """4x4 matrix from a <transform> holding <rotation>/<translation>/<scale> (identity if absent)."""
    m = np.eye(4)
    if el is None:
        return m
    rotation, translation, scale = el.findtext("rotation"), el.findtext("translation"), el.findtext("scale")
    if rotation:
        m[:3, :3] = np.array(rotation.split(), dtype=float).reshape(3, 3)
    if scale:
        m[:3, :3] *= float(scale)
    if translation:
        m[:3, 3] = np.array(translation.split(), dtype=float)
    return m


def load_cameras(xml_path, apply_chunk_transform=True):
    """Parse an Agisoft cameras XML.

    Returns (cameras, unaligned_labels); each camera is a dict with
    'label', 'calib' (intrinsics + width/height) and 'world_to_cam' (4x4).
    """
    chunk = ET.parse(xml_path).getroot().find("chunk")
    sensors = {}
    for s in chunk.iterfind("sensors/sensor"):
        calib_el = s.find("calibration[@class='adjusted']")
        if calib_el is None:
            calib_el = s.find("calibration")
        if calib_el is None:
            continue
        calib = {k: float(calib_el.findtext(k, "0")) for k in _CALIB_KEYS}
        resolution = calib_el.find("resolution")
        calib["width"], calib["height"] = int(resolution.get("width")), int(resolution.get("height"))
        sensors[s.get("id")] = calib

    chunk_t = _similarity(chunk.find("transform"))
    components = {c.get("id"): _similarity(c.find("transform")) for c in chunk.iterfind("components/component")}

    cameras, unaligned = [], []
    for c in chunk.find("cameras").iter("camera"):
        transform = c.findtext("transform")
        if transform is None or c.get("sensor_id") not in sensors:
            unaligned.append(c.get("label"))
            continue
        cam_to_world = np.array(transform.split(), dtype=float).reshape(4, 4)
        if apply_chunk_transform:
            # exported meshes are in the chunk's transformed frame, camera matrices in its internal frame
            cam_to_world = chunk_t @ components.get(c.get("component_id"), np.eye(4)) @ cam_to_world
        cameras.append({"label": c.get("label"), "calib": sensors[c.get("sensor_id")],
                        "world_to_cam": np.linalg.inv(cam_to_world)})
    return cameras, unaligned


def project(points, world_to_cam, calib):
    """Project Nx3 world points with the Metashape frame-camera model.

    Returns (uv Nx2 in pixels, in_front mask); uv is meaningless where in_front is False.
    """
    cam = points @ world_to_cam[:3, :3].T + world_to_cam[:3, 3]
    in_front = cam[:, 2] > 0
    z = np.where(in_front, cam[:, 2], 1.0)
    x, y = cam[:, 0] / z, cam[:, 1] / z
    r2 = x * x + y * y
    radial = 1 + calib["k1"] * r2 + calib["k2"] * r2**2 + calib["k3"] * r2**3 + calib["k4"] * r2**4
    xd = x * radial + calib["p1"] * (r2 + 2 * x * x) + 2 * calib["p2"] * x * y
    yd = y * radial + calib["p2"] * (r2 + 2 * y * y) + 2 * calib["p1"] * x * y
    u = calib["width"] * 0.5 + calib["cx"] + xd * calib["f"] + xd * calib["b1"] + yd * calib["b2"]
    v = calib["height"] * 0.5 + calib["cy"] + yd * calib["f"]
    return np.stack([u, v], axis=1), in_front


def pixel_footprint(points, cameras):
    """Mesh units covered by one image pixel at the depth of the points, median over the cameras.

    Dividing a mesh area by its square gives an area in image pixels, which does not depend on the
    arbitrary scale of the reconstruction nor on the mesh density (all acquisitions share the camera rig).
    """
    return float(np.median([np.median(points @ c["world_to_cam"][2, :3] + c["world_to_cam"][2, 3]) / c["calib"]["f"]
                            for c in cameras]))


def _find_image(images_dir, label):
    for candidate in (images_dir / label, images_dir / (label + ".png")):
        if candidate.is_file():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("cameras_xml", type=Path)
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--n-points", type=int, default=20000, help="random vertices to draw (default: 20000)")
    parser.add_argument("--scale", type=float, default=0.25, help="overlay downscale factor (default: 0.25)")
    parser.add_argument("--views", nargs="+", metavar="LABEL", help="only these camera labels (default: all)")
    parser.add_argument("--internal-frame", action="store_true",
                        help="ignore chunk/component transforms (try this if overlays are off)")
    args = parser.parse_args()

    vertices, _, _ = load_mesh(args.mesh)
    rng = np.random.default_rng(0)
    points = vertices[rng.choice(len(vertices), size=min(args.n_points, len(vertices)), replace=False)]
    cameras, unaligned = load_cameras(args.cameras_xml, apply_chunk_transform=not args.internal_frame)
    if args.views:
        missing = set(args.views) - {cam["label"] for cam in cameras}
        if missing:
            parser.error(f"views not found among aligned cameras: {sorted(missing)}")
        cameras = [cam for cam in cameras if cam["label"] in args.views]
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for cam in cameras:
        image_path = _find_image(args.images_dir, cam["label"])
        if image_path is None:
            print(f"SKIP  {cam['label']}: image not found in {args.images_dir}")
            continue
        image = Image.open(image_path).convert("RGB")
        calib = cam["calib"]
        if image.size != (calib["width"], calib["height"]):
            print(f"SKIP  {cam['label']}: image size {image.size} differs from calibration")
            continue
        uv, in_front = project(points, cam["world_to_cam"], calib)
        inside = in_front & (uv[:, 0] >= 0) & (uv[:, 0] < calib["width"]) & (uv[:, 1] >= 0) & (uv[:, 1] < calib["height"])

        small = image.resize((round(image.width * args.scale), round(image.height * args.scale)))
        overlay = np.array(small)
        px = (uv[inside] * args.scale).astype(int)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                overlay[np.clip(px[:, 1] + dy, 0, overlay.shape[0] - 1),
                        np.clip(px[:, 0] + dx, 0, overlay.shape[1] - 1)] = (255, 0, 0)
        Image.fromarray(overlay).save(args.out_dir / (cam["label"] + ".jpg"), quality=85)
        print(f"OK    {cam['label']}: {inside.sum()}/{len(points)} points in frame")

    print(f"\n{len(cameras)} aligned cameras, {len(unaligned)} not aligned")
    for label in unaligned:
        print(f"  not aligned: {label}")


if __name__ == "__main__":
    main()
