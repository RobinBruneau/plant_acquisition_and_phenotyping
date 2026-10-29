"""3D reconstruction of acquisitions with Metashape Professional (Python scripting needs the Pro edition).

Usage (Metashape's own Python):
    metashape.sh -platform offscreen -r reconstruct.py ACQ_DIR [ACQ_DIR ...] [--align-downscale 0] [--depth-downscale 1]

For each ACQ_DIR, the views of image/ are aligned (one camera sensor per view prefix, e.g. side_ / top_, as
the rig has one physical camera each), depth maps are built and meshed with vertex colors, and the result is
exported next to image/:
    mesh.ply      binary PLY with per-vertex colors, no texture (input of filter_green.py)
    cameras.xml   Agisoft cameras XML (input of every projection step)
    metashape/project.psx  the Metashape project, to inspect the reconstruction in the GUI
An acquisition that already has cameras.xml is skipped: an existing export is never overwritten.
Defaults are the settings last used in the GUI: alignment "Highest" (downscale 0), depth maps "Ultra"
(downscale 1), mild filtering, high face count.
"""
import argparse
import sys
from pathlib import Path

import Metashape


def reconstruct(acq_dir, align_downscale, depth_downscale):
    """Reconstruct one acquisition; return the labels of the cameras that did not align."""
    photos = sorted(str(p) for p in (acq_dir / "image").glob("*.png"))
    if not photos:
        raise RuntimeError(f"no PNG in {acq_dir / 'image'}")
    project = acq_dir / "metashape" / "project.psx"
    project.parent.mkdir(exist_ok=True)
    doc = Metashape.Document()
    doc.save(str(project))
    chunk = doc.addChunk()
    chunk.addPhotos(photos)

    # one sensor (intrinsics) per physical camera, recognized by the label prefix
    sensors = {}
    for camera in chunk.cameras:
        prefix = camera.label.rsplit("_", 1)[0]
        if prefix not in sensors:
            sensors[prefix] = chunk.addSensor(camera.sensor)
            sensors[prefix].label = prefix
        camera.sensor = sensors[prefix]
    for sensor in list(chunk.sensors):
        if sensor not in sensors.values():
            chunk.remove([sensor])

    chunk.matchPhotos(downscale=align_downscale, generic_preselection=True, reference_preselection=False,
                      keypoint_limit=40000, tiepoint_limit=4000)
    chunk.alignCameras()
    doc.save()
    chunk.buildDepthMaps(downscale=depth_downscale, filter_mode=Metashape.MildFiltering)
    chunk.buildModel(source_data=Metashape.DepthMapsData, surface_type=Metashape.Arbitrary,
                     interpolation=Metashape.EnabledInterpolation, face_count=Metashape.HighFaceCount,
                     vertex_colors=True, build_texture=False)
    doc.save()
    chunk.exportModel(str(acq_dir / "mesh.ply"), binary=True, format=Metashape.ModelFormatPLY, save_texture=False,
                      save_uv=False, save_normals=False, save_colors=True, save_confidence=False,
                      save_cameras=False, save_markers=False, save_comment=False)
    # written last: run_group.py takes cameras.xml as the sign of a finished reconstruction
    chunk.exportCameras(str(acq_dir / "cameras.xml"), format=Metashape.CamerasFormatXML)
    return [c.label for c in chunk.cameras if c.transform is None]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acq_dirs", type=Path, nargs="+")
    parser.add_argument("--align-downscale", type=int, default=0, help="0 Highest, 1 High, 2 Medium (default: 0)")
    parser.add_argument("--depth-downscale", type=int, default=1, help="1 Ultra, 2 High, 4 Medium (default: 1)")
    args = parser.parse_args()
    if not Metashape.License().valid:
        sys.exit("no valid Metashape Professional license")

    failed = []
    for acq_dir in [d.resolve() for d in args.acq_dirs]:
        if (acq_dir / "cameras.xml").exists():
            print(f"SKIP  {acq_dir.name}: cameras.xml already exists", flush=True)
            continue
        print(f"== {acq_dir.name}", flush=True)
        # one failed acquisition must not abort a whole group; failures are listed at the end
        try:
            unaligned = reconstruct(acq_dir, args.align_downscale, args.depth_downscale)
            print(f"OK    {acq_dir.name}: {len(unaligned)} cameras not aligned {unaligned}", flush=True)
        except Exception as exc:
            failed.append(acq_dir.name)
            print(f"FAIL  {acq_dir.name}: {exc}", flush=True)
    if failed:
        print(f"FAILED: {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
