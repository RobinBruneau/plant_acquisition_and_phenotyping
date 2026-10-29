"""Keep only the green (leaf) part of a vertex-colored mesh.

Usage:
    python filter_green.py MESH_IN MESH_OUT.ply

A vertex is green when its normalized excess-green index (2g - r - b) / (r + g + b)
exceeds --exg-min and it is not too dark. A face is kept when its 3 vertices are green.
Connected fragments holding less than --min-fragment of the green faces are then dropped.
The mesh must carry per-vertex colors (not a texture).
"""
import argparse
from pathlib import Path

import numpy as np

from mesh_io import load_mesh, save_ply


def green_vertex_mask(colors, exg_min=0.1, brightness_min=0.05):
    """Boolean mask of green vertices from Nx3 colors in [0, 1]."""
    total = colors.sum(axis=1)
    exg = (2 * colors[:, 1] - colors[:, 0] - colors[:, 2]) / np.maximum(total, 1e-9)
    return (exg > exg_min) & (total / 3 > brightness_min)


def filter_mesh(vertices, colors, faces, keep_vertex):
    """Keep faces whose 3 vertices are flagged, drop unused vertices and reindex."""
    faces = faces[keep_vertex[faces].all(axis=1)]
    used = np.unique(faces)
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    return vertices[used], colors[used], remap[faces]


def drop_small_fragments(vertices, colors, faces, min_fraction=0.01):
    """Drop connected components holding less than min_fraction of the faces."""
    labels = np.arange(len(vertices))
    while True:  # propagate the smallest vertex index through each component
        new = labels.copy()
        np.minimum.at(new, faces.ravel(), np.repeat(labels[faces].min(axis=1), 3))
        new = new[new]
        if (new == labels).all():
            break
        labels = new
    faces_per_component = np.bincount(labels[faces[:, 0]], minlength=len(vertices))
    return filter_mesh(vertices, colors, faces, faces_per_component[labels] >= min_fraction * len(faces))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mesh_in", type=Path)
    parser.add_argument("mesh_out", type=Path)
    parser.add_argument("--exg-min", type=float, default=0.1, help="excess-green threshold (default: 0.1)")
    parser.add_argument("--brightness-min", type=float, default=0.05, help="minimum mean RGB (default: 0.05)")
    parser.add_argument("--min-fragment", type=float, default=0.01,
                        help="drop fragments below this fraction of the green faces (default: 0.01)")
    args = parser.parse_args()

    if args.mesh_out.exists():
        parser.error(f"{args.mesh_out} already exists, refusing to overwrite")
    vertices, colors, faces = load_mesh(args.mesh_in)
    if colors is None:
        parser.error("mesh has no per-vertex colors: re-export from Metashape with 'Vertex colors' enabled")

    keep = green_vertex_mask(colors, args.exg_min, args.brightness_min)
    out_vertices, out_colors, out_faces = filter_mesh(vertices, colors, faces, keep)
    n_green = len(out_faces)
    out_vertices, out_colors, out_faces = drop_small_fragments(out_vertices, out_colors, out_faces, args.min_fragment)
    save_ply(args.mesh_out, out_vertices, out_colors, out_faces)
    print(f"vertices: {len(vertices)} -> {len(out_vertices)}")
    print(f"faces:    {len(faces)} -> {n_green} green -> {len(out_faces)} after fragment removal")


if __name__ == "__main__":
    main()
