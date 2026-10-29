"""Minimal triangle-mesh I/O (OBJ and binary PLY) with per-vertex colors."""
from pathlib import Path

import numpy as np

_PLY_TYPES = {
    "char": "i1", "uchar": "u1", "short": "i2", "ushort": "u2",
    "int": "i4", "uint": "u4", "float": "f4", "double": "f8",
    "int8": "i1", "uint8": "u1", "int16": "i2", "uint16": "u2",
    "int32": "i4", "uint32": "u4", "float32": "f4", "float64": "f8",
}


def load_mesh(path):
    """Return (vertices Nx3, colors Nx3 in [0, 1] or None, faces Mx3)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".ply":
        return _load_ply(path)
    if suffix == ".obj":
        return _load_obj(path)
    raise ValueError(f"Unsupported mesh format: {path}")


def _load_ply(path):
    with open(path, "rb") as fh:
        if fh.readline().strip() != b"ply":
            raise ValueError(f"Not a PLY file: {path}")
        fmt, elements = None, []
        while True:
            line = fh.readline()
            if not line:
                raise ValueError(f"Truncated PLY header: {path}")
            tok = line.decode("ascii").split()
            if not tok:
                continue
            if tok[0] == "end_header":
                break
            if tok[0] == "format":
                fmt = tok[1]
            elif tok[0] == "element":
                elements.append((tok[1], int(tok[2]), []))
            elif tok[0] == "property":
                elements[-1][2].append(tok[1:])
        if fmt != "binary_little_endian":
            raise ValueError(f"Only binary little-endian PLY is supported, got '{fmt}': {path}")
        data = {}
        for name, count, props in elements:
            fields = []
            for p in props:
                if p[0] == "list":
                    # shortcut: assumes every list has 3 items (triangles), checked below
                    fields += [(p[3] + "_n", "<" + _PLY_TYPES[p[1]]), (p[3], "<" + _PLY_TYPES[p[2]], (3,))]
                else:
                    fields.append((p[1], "<" + _PLY_TYPES[p[0]]))
            data[name] = np.fromfile(fh, dtype=np.dtype(fields), count=count)

    v = data["vertex"]
    vertices = np.stack([v["x"], v["y"], v["z"]], axis=1).astype(np.float64)
    colors = None
    if "red" in v.dtype.names:
        colors = np.stack([v["red"], v["green"], v["blue"]], axis=1).astype(np.float64)
        if v["red"].dtype == np.uint8:
            colors /= 255.0
    faces = np.zeros((0, 3), dtype=np.int64)
    if "face" in data and len(data["face"]):
        f = data["face"]
        index_field = next(n for n in f.dtype.names if not n.endswith("_n"))
        if len(f.dtype.names) != 2 or not (f[index_field + "_n"] == 3).all():
            raise ValueError(f"Only plain triangle faces are supported (export without texture): {path}")
        faces = f[index_field].astype(np.int64)
    return vertices, colors, faces


def _load_obj(path):
    # shortcut: pure-Python line loop, slow on multi-million-face meshes; prefer PLY for those
    v, f = [], []
    with open(path) as fh:
        for line in fh:
            if line.startswith("v "):
                v.append(line.split()[1:])
            elif line.startswith("f "):
                f.append([t.split("/")[0] for t in line.split()[1:]])
    v = np.array(v, dtype=np.float64)
    faces = np.array(f, dtype=np.int64).reshape(-1, 3) - 1
    colors = v[:, 3:6] if v.shape[1] >= 6 else None
    return v[:, :3], colors, faces


def vertex_areas(vertices, faces):
    """Area of the mesh attached to each vertex: a third of the area of every face around it."""
    face_area = np.linalg.norm(np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                                        vertices[faces[:, 2]] - vertices[faces[:, 0]]), axis=1) / 2
    return np.bincount(faces.ravel(), weights=np.repeat(face_area / 3, 3), minlength=len(vertices))


def save_ply(path, vertices, colors, faces):
    """Write a binary PLY with per-vertex colors (colors in [0, 1])."""
    v = np.empty(len(vertices), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                       ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    v["x"], v["y"], v["z"] = np.asarray(vertices).T
    v["red"], v["green"], v["blue"] = np.round(np.clip(colors, 0, 1) * 255).T
    f = np.empty(len(faces), dtype=[("n", "u1"), ("idx", "<i4", (3,))])
    f["n"] = 3
    f["idx"] = faces
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(v)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\n"
        f"element face {len(f)}\n"
        "property list uchar int vertex_indices\nend_header\n"
    )
    with open(path, "wb") as fh:
        fh.write(header.encode("ascii"))
        v.tofile(fh)
        f.tofile(fh)
