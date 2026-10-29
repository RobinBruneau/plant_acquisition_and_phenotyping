"""Trace one axis per 3D leaf, from the rosette center to the leaf tip.

Usage (conda env `phenotyping`):
    python leaf_axes.py ACQ_DIR [ACQ_DIR ...] [--check-view LABEL]

Each ACQ_DIR must hold mesh_green.ply and mesh_green_leaves.json (from segment_leaves_3d.py).
The rosette center is the point closest to the long axes of the large leaves, lowered onto the underside
of the mesh right below it (the straight axes of arched leaves cross above the plant). For each leaf, the
base is its vertex nearest to the center, the tip its vertex farthest from the base along the mesh,
and the axis joins the centroids of slices cut across the leaf between base and tip. At each inner
axis point a cross-section is traced perpendicular to the axis, from margin to margin; implausible
ones (at a kink of the axis, or zigzagging) are dropped. A lopsided one (one side of the axis more than
SECTION_MAX_SIDE_RATIO times the other) has its long side cut back to the length of the short one when the
short one is about as wide as the half-widths of the balanced sections around it; otherwise it is dropped.
Written next to the mesh:
    leaf_axes.json  center, and per leaf the axis polyline, tip, lengths and cross-sections with their
                    widths (mesh units, uncalibrated)
    leaf_axes.ply   point cloud of the axes and cross-sections colored like mesh_green_leaves.ply (center in white)
Written to OUT_DIR (--out-dir, default: results/ next to the acquisitions): section_side_ratios.png, distribution of
the side ratio of all cross-sections, all acquisitions pooled. With --check-view, the axes drawn over that cropped view
go to OUT_DIR/leaf_axes_<acq>_<label>.jpg.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

from mesh_io import load_mesh, save_ply, vertex_areas
from reproject_check import load_cameras, pixel_footprint, project
from segment_leaves_3d import leaf_colors

CENTER_MIN_LEAF_AREA_PX2 = 9000  # only leaves of at least this mesh area in image pixels^2 (~500 vertices at Ultra quality) vote for the center
CENTER_COLUMN_RADIUS = 0.05     # the center drops onto the mesh within this fraction of the rosette radius
CENTER_COLUMN_PERCENTILE = 5    # height percentile of that column of vertices taken as the center height
LINK_RADIUS_EDGES = 2.5         # extra graph links between vertices closer than this many median edge lengths
SECTION_SLICE_SPAN = 1.5        # a cross-section only uses vertices within this many slices of its axis point
SECTION_HALF_THICKNESS_EDGES = 1.5  # a cross-section uses vertices within this many median edge lengths of its plane
SECTION_BINS = 9                # points per cross-section, plus the two margin points
SECTION_MIN_POINTS = 10
SECTION_MAX_SIDE_RATIO = 2.1    # a cross-section is lopsided past this side ratio: Tukey fence of the 6 acquisitions, see section_side_ratios.png
SECTION_MIN_SHORT_SIDE = 0.5    # a lopsided section is cut back if its short side is this share of the neighbouring half-widths, else dropped
SECTION_MAX_AXIS_KINK_DEG = 45  # a cross-section is dropped if the axis turns by more than this at its point (its direction is then unreliable),
SECTION_MAX_TORTUOSITY = 1.5    # or if it is this many times longer than the straight line between its ends (zigzag)
N_SLICES = 15                   # slices of along-mesh distance per leaf, one axis point each
PLY_POINTS_PER_CURVE = 200


def up_direction(vertices, camera_positions):
    """Unit normal of the best-fit plane of the rosette, pointing to the side the cameras are on."""
    centroid = vertices.mean(axis=0)
    normal = np.linalg.svd(vertices - centroid, full_matrices=False)[2][2]
    return normal if (camera_positions.mean(axis=0) - centroid) @ normal > 0 else -normal


def rosette_center(vertices, labels, up=None, size=None, min_size=CENTER_MIN_LEAF_AREA_PX2):
    """Least-squares point closest to the principal axis line of every large leaf.

    A leaf is large when the sum of `size` over its vertices (default: its vertex count) reaches min_size.

    With `up`, the point is then moved along it onto the underside of the mesh in the column around it.
    """
    a, b = np.zeros((3, 3)), np.zeros(3)
    for leaf in range(labels.max() + 1):
        pts = vertices[labels == leaf]
        if (len(pts) if size is None else size[labels == leaf].sum()) < min_size:
            continue
        centroid = pts.mean(axis=0)
        direction = np.linalg.svd(pts - centroid, full_matrices=False)[2][0]
        off_axis = np.eye(3) - np.outer(direction, direction)  # projector onto the plane normal to the axis
        a += off_axis
        b += off_axis @ centroid
    center = np.linalg.solve(a, b)
    if up is None:
        return center
    rel = vertices - center
    height = rel @ up
    radius = np.linalg.norm(rel - np.outer(height, up), axis=1)
    column = radius < CENTER_COLUMN_RADIUS * np.percentile(radius, 95)
    if not column.any():
        return center
    return center + np.percentile(height[column], CENTER_COLUMN_PERCENTILE) * up


def leaf_axis(vertices, faces, leaf_mask, center, n_slices=N_SLICES):
    """Return (polyline Kx3 from base side to tip, tip vertex index, cross-sections, side ratios) for one leaf.

    Works on the largest connected piece of the leaf. The polyline ends exactly on the tip vertex.
    cross-sections: one dict per kept inner axis point, see cross_section(); "trimmed" if its long side was cut back.
    side ratios: long side / short side of every plausible cross-section, kept or not, before any cut.
    """
    idx = np.flatnonzero(leaf_mask)
    local = np.full(len(vertices), -1)
    local[idx] = np.arange(len(idx))
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = local[edges[leaf_mask[edges].all(axis=1)]]
    pts = vertices[idx]
    # also link vertices closer than a few edge lengths: joins the upper and lower skins of the leaf, so
    # that the farthest vertex is the tip and not a point reached by wrapping around the leaf margin
    edge_length = np.median(np.linalg.norm(pts[edges[:, 0]] - pts[edges[:, 1]], axis=1))
    radius = LINK_RADIUS_EDGES * edge_length
    edges = np.concatenate([edges, cKDTree(pts).query_pairs(radius, output_type="ndarray")])
    edges = np.unique(np.sort(edges, axis=1), axis=0)  # coo_matrix would sum the weights of repeated edges
    weights = np.linalg.norm(pts[edges[:, 0]] - pts[edges[:, 1]], axis=1)
    graph = sparse.coo_matrix((weights, (edges[:, 0], edges[:, 1])), shape=(len(idx),) * 2).tocsr()
    piece = connected_components(graph, directed=False)[1]
    main = np.flatnonzero(piece == np.bincount(piece).argmax())
    pts, graph = pts[main], graph[main][:, main]

    base = np.linalg.norm(pts - center, axis=1).argmin()
    from_base = dijkstra(graph, directed=False, indices=base)
    from_tip = dijkstra(graph, directed=False, indices=from_base.argmax())
    # 0 at the base, 1 at the far end; slices of equal position cut the leaf across, whereas slices of
    # distance from the base alone are arcs that end in one corner of the tip
    position = from_base / np.maximum(from_base + from_tip, 1e-12)
    slice_id = np.minimum((position * n_slices).astype(int), n_slices - 1)
    slices = [s for s in range(n_slices) if (slice_id == s).any()]
    polyline = np.array([pts[slice_id == s].mean(axis=0) for s in slices])
    # tip: the vertex lying farthest ahead along the end of the axis. The farthest vertex from the base
    # is often a corner of the leaf, and it also skews the last slice, so that slice is not an axis point
    if len(slices) > 2:
        slices, polyline = slices[:-1], polyline[:-1]
        end = np.flatnonzero(slice_id >= slices[-1])
        ahead = polyline[-1] - polyline[-2]
        ahead /= max(np.linalg.norm(ahead), 1e-12)
        rel = pts[end] - polyline[-1]
        along = rel @ ahead
        # a corner of a blunt tip reaches as far ahead as its middle: prefer the vertex near the axis line
        tip = end[(along - 0.5 * np.linalg.norm(rel - np.outer(along, ahead), axis=1)).argmax()]
    else:
        tip = from_base.argmax()
    polyline = np.vstack([polyline, pts[tip]])

    balanced, lopsided, ratios = [], [], []
    for k in range(1, len(slices)):
        near = np.abs(position - (slices[k] + 0.5) / n_slices) <= SECTION_SLICE_SPAN / n_slices
        section = cross_section(pts[near], polyline[k], polyline[k + 1] - polyline[k - 1],
                                SECTION_HALF_THICKNESS_EDGES * edge_length)
        if section is None or not section_is_plausible(section, polyline[k - 1], polyline[k], polyline[k + 1]):
            continue
        sides = np.linalg.norm(section[[0, -1]] - polyline[k], axis=1)
        ratios.append(sides.max() / max(sides.min(), 1e-12))
        (balanced if ratios[-1] <= SECTION_MAX_SIDE_RATIO else lopsided).append((k, section, sides.min()))
    sections = [{"axis_index": k, "width": polyline_length(sec), "polyline": sec.tolist(), "trimmed": False}
                for k, sec, _ in balanced]
    if balanced:
        # half-width expected at a lopsided section, read on the balanced ones around it
        expected = np.interp([k for k, _, _ in lopsided], [k for k, _, _ in balanced], [s["width"] / 2 for s in sections])
        for (k, sec, short), half in zip(lopsided, expected):
            if short >= SECTION_MIN_SHORT_SIDE * half:  # the short side is sound: only the long one overshoots
                sec = trim_section(sec, polyline[k], short)
                sections.append({"axis_index": k, "width": polyline_length(sec), "polyline": sec.tolist(), "trimmed": True})
        sections.sort(key=lambda s: s["axis_index"])
    return polyline, int(idx[main[tip]]), sections, ratios


def cross_section(pts, origin, tangent, half_thickness, n_bins=SECTION_BINS):
    """Polyline across the leaf through `origin`, perpendicular to `tangent`, margin to margin.

    Uses the points of `pts` within `half_thickness` of the plane normal to the tangent and joins their
    centroids binned along the widest direction of that slab, so the curve follows the leaf surface.
    The slab must stay thin: its end points are the outermost vertices of the whole slab, so a thick
    one reports the largest width found along it and overshoots the margin. None if too few points.
    """
    step = np.linalg.norm(tangent)
    if step == 0:
        return None
    tangent = tangent / step
    rel = pts - origin
    rel = rel[np.abs(rel @ tangent) <= half_thickness]
    if len(rel) < SECTION_MIN_POINTS:
        return None
    flat = rel - np.outer(rel @ tangent, tangent)
    lateral = np.linalg.svd(flat - flat.mean(axis=0), full_matrices=False)[2][0]
    u = flat @ lateral
    bin_id = np.minimum(((u - u.min()) / max(np.ptp(u), 1e-12) * n_bins).astype(int), n_bins - 1)
    inner = [flat[bin_id == b].mean(axis=0) for b in range(n_bins) if (bin_id == b).any()]
    return origin + np.vstack([flat[u.argmin()], inner, flat[u.argmax()]])


def trim_section(section, origin, reach):
    """Cut the side of `section` whose end lies farthest from `origin` where it gets `reach` away from it.

    The distance to the origin is interpolated linearly between two section points, so the cut is approximate.
    """
    if np.linalg.norm(section[0] - origin) > np.linalg.norm(section[-1] - origin):
        section = section[::-1]
    dist = np.linalg.norm(section - origin, axis=1)
    start = dist.argmin()
    out = start + np.flatnonzero(dist[start:] > reach)[0]
    t = (reach - dist[out - 1]) / (dist[out] - dist[out - 1])
    return np.vstack([section[:out], section[out - 1] + t * (section[out] - section[out - 1])])


def section_is_plausible(section, before, origin, after):
    """False for a cross-section that cannot be a leaf width; `before`, `origin`, `after` are its axis points."""
    seg_in, seg_out = origin - before, after - origin
    turn = seg_in @ seg_out / max(np.linalg.norm(seg_in) * np.linalg.norm(seg_out), 1e-12)
    return (turn >= np.cos(np.radians(SECTION_MAX_AXIS_KINK_DEG))
            and polyline_length(section) <= SECTION_MAX_TORTUOSITY * np.linalg.norm(section[-1] - section[0]))


def polyline_length(polyline):
    return float(np.linalg.norm(np.diff(polyline, axis=0), axis=1).sum())


def resample(polyline, n):
    """n points evenly spaced along a polyline."""
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(polyline, axis=0), axis=1))])
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, polyline[:, k]) for k in range(3)], axis=1)


def save_check_view(acq_dir, view, center, axes, sections, out_path):
    """Draw the axes (center = white dot, tips = dots) and cross-sections over one cropped view."""
    import cv2  # only needed for this optional figure

    cam = next(c for c in load_cameras(acq_dir / "cameras.xml")[0] if c["label"] == view)
    with open(acq_dir / "image_crop" / "crops.json") as fh:
        x0, y0 = json.load(fh)["crops"][view + ".png"][:2]
    image = cv2.imread(str(acq_dir / "image_crop" / (view + ".png")))
    colors = leaf_colors(np.arange(len(axes)))[:, ::-1] * 255

    def to_px(points):
        return np.round(project(np.atleast_2d(points), cam["world_to_cam"], cam["calib"])[0] - (x0, y0)).astype(np.int32)

    for leaf, polyline in enumerate(axes):
        px, color = to_px(np.vstack([center, polyline])), colors[leaf].tolist()
        cv2.polylines(image, [px], False, (0, 0, 0), 7)
        cv2.polylines(image, [px], False, color, 3)
        cv2.polylines(image, [to_px(np.array(sec["polyline"])) for sec in sections[leaf]], False, color, 2)
        cv2.circle(image, tuple(map(int, px[-1])), 8, color, -1)
        cv2.putText(image, str(leaf), tuple(map(int, px[-1] + 10)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    cv2.circle(image, tuple(map(int, to_px(center)[0])), 12, (255, 255, 255), -1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), image)


def save_side_ratio_figure(ratios, out_path):
    """Histogram of the cross-section side ratios (log scale), with the lopsided threshold."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, ink_soft, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    ratios = np.asarray(ratios)
    log_r = np.log2(ratios)
    q1, q3 = np.percentile(log_r, [25, 75])
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=surface)
    bins = np.logspace(0, np.log10(max(ratios.max(), 4)), 40)
    ax.hist(ratios[ratios <= SECTION_MAX_SIDE_RATIO], bins=bins, color="#2a78d6", edgecolor=surface, label="balanced")
    ax.hist(ratios[ratios > SECTION_MAX_SIDE_RATIO], bins=bins, color="#eb6834", edgecolor=surface, label="lopsided")
    ax.set_xscale("log")
    ticks = [t for t in (1, 1.5, 2, 3, 5, 10, 20, 50) if t <= bins[-1]]
    ax.set_xticks(ticks, [f"{t:g}" for t in ticks])
    ax.minorticks_off()
    ax.axvline(SECTION_MAX_SIDE_RATIO, color=ink, linewidth=1.5)
    ax.annotate(f"threshold {SECTION_MAX_SIDE_RATIO:g} (Tukey fence of these data: {2 ** (q3 + 1.5 * (q3 - q1)):.2f})",
                (SECTION_MAX_SIDE_RATIO, 1), xycoords=("data", "axes fraction"), xytext=(4, -12),
                textcoords="offset points", fontsize=8, color=ink_soft)
    ax.set_facecolor(surface)
    ax.grid(axis="y", color=grid, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=ink_soft, labelsize=8, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(grid)
    ax.set_xlabel("Long side / short side of the cross-section about the axis", fontsize=9, color=ink_soft)
    ax.set_ylabel("Number of cross-sections", fontsize=9, color=ink_soft)
    ax.legend(frameon=False, fontsize=8)
    ax.set_title(f"Cross-section side ratio, {len(ratios)} sections (median {np.median(ratios):.2f}, "
                 f"{(ratios > SECTION_MAX_SIDE_RATIO).sum()} lopsided)", fontsize=11, color=ink, loc="left")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acq_dirs", type=Path, nargs="+")
    parser.add_argument("--check-view", metavar="LABEL", help="camera label to draw the axes on, e.g. top_009")
    parser.add_argument("--out-dir", type=Path, help="figures folder (default: results/ next to the acquisitions)")
    args = parser.parse_args()
    out_dir = args.out_dir or args.acq_dirs[0].resolve().parent / "results"
    all_ratios = []
    for acq_dir in args.acq_dirs:
        vertices, _, faces = load_mesh(acq_dir / "mesh_green.ply")
        with open(acq_dir / "mesh_green_leaves.json") as fh:
            labels = np.array(json.load(fh)["vertex_leaf_id"])
        cameras = load_cameras(acq_dir / "cameras.xml")[0]
        camera_positions = np.array([np.linalg.inv(c["world_to_cam"])[:3, 3] for c in cameras])
        size = vertex_areas(vertices, faces) / pixel_footprint(vertices, cameras) ** 2  # px^2 per vertex
        center = rosette_center(vertices, labels, up_direction(vertices, camera_positions), size)
        axes, sections, leaves = [], [], []
        for leaf in range(labels.max() + 1):
            polyline, tip, leaf_sections, ratios = leaf_axis(vertices, faces, labels == leaf, center)
            if size[labels == leaf].sum() >= CENTER_MIN_LEAF_AREA_PX2:  # rosette-heart fragments would blur the distribution
                all_ratios += ratios
            axes.append(polyline)
            sections.append(leaf_sections)
            leaves.append({"id": leaf, "tip_vertex": tip, "tip": polyline[-1].tolist(),
                           "length_on_leaf": polyline_length(polyline),
                           "length_from_center": polyline_length(np.vstack([center, polyline])),
                           "axis": polyline.tolist(), "cross_sections": leaf_sections})
        with open(acq_dir / "leaf_axes.json", "w") as fh:
            json.dump({"units": "mesh units (uncalibrated)", "center": center.tolist(),
                       "axis_format": "polyline on the leaf, base side to tip; prepend center for the full axis",
                       "cross_section_format": "polyline across the leaf, margin to margin, through axis[axis_index] "
                                               "and perpendicular to the axis there; width = its length",
                       "parameters": {"center_min_leaf_area_px2": CENTER_MIN_LEAF_AREA_PX2,
                                      "center_column_radius": CENTER_COLUMN_RADIUS,
                                      "center_column_percentile": CENTER_COLUMN_PERCENTILE, "n_slices": N_SLICES,
                                      "link_radius_edges": LINK_RADIUS_EDGES,
                                      "section_half_thickness_edges": SECTION_HALF_THICKNESS_EDGES,
                                      "section_max_side_ratio": SECTION_MAX_SIDE_RATIO,
                                      "section_min_short_side": SECTION_MIN_SHORT_SIDE,
                                      "section_max_axis_kink_deg": SECTION_MAX_AXIS_KINK_DEG,
                                      "section_max_tortuosity": SECTION_MAX_TORTUOSITY},
                       "leaves": leaves}, fh)
        curves = [(leaf, np.vstack([center, a])) for leaf, a in enumerate(axes)]
        curves += [(leaf, np.array(sec["polyline"])) for leaf, secs in enumerate(sections) for sec in secs]
        cloud = np.vstack([resample(c, PLY_POINTS_PER_CURVE) for _, c in curves] + [center[None]])
        cloud_colors = np.vstack([leaf_colors(np.repeat([leaf for leaf, _ in curves], PLY_POINTS_PER_CURVE)), [[1, 1, 1]]])
        save_ply(acq_dir / "leaf_axes.ply", cloud, cloud_colors, np.zeros((0, 3), dtype=int))
        n_trimmed = sum(sec["trimmed"] for secs in sections for sec in secs)
        print(f"{acq_dir.name}: {len(axes)} axes, {n_trimmed} cross-sections cut back -> {acq_dir / 'leaf_axes.json'}")
        if args.check_view:
            out_path = out_dir / f"leaf_axes_{acq_dir.name}_{args.check_view}.jpg"
            save_check_view(acq_dir, args.check_view, center, axes, sections, out_path)
    save_side_ratio_figure(all_ratios, out_dir / "section_side_ratios.png")


if __name__ == "__main__":
    main()
