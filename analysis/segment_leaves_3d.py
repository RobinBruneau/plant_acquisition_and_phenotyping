"""Lift the 2D leaf masks to a 3D leaf segmentation of the cleaned green mesh.

Usage (conda env `phenotyping`):
    python segment_leaves_3d.py ACQ_DIR [ACQ_DIR ...]

Each ACQ_DIR must hold mesh_green.ply, cameras.xml, image_crop/crops.json and
image_crop_seg_clean/results_*.json. Each 2D mask can first be eroded by ERODE_PX pixels (off by default:
on a leaf lying over another one, it hands the margin of the upper leaf to the lower one). In every view
the vertices that are not hidden behind the plant take the id of the 2D mask they project into; masks of
different views that cover the same vertices are merged into one 3D leaf, each vertex takes the leaf with
the most votes, a view voting with weight |cos|^VOTE_COS_POWER (off by default) of the angle between the vertex normal and
the line of sight (a leaf margin seen edge-on falls into the mask of whatever lies behind it), small pieces
of a leaf detached from its main part (smears along the margin of another leaf) take the leaf they
touch, the leaves can then grow along the mesh into the unlabeled vertices within GROW_PX pixels of them (the
margins the erosion took away; larger unlabeled parts keep their middle unlabeled), and small unlabeled gaps
take the leaf around them.
Written next to the mesh:
    mesh_green_leaves.ply   mesh_green.ply with vertices colored by leaf (grey = no leaf)
    mesh_green_leaves.json  leaf id per vertex index of mesh_green.ply (-1 = no leaf) and parameters
"""
import argparse
import colorsys
import json
from pathlib import Path

import cv2
import numpy as np
import pycocotools.mask as mask_util
from scipy import sparse
from scipy.ndimage import minimum_filter
from scipy.sparse.csgraph import connected_components, dijkstra

from mesh_io import load_mesh, save_ply, vertex_areas
from reproject_check import load_cameras, pixel_footprint, project

DEPTH_CELL_PX = 6          # cell of the point-splat depth buffer, in original image pixels
DEPTH_TOLERANCE_CELLS = 3  # a vertex is hidden if it lies deeper than the front surface by this many cells
# sizes are mesh areas in image pixels^2 (see pixel_footprint), so they hold for any mesh density;
# a mesh reconstructed at Highest/Ultra quality has about 18 px^2 per vertex
MIN_MASK_AREA_PX2 = 540    # 2D masks covering less visible mesh are ignored
MERGE_IOU = 0.5            # two masks of different views are the same leaf above this 3D IoU
MIN_LEAF_MASKS = 3         # a 3D leaf must be supported by at least this many 2D masks
MIN_LEAF_AREA_PX2 = 900    # smaller 3D leaves are detection noise, their vertices stay unlabeled
MAX_STRAY_AREA_PX2 = 3600  # pieces of a leaf smaller than this, detached from its largest piece, go to a neighbor leaf
MAX_FILL_AREA_PX2 = 900    # unlabeled zones smaller than this take the id of the leaf around them
MIN_VOTE_FRACTION = 0.5    # share of a vertex's votes its leaf must win, else the vertex stays unlabeled
ERODE_PX = 0               # each 2D mask is eroded by this many pixels before voting (0 = off)
GROW_PX = 0                # leaves then grow into unlabeled vertices up to this distance, in pixels of the median view footprint (0 = off)
VOTE_COS_POWER = 0         # vote weight = |cos(normal, line of sight)| ** this; 0 = every view votes 1
UNLABELED_COLOR = (0.5, 0.5, 0.5)


def visible_vertices(vertices, faces, world_to_cam, calib):
    """Return (uv Nx2, visible mask): vertices in frame and not hidden behind the mesh in this view."""
    # shortcut: depth buffer splatted from vertices and face centroids instead of rasterized triangles;
    # needs triangles smaller than DEPTH_CELL_PX, switch to a real rasterizer for coarse meshes
    samples = np.concatenate([vertices, vertices[faces].mean(axis=1)])
    uv, in_front = project(samples, world_to_cam, calib)
    depth = samples @ world_to_cam[2, :3] + world_to_cam[2, 3]
    grid_w, grid_h = calib["width"] // DEPTH_CELL_PX + 1, calib["height"] // DEPTH_CELL_PX + 1
    cell = np.floor(uv / DEPTH_CELL_PX).astype(np.int64)
    in_frame = in_front & (cell[:, 0] >= 0) & (cell[:, 0] < grid_w) & (cell[:, 1] >= 0) & (cell[:, 1] < grid_h)
    zbuf = np.full((grid_h, grid_w), np.inf)
    np.minimum.at(zbuf, (cell[in_frame, 1], cell[in_frame, 0]), depth[in_frame])
    zbuf = minimum_filter(zbuf, size=3)

    n = len(vertices)
    visible = in_frame[:n].copy()
    idx = np.flatnonzero(visible)
    z = depth[idx]
    tolerance = DEPTH_TOLERANCE_CELLS * DEPTH_CELL_PX * z / calib["f"]
    visible[idx] = z <= zbuf[cell[idx, 1], cell[idx, 0]] + tolerance
    return uv[:n], visible


def mask_label_image(results, erode_px=ERODE_PX):
    """HxW int image of annotation indices (-1 = background), each mask eroded by erode_px; where masks overlap the smallest wins."""
    labels = np.full((results["img_height"], results["img_width"]), -1, dtype=np.int32)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * erode_px + 1,) * 2)
    masks = [cv2.erode(mask_util.decode(a["segmentation"]), kernel).astype(bool) for a in results["annotations"]]
    for i in sorted(range(len(masks)), key=lambda i: -masks[i].sum()):
        labels[masks[i]] = i
    return labels


def merge_masks(membership, mask_view, visibility, min_iou=MERGE_IOU):
    """Group 2D masks into 3D leaves.

    membership: sparse bool (n_vertices, n_masks), vertex seen inside mask;
    mask_view: view index of each mask; visibility: sparse bool (n_vertices, n_views).
    Mask pairs of different views are merged by decreasing IoU (counted on the vertices visible in
    both views, down to min_iou), unless the merged leaf would hold two masks of the same view: masks
    of one view are disjoint, so they are different leaves. Returns the group id of each mask.
    """
    m, vis = membership.astype(np.float64).tocsc(), visibility.astype(np.float64).tocsc()
    inter = (m.T @ m).tocoo()
    seen_in_view = np.asarray((m.T @ vis).todense())  # [mask, view]: vertices of the mask visible in that view
    a, b = inter.row, inter.col
    union = seen_in_view[a, mask_view[b]] + seen_in_view[b, mask_view[a]] - inter.data
    iou = inter.data / np.maximum(union, 1)
    link = np.flatnonzero((a < b) & (mask_view[a] != mask_view[b]) & (iou >= min_iou))

    parent = list(range(membership.shape[1]))
    group_views = [1 << int(v) for v in mask_view]  # bitmask of the views present in each group

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for k in link[np.argsort(-iou[link], kind="stable")]:
        ra, rb = find(a[k]), find(b[k])
        if ra != rb and not group_views[ra] & group_views[rb]:
            parent[rb] = ra
            group_views[ra] |= group_views[rb]
    return np.unique([find(i) for i in range(len(parent))], return_inverse=True)[1]


def reassign_stray_pieces(labels, faces, max_size=MAX_STRAY_AREA_PX2, size=None):
    """Give each small piece of a leaf detached from its largest piece the leaf it shares most edges with.

    A piece is a connected set of vertices of one leaf; its size is the sum of `size` over its vertices (default:
    its vertex count), and only pieces under max_size move. Edges
    to other stray pieces do not count; a piece touching no settled leaf becomes -1. Returns a new array.
    """
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.concatenate([edges, edges[:, ::-1]])
    n = len(labels)
    same = edges[(labels[edges[:, 0]] == labels[edges[:, 1]]) & (labels[edges[:, 0]] >= 0)]
    n_pieces, piece = connected_components(sparse.coo_matrix((np.ones(len(same)), (same[:, 0], same[:, 1])),
                                                             shape=(n, n)), directed=False)
    piece_size = np.bincount(piece, weights=size)
    largest = np.zeros(labels.max() + 2)  # size of the largest piece of each leaf; last slot takes label -1
    np.maximum.at(largest, labels, piece_size[piece])
    stray = (labels >= 0) & (piece_size[piece] < max_size) & (piece_size[piece] < largest[labels])
    border = edges[stray[edges[:, 0]] & ~stray[edges[:, 1]] & (labels[edges[:, 1]] >= 0)]
    # contact[piece, leaf]: number of mesh edges between the stray piece and the settled part of the leaf
    contact = sparse.coo_matrix((np.ones(len(border)), (piece[border[:, 0]], labels[border[:, 1]])),
                                shape=(n_pieces, labels.max() + 1)).tocsr()
    piece_leaf = np.where(contact.max(axis=1).toarray().ravel() > 0, np.asarray(contact.argmax(axis=1)).ravel(), -1)
    return np.where(stray, piece_leaf[piece], labels)


def grow_into_margins(labels, vertices, faces, max_dist):
    """Give each unlabeled vertex within max_dist (along the mesh edges) of a leaf the id of the nearest leaf.

    Farther unlabeled vertices stay -1, so a large unlabeled part only loses its rim. Returns a new array.
    """
    src = np.flatnonzero(labels >= 0)
    if len(src) == 0 or max_dist <= 0:
        return labels.copy()
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)  # coo_matrix would sum the weights of repeated edges
    weights = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    graph = sparse.coo_matrix((weights, (edges[:, 0], edges[:, 1])), shape=(len(labels),) * 2).tocsr()
    dist, _, source = dijkstra(graph, directed=False, indices=src, limit=max_dist, min_only=True, return_predecessors=True)
    grow = (labels < 0) & np.isfinite(dist)
    out = labels.copy()
    out[grow] = labels[source[grow]]
    return out


def fill_small_gaps(labels, faces, max_size=MAX_FILL_AREA_PX2, size=None):
    """Give each connected unlabeled zone smaller than max_size the leaf it shares most edges with.

    The size of a zone is the sum of `size` over its vertices (default: its vertex count).

    Larger zones (parts no 2D mask covers) and zones touching no leaf stay -1. Returns a new array.
    """
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.concatenate([edges, edges[:, ::-1]])
    n = len(labels)
    inner = edges[(labels[edges] < 0).all(axis=1)]
    n_zones, zone = connected_components(sparse.coo_matrix((np.ones(len(inner)), (inner[:, 0], inner[:, 1])),
                                                           shape=(n, n)), directed=False)
    unlabeled = labels < 0
    zone_size = np.bincount(zone[unlabeled], weights=None if size is None else size[unlabeled], minlength=n_zones)
    border = edges[(labels[edges[:, 0]] < 0) & (labels[edges[:, 1]] >= 0)]
    if len(border) == 0:
        return labels.copy()
    # contact[zone, leaf]: number of mesh edges between the zone and the leaf
    contact = sparse.coo_matrix((np.ones(len(border)), (zone[border[:, 0]], labels[border[:, 1]])),
                                shape=(n_zones, labels.max() + 1)).toarray()
    zone_leaf = np.where((contact.max(axis=1) > 0) & (zone_size < max_size), contact.argmax(axis=1), -1)
    return np.where(labels < 0, zone_leaf[zone], labels)


def leaf_colors(labels):
    """Distinct color per leaf id (golden-ratio hues), grey where the label is -1."""
    colors = np.array([colorsys.hsv_to_rgb((i * 0.618034) % 1, 0.75, 0.95) for i in range(labels.max() + 1)]
                      + [UNLABELED_COLOR])
    return colors[labels]


def vertex_normals(vertices, faces):
    """Unit normal per vertex, area-weighted mean of its face normals."""
    face_normal = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]])
    normals = np.zeros_like(vertices)
    for k in range(3):
        np.add.at(normals, faces[:, k], face_normal)
    return normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-15)


def segment_acquisition(acq_dir):
    """Return (vertices, faces, leaf id per vertex, report dict) for one acquisition."""
    vertices, _, faces = load_mesh(acq_dir / "mesh_green.ply")
    normals = vertex_normals(vertices, faces)
    cameras, _ = load_cameras(acq_dir / "cameras.xml")
    size = vertex_areas(vertices, faces) / pixel_footprint(vertices, cameras) ** 2  # px^2 per vertex
    with open(acq_dir / "image_crop" / "crops.json") as fh:
        crops = json.load(fh)["crops"]

    rows, cols, weights, mask_view, vis_rows, vis_cols, views, footprints = [], [], [], [], [], [], [], []
    for cam in cameras:
        label = cam["label"]
        json_path = acq_dir / "image_crop_seg_clean" / f"results_{Path(label).stem}.json"
        if not json_path.is_file():
            print(f"SKIP  {label}: no segmentation")
            continue
        with open(json_path) as fh:
            results = json.load(fh)
        x0, y0, _, _ = crops[results["image_name"]]
        mask_image = mask_label_image(results)

        uv, visible = visible_vertices(vertices, faces, cam["world_to_cam"], cam["calib"])
        px = np.floor(uv - (x0, y0)).astype(np.int64)
        visible &= (px[:, 0] >= 0) & (px[:, 0] < mask_image.shape[1]) & (px[:, 1] >= 0) & (px[:, 1] < mask_image.shape[0])
        idx = np.flatnonzero(visible)
        hit = mask_image[px[idx, 1], px[idx, 0]]
        # mesh units covered by one pixel at the depth of the plant in this view
        footprints.append(np.median(vertices[idx] @ cam["world_to_cam"][2, :3] + cam["world_to_cam"][2, 3]) / cam["calib"]["f"])
        sight = np.linalg.inv(cam["world_to_cam"])[:3, 3] - vertices[idx]
        # abs: the mesh has an upper and a lower skin, their normals point opposite ways
        weight = np.abs((normals[idx] * sight).sum(axis=1) / np.linalg.norm(sight, axis=1)) ** VOTE_COS_POWER
        view = len(views)
        views.append(label)
        vis_rows.append(idx)
        vis_cols.append(np.full(len(idx), view))
        for i in range(len(results["annotations"])):
            members = idx[hit == i]
            if size[members].sum() >= MIN_MASK_AREA_PX2:
                rows.append(members)
                cols.append(np.full(len(members), len(mask_view)))
                weights.append(weight[hit == i])
                mask_view.append(view)

    n_vertices, mask_view = len(vertices), np.array(mask_view)
    rows, cols, weights = np.concatenate(rows), np.concatenate(cols), np.concatenate(weights)
    membership = sparse.coo_matrix((np.ones(len(rows), bool), (rows, cols)), shape=(n_vertices, len(mask_view)))
    vis_rows, vis_cols = np.concatenate(vis_rows), np.concatenate(vis_cols)
    visibility = sparse.coo_matrix((np.ones(len(vis_rows), bool), (vis_rows, vis_cols)), shape=(n_vertices, len(views)))

    group = merge_masks(membership, mask_view, visibility)
    group_size = np.bincount(group)
    kept = np.flatnonzero(group_size >= MIN_LEAF_MASKS)
    # votes[vertex, group]: weighted number of views in which the vertex fell in a mask of that group
    assign = sparse.coo_matrix((np.ones(len(group)), (np.arange(len(group)), group)), shape=(len(group), len(group_size)))
    weighted = sparse.coo_matrix((weights, (rows, cols)), shape=membership.shape)
    all_votes = (weighted.tocsr() @ assign.tocsr()).tocsc()
    votes = all_votes[:, kept].toarray()
    total = np.asarray(all_votes.sum(axis=1)).ravel()
    best = votes.argmax(axis=1)
    best_votes = votes[np.arange(n_vertices), best]
    labels = np.where((best_votes > 0) & (best_votes >= MIN_VOTE_FRACTION * total), best, -1)
    labels = reassign_stray_pieces(labels, faces, size=size)

    # renumber by decreasing vertex count so that leaf 0 is the largest
    leaf_size = np.bincount(labels[labels >= 0], weights=size[labels >= 0], minlength=len(kept))
    order = np.argsort(-leaf_size, kind="stable")
    order = order[leaf_size[order] >= MIN_LEAF_AREA_PX2]
    remap = np.full(len(kept) + 1, -1)
    remap[order] = np.arange(len(order))
    labels = remap[labels]
    n_voted = int((labels >= 0).sum())
    labels = grow_into_margins(labels, vertices, faces, GROW_PX * np.median(footprints))
    n_grown = int((labels >= 0).sum()) - n_voted
    labels = fill_small_gaps(labels, faces, size=size)
    report = {
        "n_views": len(views), "n_masks": len(mask_view), "n_leaves": len(order),
        "labeled_vertex_fraction": float((labels >= 0).mean()),
        "n_grown_vertices": n_grown, "n_gap_filled_vertices": int((labels >= 0).sum()) - n_voted - n_grown,
        "leaves": [{"id": i, "n_vertices": int((labels == i).sum()), "area_px2": float(size[labels == i].sum()), "n_masks": int(group_size[kept[g]])}
                   for i, g in enumerate(order)],
    }
    return vertices, faces, labels, report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acq_dirs", type=Path, nargs="+")
    parser.add_argument("--out-dir", type=Path, help="write here instead of ACQ_DIR (single acquisition, for trials)")
    args = parser.parse_args()
    for acq_dir in args.acq_dirs:
        vertices, faces, labels, report = segment_acquisition(acq_dir)
        out_dir = args.out_dir or acq_dir
        save_ply(out_dir / "mesh_green_leaves.ply", vertices, leaf_colors(labels), faces)
        with open(out_dir / "mesh_green_leaves.json", "w") as fh:
            json.dump({**report,
                       "parameters": {"depth_cell_px": DEPTH_CELL_PX, "depth_tolerance_cells": DEPTH_TOLERANCE_CELLS,
                                      "min_mask_area_px2": MIN_MASK_AREA_PX2, "merge_iou": MERGE_IOU,
                                      "min_leaf_masks": MIN_LEAF_MASKS, "min_leaf_area_px2": MIN_LEAF_AREA_PX2, "max_stray_area_px2": MAX_STRAY_AREA_PX2,
                                      "max_fill_area_px2": MAX_FILL_AREA_PX2,
                                      "min_vote_fraction": MIN_VOTE_FRACTION, "erode_px": ERODE_PX, "grow_px": GROW_PX,
                                      "vote_cos_power": VOTE_COS_POWER},
                       "vertex_leaf_id": labels.tolist()}, fh)
        print(f"{acq_dir.name}: {report['n_leaves']} leaves from {report['n_masks']} masks in {report['n_views']} views, "
              f"{report['labeled_vertex_fraction']:.0%} of vertices labeled "
              f"({report['n_grown_vertices']} by growing, {report['n_gap_filled_vertices']} by gap filling) -> {out_dir}")
        for leaf in report["leaves"]:
            print(f"  leaf {leaf['id']:2d}: {leaf['n_vertices']:6d} vertices, {leaf['n_masks']:3d} masks")


if __name__ == "__main__":
    main()
