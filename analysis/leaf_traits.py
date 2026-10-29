"""Leaf and plant traits from the 3D leaf segmentation and the leaf axes, with summary figures.

Usage (conda env `phenotyping`):
    python leaf_traits.py ACQ_DIR [ACQ_DIR ...] [--check-view LABEL]

Each ACQ_DIR must hold mesh_green.ply, cameras.xml, mesh_green_leaves.json and leaf_axes.json.
Each Metashape reconstruction has its own arbitrary scale, but all acquisitions
share the same camera rig: each one is rescaled so that its camera centers match those of the reference
acquisition (--reference, default: the first ACQ_DIR). All lengths and areas are then in the mesh units of the
reference (uncalibrated), so they compare leaves and acquisitions with each other but are not physical sizes. Use the
same --reference for every group that will be compared. Written to OUT_DIR (--out-dir, default: results/ next to the
acquisitions):
    leaf_traits.csv    one row per 3D leaf
    plant_traits.csv   one row per acquisition
    leaf_traits_distributions.png, leaf_length_vs_width.png, leaf_width_profiles.png, plant_traits.png
The petiole/blade limit of a leaf is read on its width profile: the point where the width has risen by a quarter
from its narrowest value near the base to its maximum. With --check-view, the axes drawn over that cropped
view, petiole and blade in two colors, go to OUT_DIR/petiole_blade_<acq>_<label>.jpg.
Figures only show leaves of at least MIN_LEAF_AREA_PX2 (mesh area in image pixels^2, column size_px2, independent of
the mesh density); the CSV keeps them all.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull

from leaf_axes import polyline_length, up_direction
from mesh_io import load_mesh, vertex_areas
from reproject_check import load_cameras, pixel_footprint, project

MIN_LEAF_AREA_PX2 = 9000  # smaller 3D leaves (~500 vertices at Ultra quality) are mostly rosette-heart fragments: kept in the CSV, not plotted
MIN_SECTIONS = 5          # fewer cross-sections than this: widths are reported but flagged unreliable
BLADE_START_RISE = 0.25   # the blade starts where the width has risen by this share from the narrow base to the maximum
MAX_BASE_WIDTH_RATIO = 0.7  # a base wider than this share of the maximal width shows no petiole: no limit reported
UNITS_NOTE = "Mesh units of {} (all acquisitions rescaled to its camera rig), uncalibrated."

SERIES, SERIES_2, MUTED, INK, INK_SOFT, GRID, SURFACE = "#2a78d6", "#eb6834", "#c3c2b7", "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def face_areas(vertices, faces):
    """(area, unit normal) of each triangle."""
    normal = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]])
    area = np.linalg.norm(normal, axis=1) / 2
    return area, normal / np.maximum(2 * area, 1e-15)[:, None]


def camera_centers(xml_path):
    """{camera label: camera center} of an Agisoft cameras XML, in the mesh frame."""
    return {c["label"]: np.linalg.inv(c["world_to_cam"])[:3, 3] for c in load_cameras(xml_path)[0]}


def rig_scale(centers, ref_centers):
    """Scale factor taking `centers` onto `ref_centers` (both {label: point}), best similarity over the shared labels."""
    labels = sorted(set(centers) & set(ref_centers))
    x = np.array([centers[k] for k in labels])
    y = np.array([ref_centers[k] for k in labels])
    x -= x.mean(axis=0)
    y -= y.mean(axis=0)
    s = np.linalg.svd(x.T @ y, compute_uv=False)
    if np.linalg.det(x.T @ y) < 0:  # best rotation, never a reflection
        s[-1] = -s[-1]
    return s.sum() / (x ** 2).sum()


def smooth_widths(widths):
    """Running median of 3 (ends mirrored): one oblique cross-section no longer makes a spike."""
    if len(widths) < 3:
        return widths
    return np.median(np.lib.stride_tricks.sliding_window_view(np.pad(widths, 1, mode="reflect"), 3), axis=1)


def blade_start(positions, widths):
    """Position along the axis (0 = base, 1 = tip) where the leaf goes from narrow to wide; nan if it has no narrow base.

    Between the narrowest cross-section before the widest one and the widest one, this is where the
    smoothed width first crosses BLADE_START_RISE of the way up, interpolated between two cross-sections.
    """
    if len(widths) < MIN_SECTIONS:
        return np.nan
    smooth = smooth_widths(widths)
    widest = smooth.argmax()
    if widest == 0:
        return np.nan
    narrowest = smooth[:widest].argmin()
    if smooth[narrowest] > MAX_BASE_WIDTH_RATIO * smooth[widest]:
        return np.nan
    level = smooth[narrowest] + BLADE_START_RISE * (smooth[widest] - smooth[narrowest])
    k = narrowest + 1 + np.flatnonzero(smooth[narrowest + 1:widest + 1] >= level)[0]
    t = (level - smooth[k - 1]) / (smooth[k] - smooth[k - 1])
    return positions[k - 1] + t * (positions[k] - positions[k - 1])


def leaf_traits(vertices, faces, leaf_mask, leaf, center, up):
    """Traits of one leaf; `leaf` is its entry of leaf_axes.json."""
    axis = np.array(leaf["axis"])
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(axis, axis=0), axis=1))])
    length = arc[-1]
    widths = np.array([s["width"] for s in leaf["cross_sections"]])
    positions = arc[[s["axis_index"] for s in leaf["cross_sections"]]] / max(length, 1e-12)

    area, normal = face_areas(vertices, faces)
    in_leaf = leaf_mask[faces].all(axis=1)
    # the mesh wraps a little around the margins: only the faces turned upward count as leaf surface
    upper = in_leaf & (normal @ up > 0)
    leaf_area = area[upper].sum()


    to_tip = axis[-1] - center
    height = to_tip @ up
    flat = to_tip - height * up
    ref = np.cross(up, [1.0, 0.0, 0.0])  # arbitrary zero of the azimuth, same for all leaves of a plant
    ref /= np.linalg.norm(ref)
    chord = np.linalg.norm(axis[-1] - axis[0])
    smooth = smooth_widths(widths)
    start = blade_start(positions, widths)
    max_width = smooth.max() if len(widths) else np.nan
    return {
        "leaf_id": leaf["id"], "n_vertices": int(leaf_mask.sum()), "n_sections": len(widths),
        "widths_reliable": len(widths) >= MIN_SECTIONS,
        "length": length, "length_from_center": leaf["length_from_center"],
        "max_width": max_width, "mean_width": widths.mean() if len(widths) else np.nan,
        "max_width_position": positions[smooth.argmax()] if len(widths) else np.nan,
        "area": leaf_area, "aspect_ratio": length / max_width,
        "area_fill": leaf_area / (length * max_width),  # 1 = rectangle, about 0.79 = ellipse
        "straightness": chord / max(length, 1e-12),
        "inclination_deg": np.degrees(np.arctan2(height, np.linalg.norm(flat))),
        "azimuth_deg": np.degrees(np.arctan2(flat @ np.cross(up, ref), flat @ ref)) % 360,
        "tip_radius": np.linalg.norm(flat), "tip_height": height,
        "blade_start_position": start, "petiole_length_from_width": start * length,
    }, positions, widths


def acquisition_traits(acq_dir, reference_dir):
    """Return (leaf rows, plant row, width profiles [(positions, widths)] in leaf order) for one acquisition.

    Lengths are rescaled to the camera rig of the acquisition in `reference_dir`.
    """
    vertices, _, faces = load_mesh(acq_dir / "mesh_green.ply")
    with open(acq_dir / "mesh_green_leaves.json") as fh:
        labels = np.array(json.load(fh)["vertex_leaf_id"])
    with open(acq_dir / "leaf_axes.json") as fh:
        axes = json.load(fh)
    centers = camera_centers(acq_dir / "cameras.xml")
    size = vertex_areas(vertices, faces) / pixel_footprint(vertices, load_cameras(acq_dir / "cameras.xml")[0]) ** 2
    up = up_direction(vertices, np.array(list(centers.values())))
    scale = rig_scale(centers, camera_centers(reference_dir / "cameras.xml"))
    # rescale every length read from the mesh or the axes; areas follow as scale**2
    vertices = vertices * scale
    center = np.array(axes["center"]) * scale
    for leaf in axes["leaves"]:
        leaf["axis"] = (np.array(leaf["axis"]) * scale).tolist()
        leaf["length_from_center"] *= scale
        for section in leaf["cross_sections"]:
            section["width"] *= scale

    rows, profiles = [], []
    for leaf in axes["leaves"]:
        row, positions, widths = leaf_traits(vertices, faces, labels == leaf["id"], leaf, center, up)
        rows.append({"acquisition": acq_dir.name, **row, "size_px2": size[labels == leaf["id"]].sum()})
        profiles.append((positions, widths))

    area, normal = face_areas(vertices, faces)
    upward = normal @ up > 0
    rel = vertices - center
    height = rel @ up
    flat = rel - np.outer(height, up)
    e1 = flat[np.linalg.norm(flat, axis=1).argmax()]
    e1 /= np.linalg.norm(e1)
    hull_area = ConvexHull(np.c_[flat @ e1, flat @ np.cross(up, e1)]).volume  # .volume of a 2D hull is its area
    big = [r for r in rows if r["size_px2"] >= MIN_LEAF_AREA_PX2]
    plant = {
        "acquisition": acq_dir.name, "rig_reference": str(reference_dir), "rig_scale": scale, "n_leaves": len(rows), "n_large_leaves": len(big),
        "green_area": area[upward].sum(), "leaf_area_total": sum(r["area"] for r in rows),
        "labeled_area_fraction": sum(r["area"] for r in rows) / area[upward].sum(),
        "rosette_diameter": 2 * max(r["tip_radius"] for r in rows),
        "hull_area": hull_area, "green_area_per_hull_area": area[upward].sum() / hull_area,
        "height": np.percentile(height, 99) - np.percentile(height, 1),
        "longest_leaf": max(r["length"] for r in rows),
        "median_length": np.median([r["length"] for r in big]),
        "median_max_width": np.nanmedian([r["max_width"] for r in big]),
        "median_inclination_deg": np.median([r["inclination_deg"] for r in big]),
    }
    return rows, plant, profiles


def write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: f"{v:.5g}" if isinstance(v, float) else v for k, v in row.items()})


def style(ax, title):
    ax.set_title(title, fontsize=10, color=INK, loc="left")
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK_SOFT, labelsize=8, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)


def save_figures(rows, plants, profiles, out_dir, units_note):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [p["acquisition"] for p in plants]
    short = [n.replace("acq_", "") for n in names]
    shown = [r["size_px2"] >= MIN_LEAF_AREA_PX2 for r in rows]
    big = [r for r, keep in zip(rows, shown) if keep]
    note = f"Leaves of at least {MIN_LEAF_AREA_PX2} px2 of mesh. {units_note}"

    # all acquisitions pooled: one histogram per trait, line = median
    panels = [("length", "Leaf length"), ("max_width", "Maximal width"), ("area", "Leaf area (upper surface)"),
              ("aspect_ratio", "Length / maximal width"), ("inclination_deg", "Tip inclination above the rosette plane (deg)"),
              ("max_width_position", "Position of the maximal width (0 = base, 1 = tip)")]
    fig, axs = plt.subplots(2, 3, figsize=(13, 7), facecolor=SURFACE)
    for ax, (key, title) in zip(axs.ravel(), panels):
        values = np.array([r[key] for r in big], dtype=float)
        values = values[np.isfinite(values)]
        ax.hist(values, bins=20, color=SERIES, edgecolor=SURFACE, linewidth=1.5)
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        median = np.median(values)
        ax.axvline(median, color=INK, linewidth=2)
        ax.annotate(f"median {median:.3g}", (median, 1), xycoords=("data", "axes fraction"), xytext=(4, -10),
                    textcoords="offset points", fontsize=8, color=INK_SOFT)
        style(ax, title)
    fig.supylabel("Number of leaves", fontsize=9, color=INK_SOFT)
    fig.suptitle(f"Leaf trait distributions, {len(names)} acquisitions pooled ({len(big)} leaves)", x=0.01, ha="left",
                 fontsize=13, color=INK)
    fig.text(0.01, 0.01, note, fontsize=8, color=INK_SOFT)
    fig.tight_layout(rect=(0.01, 0.03, 1, 0.96))
    fig.savefig(out_dir / "leaf_traits_distributions.png", dpi=150)

    cols = min(3, len(names))
    grid = (-(-len(names) // cols), cols)
    fig, axs = plt.subplots(*grid, figsize=(4.3 * cols, 3.6 * grid[0]), facecolor=SURFACE, sharex=True, sharey=True, squeeze=False)
    for ax, name in zip(axs.ravel(), names):
        ax.scatter([r["length"] for r in big], [r["max_width"] for r in big], s=14, color=MUTED, linewidths=0)
        mine = [r for r in big if r["acquisition"] == name]
        ax.scatter([r["length"] for r in mine], [r["max_width"] for r in mine], s=30, color=SERIES, edgecolors=SURFACE, linewidths=0.8)
        style(ax, name)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
    fig.supxlabel("Leaf length", y=0.04, fontsize=9, color=INK_SOFT)
    fig.supylabel("Maximal width", fontsize=9, color=INK_SOFT)
    fig.suptitle("Leaf length against maximal width (grey: the other acquisitions)", x=0.01, ha="left", fontsize=13, color=INK)
    fig.text(0.01, 0.005, note, fontsize=8, color=INK_SOFT)
    fig.tight_layout(rect=(0.01, 0.07, 1, 0.95))
    fig.savefig(out_dir / "leaf_length_vs_width.png", dpi=150)

    fig, axs = plt.subplots(*grid, figsize=(4.3 * cols, 3.6 * grid[0]), facecolor=SURFACE, sharex=True, sharey=True, squeeze=False)
    for ax, name in zip(axs.ravel(), names):
        for row, keep, (positions, widths) in zip(rows, shown, profiles):
            if keep and row["acquisition"] == name and row["widths_reliable"]:
                ax.plot(positions, widths, color=SERIES, linewidth=1.2, alpha=0.6)
                if np.isfinite(row["blade_start_position"]):
                    ax.scatter(row["blade_start_position"], np.interp(row["blade_start_position"], positions, widths),
                               s=28, color=SERIES_2, edgecolors=SURFACE, linewidths=0.8, zorder=3)
        style(ax, name)
    fig.supxlabel("Position along the leaf axis (0 = base, 1 = tip)", y=0.04, fontsize=9, color=INK_SOFT)
    fig.supylabel("Width", fontsize=9, color=INK_SOFT)
    fig.suptitle("Width profile of each leaf (orange dot: petiole/blade limit)", x=0.01, ha="left", fontsize=13, color=INK)
    fig.text(0.01, 0.005, note + f" Leaves with at least {MIN_SECTIONS} cross-sections.", fontsize=8, color=INK_SOFT)
    fig.tight_layout(rect=(0.01, 0.07, 1, 0.95))
    fig.savefig(out_dir / "leaf_width_profiles.png", dpi=150)

    panels = [("n_large_leaves", f"Leaves of at least {MIN_LEAF_AREA_PX2} px2 of mesh"), ("leaf_area_total", "Total labeled leaf area"),
              ("rosette_diameter", "Rosette diameter (2 x farthest tip)"), ("hull_area", "Convex hull area in the rosette plane"),
              ("median_length", "Median leaf length"), ("height", "Rosette height (1st to 99th percentile)")]
    fig, axs = plt.subplots(2, 3, figsize=(13, 6.5), facecolor=SURFACE)
    for ax, (key, title) in zip(axs.ravel(), panels):
        values = [p[key] for p in plants]
        bars = ax.bar(range(len(names)), values, width=0.6, color=SERIES)
        ax.bar_label(bars, labels=[f"{v:.3g}" for v in values], fontsize=8, color=INK_SOFT, padding=2)
        ax.set_xticks(range(len(names)), short)
        style(ax, title)
    fig.suptitle("Plant traits per acquisition", x=0.01, ha="left", fontsize=13, color=INK)
    fig.text(0.01, 0.01, units_note, fontsize=8, color=INK_SOFT)
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    fig.savefig(out_dir / "plant_traits.png", dpi=150)


def save_check_view(acq_dir, view, rows, out_path):
    """Draw each leaf axis over one cropped view: petiole in orange, blade in blue, white dot at the limit."""
    import cv2  # only needed for this optional figure

    cam = next(c for c in load_cameras(acq_dir / "cameras.xml")[0] if c["label"] == view)
    with open(acq_dir / "image_crop" / "crops.json") as fh:
        x0, y0 = json.load(fh)["crops"][view + ".png"][:2]
    image = cv2.imread(str(acq_dir / "image_crop" / (view + ".png")))
    with open(acq_dir / "leaf_axes.json") as fh:
        leaves = json.load(fh)["leaves"]

    def to_px(points):
        return np.round(project(np.atleast_2d(points), cam["world_to_cam"], cam["calib"])[0] - (x0, y0)).astype(np.int32)

    for leaf, row in zip(leaves, rows):
        axis = np.array(leaf["axis"])
        if row["size_px2"] < MIN_LEAF_AREA_PX2:
            continue
        if not np.isfinite(row["blade_start_position"]):
            cv2.polylines(image, [to_px(axis)], False, (200, 200, 200), 2)  # no limit found
            continue
        arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(axis, axis=0), axis=1))])
        cut = row["blade_start_position"] * arc[-1]
        limit = np.array([np.interp(cut, arc, axis[:, k]) for k in range(3)])
        cv2.polylines(image, [to_px(np.vstack([axis[arc < cut], limit]))], False, (52, 104, 235), 4)
        cv2.polylines(image, [to_px(np.vstack([limit, axis[arc > cut]]))], False, (214, 120, 42), 4)
        cv2.circle(image, tuple(map(int, to_px(limit)[0])), 7, (255, 255, 255), -1)
    cv2.imwrite(str(out_path), image)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acq_dirs", type=Path, nargs="+")
    parser.add_argument("--check-view", metavar="LABEL", help="camera label to draw the petiole/blade limits on, e.g. top_009")
    parser.add_argument("--reference", type=Path, help="acquisition whose camera rig sets the units (default: the first ACQ_DIR)")
    parser.add_argument("--out-dir", type=Path, help="output folder (default: results/ next to the acquisitions)")
    args = parser.parse_args()
    reference_dir = (args.reference or args.acq_dirs[0]).resolve()
    if not (reference_dir / "cameras.xml").is_file():
        parser.error(f"no cameras.xml in the reference acquisition {reference_dir}")
    out_dir = args.out_dir or args.acq_dirs[0].resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, plants, profiles = [], [], []
    for acq_dir in args.acq_dirs:
        acq_rows, plant, acq_profiles = acquisition_traits(acq_dir, reference_dir)
        rows += acq_rows
        plants.append(plant)
        profiles += acq_profiles
        if args.check_view:
            save_check_view(acq_dir, args.check_view, acq_rows, out_dir / f"petiole_blade_{acq_dir.name}_{args.check_view}.jpg")
        print(f"{acq_dir.name}: {plant['n_leaves']} leaves ({plant['n_large_leaves']} of at least {MIN_LEAF_AREA_PX2} px2)")
    write_csv(out_dir / "leaf_traits.csv", rows)
    write_csv(out_dir / "plant_traits.csv", plants)
    save_figures(rows, plants, profiles, out_dir, UNITS_NOTE.format(reference_dir.name))
    print(f"-> {out_dir}/leaf_traits.csv, plant_traits.csv and 4 figures")


if __name__ == "__main__":
    main()
