import numpy as np

from filter_green import drop_small_fragments, filter_mesh, green_vertex_mask
from mesh_io import load_mesh, save_ply
from reproject_check import load_cameras, project

CAMERAS_XML = """<document version="2.0.0"><chunk>
<sensors><sensor id="0"><calibration type="frame" class="adjusted">
<resolution width="100" height="200"/><f>1000</f><cx>3</cx><cy>-2</cy>
</calibration></sensor></sensors>
<cameras>
<camera id="0" sensor_id="0" label="aligned"><transform>1 0 0 0 0 1 0 0 0 0 1 -5 0 0 0 1</transform></camera>
<camera id="1" sensor_id="0" label="lost"/>
</cameras>
<transform><rotation>1 0 0 0 1 0 0 0 1</rotation><translation>0 0 0</translation><scale>2</scale></transform>
</chunk></document>"""

VERTICES = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
COLORS = np.array([[0.1, 0.5, 0.1], [0.2, 0.6, 0.1], [0.1, 0.4, 0.1], [0.3, 0.2, 0.15]])  # last one is soil brown
FACES = np.array([[0, 1, 2], [1, 3, 2]])


def test_projection_with_chunk_scale(tmp_path):
    xml = tmp_path / "cameras.xml"
    xml.write_text(CAMERAS_XML)
    cameras, unaligned = load_cameras(xml)
    assert unaligned == ["lost"] and len(cameras) == 1
    # world (1,0,0) is (0.5,0,0) in the internal frame, 5 units in front of the camera -> x = 0.1
    uv, in_front = project(np.array([[0.0, 0, 0], [1.0, 0, 0], [0, 0, -20.0]]),
                           cameras[0]["world_to_cam"], cameras[0]["calib"])
    assert np.allclose(uv[0], [53, 98]) and np.allclose(uv[1], [153, 98])
    assert in_front.tolist() == [True, True, False]


def test_ply_roundtrip_and_green_filter(tmp_path):
    path = tmp_path / "mesh.ply"
    save_ply(path, VERTICES, COLORS, FACES)
    vertices, colors, faces = load_mesh(path)
    assert np.allclose(vertices, VERTICES) and np.allclose(colors, COLORS, atol=1 / 255)
    assert (faces == FACES).all()

    keep = green_vertex_mask(colors)
    assert keep.tolist() == [True, True, True, False]
    v, c, f = filter_mesh(vertices, colors, faces, keep)
    assert len(v) == 3 and f.tolist() == [[0, 1, 2]]


def test_obj_with_vertex_colors(tmp_path):
    path = tmp_path / "mesh.obj"
    path.write_text("v 0 0 0 0.1 0.5 0.1\nv 1 0 0 0.2 0.6 0.1\nv 0 1 0 0.1 0.4 0.1\nvn 0 0 1\nf 1/1/1 2/2/1 3/3/1\n")
    vertices, colors, faces = load_mesh(path)
    assert vertices.shape == (3, 3) and np.allclose(colors[0], [0.1, 0.5, 0.1]) and faces.tolist() == [[0, 1, 2]]


def test_drop_small_fragments():
    # a strip of 4 triangles plus one detached triangle
    vertices = np.zeros((9, 3))
    faces = np.array([[5, 4, 3], [4, 3, 2], [3, 2, 1], [2, 1, 0], [6, 7, 8]])
    v, c, f = drop_small_fragments(vertices, vertices, faces, min_fraction=0.5)
    assert len(v) == 6 and len(f) == 4
    v, c, f = drop_small_fragments(vertices, vertices, faces, min_fraction=0.1)
    assert len(v) == 9 and len(f) == 5


def test_crop_box():
    from crop_images import crop_box
    uv = np.array([[50.4, 60.0], [80.9, 199.5]])
    assert crop_box(uv, 100, 200, margin=10) == (40, 50, 91, 200)  # bottom edge clipped to the image
    assert crop_box(uv + 500, 100, 200) is None and crop_box(uv[:0], 100, 200) is None


def test_drop_large_boxes():
    from clean_segmentation import drop_large_boxes
    results = {"img_width": 100, "img_height": 100, "total_leaves_detected": 2,
               "annotations": [{"bbox": [0, 0, 50, 50]}, {"bbox": [0, 0, 51, 50]}]}
    clean = drop_large_boxes(results, 0.25)
    assert clean["annotations"] == [{"bbox": [0, 0, 50, 50]}] and clean["total_leaves_detected"] == 1
    assert len(results["annotations"]) == 2


def test_visible_vertices_hides_the_back_plane():
    from segment_leaves_3d import visible_vertices

    # two parallel 20x20 grids facing the camera, the second one right behind the first
    g = np.stack(np.meshgrid(np.linspace(-0.1, 0.1, 20), np.linspace(-0.1, 0.1, 20)), axis=-1).reshape(-1, 2)
    vertices = np.concatenate([np.c_[g, np.full(len(g), 5.0)], np.c_[g, np.full(len(g), 6.0)]])
    faces = np.array([[0, 1, 20], [400, 401, 420]])
    calib = {"f": 1000.0, "cx": 0.0, "cy": 0.0, "width": 200, "height": 200,
             **{k: 0.0 for k in ("k1", "k2", "k3", "k4", "p1", "p2", "b1", "b2")}}
    _, visible = visible_vertices(vertices, faces, np.eye(4), calib)
    assert visible[:400].all() and not visible[400:].any()


def test_merge_masks_keeps_same_view_masks_apart():
    from scipy import sparse
    from segment_leaves_3d import merge_masks

    # leaves A = vertices 0-9 and B = 10-19; view 0 and 1 see both, view 2 sees one mask bridging them
    members = [range(0, 10), range(10, 20), range(0, 10), range(10, 20), range(4, 16)]
    mask_view = np.array([0, 0, 1, 1, 2])
    membership = sparse.lil_matrix((20, 5), dtype=bool)
    for j, m in enumerate(members):
        membership[list(m), j] = True
    group = merge_masks(membership.tocoo(), mask_view, sparse.coo_matrix(np.ones((20, 3), bool)), min_iou=0.3)
    assert group[0] == group[2] and group[1] == group[3] and group[0] != group[1]


def test_fill_small_gaps_fills_only_small_zones():
    from segment_leaves_3d import fill_small_gaps

    # a strip of 12 vertices: leaf 0, a 1-vertex gap, leaf 0, then a 5-vertex gap up to leaf 1
    faces = np.array([[i, i + 1, i + 2] for i in range(10)])
    labels = np.array([0, 0, -1, 0, 0, -1, -1, -1, -1, -1, 1, 1])
    filled = fill_small_gaps(labels, faces, max_size=3)
    assert filled.tolist() == [0, 0, 0, 0, 0, -1, -1, -1, -1, -1, 1, 1]


def test_grow_into_margins_takes_only_the_rim():
    from segment_leaves_3d import grow_into_margins

    # a row of 10 vertices 1 apart: leaf 0 on the first two, leaf 1 on the last one, the rest unlabeled
    vertices = np.c_[np.arange(10.0), np.zeros(10), np.zeros(10)]
    faces = np.array([[i, i + 1, i + 1] for i in range(9)])
    labels = np.array([0, 0, -1, -1, -1, -1, -1, -1, -1, 1])
    grown = grow_into_margins(labels, vertices, faces, max_dist=2.5)
    assert grown.tolist() == [0, 0, 0, 0, -1, -1, -1, 1, 1, 1]


def test_reassign_stray_pieces_moves_only_small_detached_pieces():
    from segment_leaves_3d import reassign_stray_pieces

    # a strip of triangles: leaf 0, then a smear of leaf 0 inside leaf 1, then an isolated bit of leaf 1
    faces = np.array([[i, i + 1, i + 2] for i in range(12)])
    labels = np.array([0, 0, 0, 0, 1, 1, 0, 1, 1, 1, -1, -1, 1, -1])
    out = reassign_stray_pieces(labels, faces, max_size=3)
    assert out.tolist() == [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1]
    assert reassign_stray_pieces(labels, faces, max_size=1).tolist() == labels.tolist()  # too large to move


def test_leaf_axis_follows_a_bent_strip():
    from leaf_axes import leaf_axis, rosette_center, section_is_plausible, trim_section, up_direction

    # an L-shaped strip 2 wide (9 vertices across): 9 units along +x, then 10 units going up in z
    rows = [(x, 0.0) for x in np.arange(0, 9.01, 0.25)] + [(9.0, z) for z in np.arange(0.25, 10.01, 0.25)]
    w = 9
    vertices = np.array([[x, y, z] for x, z in rows for y in np.linspace(-1, 1, w)])
    faces = np.array([f for r in range(len(rows) - 1) for c in range(w - 1) for f in
                      ([w * r + c, w * r + c + 1, w * r + w + c], [w * r + c + 1, w * r + w + c + 1, w * r + w + c])])
    polyline, tip, sections, ratios = leaf_axis(vertices, faces, np.ones(len(vertices), bool), np.array([-1.0, 0.0, 0.0]))
    assert vertices[tip][2] == 10 and abs(vertices[tip][1]) <= 0.25  # tip in the middle of the far end
    assert np.abs(polyline[:, 1]).max() < 0.3  # axis centered
    assert polyline[len(polyline) // 2][0] > 7  # the axis goes around the bend, not straight to the tip
    widths = np.array([s["width"] for s in sections])
    # 2 wide everywhere; the slab of a section cut right at the 90-degree bend also catches the other leg
    assert len(widths) >= 10 and abs(np.median(widths) - 2) < 0.05 and widths.max() < 2.5
    assert len(ratios) >= len(sections) and np.median(ratios) < 1.2

    # a section is kept only about a straight axis and if not zigzagging
    x, o = np.array([1.0, 0.0, 0.0]), np.zeros(3)
    straight = np.array([[0, -1.0, 0], [0, 0, 0], [0, 1.0, 0]])
    assert section_is_plausible(straight, -x, o, x)
    # a lopsided one is cut back on its long side, whichever end it is
    lopsided = np.array([[0, 2.5, 0], [0, 1.5, 0], [0, 0, 0], [0, -1.0, 0]])
    assert np.allclose(trim_section(lopsided, o, 1.0), [[0, -1.0, 0], [0, 0, 0], [0, 1.0, 0]])
    assert not section_is_plausible(straight, -x, o, np.array([0.0, 0.0, 1.0]))  # axis turns by 90 degrees
    assert not section_is_plausible(np.array([[0, -1.0, 0], [0, 0, 2.0], [0, 1.0, 0]]), -x, o, x)  # zigzag

    # two straight leaves along x and y cross at the origin
    line = np.linspace(1, 5, 50)
    pts = np.concatenate([np.c_[line, 0 * line, 0 * line], np.c_[0 * line, line, 0 * line]])
    assert np.allclose(rosette_center(pts, np.repeat([0, 1], 50), min_size=10), 0, atol=1e-9)
    # the mesh lies lower right under the crossing point: the center drops onto it
    pts = np.concatenate([pts, [[0.0, 0.0, -1.0]] * 5])
    labels, up = np.r_[np.repeat([0, 1], 50), [-1] * 5], np.array([0.0, 0.0, 1.0])
    assert np.allclose(rosette_center(pts, labels, up, min_size=10), [0, 0, -1], atol=1e-9)
    assert up_direction(pts, np.array([[0.0, 0.0, 9.0]])) @ up > 0.99


def test_leaf_traits_of_a_flat_strip():
    from leaf_axes import leaf_axis
    from leaf_traits import blade_start, leaf_traits

    # narrow up to 0.3 then wide from 0.4: the limit is a quarter of the way up the step; a leaf wide from its base has none
    pos = np.linspace(0, 0.7, 8)
    assert abs(blade_start(pos, np.array([1, 1, 1, 1, 3, 3, 3, 3.0])) - 0.325) < 1e-9
    assert np.isnan(blade_start(pos, np.array([2.5, 2.6, 2.8, 3, 3, 3, 2.9, 2.0])))

    # a flat strip 10 long and 2 wide along +x, starting 1 away from the center
    xs, ys = np.arange(1, 11.01, 0.25), np.linspace(-1, 1, 9)
    vertices = np.array([[x, y, 0.0] for x in xs for y in ys])
    w = len(ys)
    faces = np.array([f for r in range(len(xs) - 1) for c in range(w - 1) for f in
                      ([w * r + c, w * r + w + c, w * r + c + 1], [w * r + c + 1, w * r + w + c, w * r + w + c + 1])])
    mask, center, up = np.ones(len(vertices), bool), np.zeros(3), np.array([0.0, 0.0, 1.0])
    polyline, _, sections, _ = leaf_axis(vertices, faces, mask, center)
    leaf = {"id": 0, "axis": polyline.tolist(), "cross_sections": sections, "length_from_center": 11.0}
    row, positions, widths = leaf_traits(vertices, faces, mask, leaf, center, up)
    assert abs(row["area"] - 20) < 1e-9 and abs(row["max_width"] - 2) < 0.1
    assert 9 < row["length"] < 10.5 and row["straightness"] > 0.9 and abs(row["inclination_deg"]) < 1e-6
    assert len(positions) == len(widths) == row["n_sections"]


def test_rig_scale_recovers_the_scale_of_a_moved_rig():
    from leaf_traits import rig_scale
    rng = np.random.default_rng(0)
    ref = {f"cam_{i}": p for i, p in enumerate(rng.normal(size=(10, 3)))}
    angle = 0.7
    rot = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    moved = {k: 1.25 * rot @ p + [3, -1, 2] for k, p in ref.items()}
    del moved["cam_3"]  # a camera missing in one acquisition
    assert np.isclose(rig_scale(moved, ref), 1 / 1.25)


def test_bh_adjust_matches_hand_computation():
    from compare_groups import bh_adjust

    q = bh_adjust([0.01, 0.04, np.nan, 0.03, 0.5])
    # 4 finite p-values: 0.01*4/1, then 0.03*4/2 = 0.06 and 0.04*4/3 = 0.0533 -> monotone min 0.0533, 0.5*4/4
    assert np.allclose(q[[0, 1, 3, 4]], [0.04, 0.16 / 3, 0.16 / 3, 0.5]) and np.isnan(q[2])


def test_compare_separates_shifted_groups():
    from compare_groups import compare

    rows = [{"group": "a", "x": v, "y": 1.0} for v in range(6)] + [{"group": "b", "x": v + 10, "y": 1.0} for v in range(6)]
    by_trait = {r["trait"]: r for r in compare(rows, ["a", "b"], ["x", "y"])}
    assert by_trait["x"]["p"] < 0.01 and by_trait["x"]["median_b"] == 12.5
    assert by_trait["y"]["p"] == 1  # constant trait: no difference
    assert np.isnan(compare(rows + [{"group": "c", "x": 0.0, "y": 1.0}] * 2, ["a", "b", "c"], ["y"])[0]["p"])  # Kruskal: not tested


def test_sizes_in_pixels_ignore_mesh_density_and_scale(tmp_path):
    from mesh_io import vertex_areas
    from reproject_check import pixel_footprint

    xml = tmp_path / "cameras.xml"
    xml.write_text(CAMERAS_XML)
    cameras = load_cameras(xml)[0]
    # unit square, then the same square subdivided and the whole scene scaled by 3: same area in pixels
    coarse = vertex_areas(VERTICES, FACES).sum() / pixel_footprint(VERTICES, cameras) ** 2
    grid = np.array([[x, y, 0.0] for y in np.linspace(0, 1, 5) for x in np.linspace(0, 1, 5)])
    faces = np.array([f for r in range(4) for c in range(4) for f in ([5 * r + c, 5 * r + c + 1, 5 * r + c + 5],
                                                                       [5 * r + c + 1, 5 * r + c + 6, 5 * r + c + 5])])
    scaled = [{**cam, "world_to_cam": np.diag([1, 1, 1, 1 / 3]) @ cam["world_to_cam"] @ np.diag([1, 1, 1, 3])}
              for cam in cameras]  # the same rig around the scaled scene: camera translation times 3
    fine = vertex_areas(3 * grid, faces).sum() / pixel_footprint(3 * grid, scaled) ** 2
    assert np.isclose(vertex_areas(VERTICES, FACES).sum(), 1) and np.isclose(coarse, fine)
