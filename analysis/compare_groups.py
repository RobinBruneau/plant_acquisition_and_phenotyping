"""Compare plant and leaf traits between groups (e.g. control vs treated).

Usage (conda env `phenotyping`):
    python compare_groups.py GROUP [GROUP ...] --out-dir OUT_DIR

Each GROUP is a group folder processed by run_group.py (its results/ is read) or directly a folder
holding plant_traits.csv and leaf_traits.csv; the group is named after the folder. The statistical unit
is the plant: leaf traits are first reduced to their median per plant over the leaves of at least
MIN_LEAF_AREA_PX2 of mesh (testing leaves directly would count the leaves of one plant as independent
samples). Each trait is then tested across groups, Mann-Whitney U for two groups, Kruskal-Wallis for more,
both two-sided, and the p-values are adjusted for the number of traits (Benjamini-Hochberg, q).
With a handful of plants per group only large differences can reach significance: read the medians too.
Written to OUT_DIR:
    plant_table.csv        one row per plant: group, plant traits and per-plant leaf medians
    group_comparison.csv   one row per trait: n and median per group, test, p, q (sorted by p)
    group_comparison.png   value per plant for each trait, by group, most different traits first
"""
import argparse
import csv
import warnings
from pathlib import Path

import numpy as np
from scipy import stats

from leaf_traits import GRID, INK, INK_SOFT, MIN_LEAF_AREA_PX2, SURFACE, style, write_csv

# per-plant medians of length, max_width and inclination_deg are already in plant_traits.csv
LEAF_TRAITS = ["area", "aspect_ratio", "area_fill", "straightness", "max_width_position", "blade_start_position",
               "petiole_length_from_width"]
NOT_TRAITS = {"acquisition", "rig_reference", "rig_scale"}
GROUP_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]  # fixed categorical order


def read_csv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def to_float(value):
    try:
        return float(value)
    except ValueError:
        return np.nan


def plant_table(results_dir, group):
    """One dict per plant: group, acquisition, rig_reference, then trait -> float."""
    leaves = read_csv(results_dir / "leaf_traits.csv")
    rows = []
    for plant in read_csv(results_dir / "plant_traits.csv"):
        row = {"group": group, "acquisition": plant["acquisition"], "rig_reference": plant.get("rig_reference", "")}
        row.update({k: to_float(v) for k, v in plant.items() if k not in NOT_TRAITS})
        mine = [r for r in leaves if r["acquisition"] == plant["acquisition"] and float(r["size_px2"]) >= MIN_LEAF_AREA_PX2]
        for trait in LEAF_TRAITS:
            values = np.array([to_float(r[trait]) for r in mine])
            row[f"leaf_median_{trait}"] = np.nanmedian(values) if np.isfinite(values).any() else np.nan
        rows.append(row)
    return rows


def bh_adjust(p):
    """Benjamini-Hochberg q-values of an array of p-values (nan stays nan and is not counted)."""
    p = np.asarray(p, dtype=float)
    q = np.full(len(p), np.nan)
    ok = np.flatnonzero(np.isfinite(p))
    order = ok[np.argsort(p[ok])]
    ranked = p[order] * len(ok) / np.arange(1, len(ok) + 1)
    q[order] = np.minimum(np.minimum.accumulate(ranked[::-1])[::-1], 1)
    return q


def compare(rows, groups, traits):
    """One result dict per trait, sorted by p."""
    results = []
    for trait in traits:
        samples = [np.array([r[trait] for r in rows if r["group"] == g]) for g in groups]
        samples = [s[np.isfinite(s)] for s in samples]
        p = np.nan
        if all(len(s) >= 2 for s in samples):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    p = (stats.mannwhitneyu(*samples).pvalue if len(groups) == 2 else stats.kruskal(*samples).pvalue)
                except ValueError:  # all values identical
                    p = np.nan
        result = {"trait": trait, "test": "mann_whitney_u" if len(groups) == 2 else "kruskal_wallis", "p": p}
        for g, s in zip(groups, samples):
            result[f"n_{g}"] = len(s)
            result[f"median_{g}"] = np.median(s) if len(s) else np.nan
        results.append(result)
    for result, q in zip(results, bh_adjust([r["p"] for r in results])):
        result["q"] = q
    return sorted(results, key=lambda r: (not np.isfinite(r["p"]), r["p"]))


def save_figure(rows, groups, results, out_path, note):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cols = 4
    grid = (-(-len(results) // cols), cols)
    fig, axs = plt.subplots(*grid, figsize=(3.4 * cols, 2.9 * grid[0]), facecolor=SURFACE, squeeze=False)
    rng = np.random.default_rng(0)
    for ax, result in zip(axs.ravel(), results):
        for k, g in enumerate(groups):
            values = np.array([r[result["trait"]] for r in rows if r["group"] == g])
            values = values[np.isfinite(values)]
            ax.scatter(k + rng.uniform(-0.12, 0.12, len(values)), values, s=36,
                       color=GROUP_COLORS[k % len(GROUP_COLORS)], edgecolors=SURFACE, linewidths=1, zorder=3)
            if len(values):
                ax.hlines(np.median(values), k - 0.25, k + 0.25, color=INK, linewidth=2, zorder=4)
        ax.set_xticks(range(len(groups)), groups)
        ax.set_xlim(-0.6, len(groups) - 0.4)
        p, q = result["p"], result["q"]
        style(ax, result["trait"] + (f"\np = {p:.2g}, q = {q:.2g}" if np.isfinite(p) else "\nnot tested"))
    for ax in axs.ravel()[len(results):]:
        ax.set_visible(False)
    fig.suptitle(f"Traits per plant by group (line: median), {len(rows)} plants", x=0.01, ha="left", fontsize=13, color=INK)
    fig.text(0.01, 0.005, note, fontsize=8, color=INK_SOFT, wrap=True)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    fig.savefig(out_path, dpi=150)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("groups", type=Path, nargs="+")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    rows, groups = [], []
    for path in args.groups:
        path = path.resolve()
        results_dir = path if (path / "plant_traits.csv").is_file() else path / "results"
        if not (results_dir / "plant_traits.csv").is_file():
            parser.error(f"no plant_traits.csv in {path} or {path / 'results'}: run run_group.py first")
        group = path.name if results_dir == path / "results" else path.parent.name
        if group in groups:
            parser.error(f"two groups named {group}")
        groups.append(group)
        rows += plant_table(results_dir, group)
    if len(groups) < 2:
        parser.error("give at least two groups")

    references = {r["rig_reference"] for r in rows}
    note = (f"Statistical unit: the plant. Leaf traits: median per plant over leaves of at least {MIN_LEAF_AREA_PX2} "
            f"px2 of mesh. q: Benjamini-Hochberg over all traits. Units: uncalibrated mesh units of the rig reference.")
    if len(references) > 1:
        # lengths of groups rescaled to different references are not comparable
        print(f"WARNING: groups use different rig references {sorted(references)}; "
              "re-run run_group.py with the same --reference for all groups")
        note = "WARNING: different rig references, sizes not comparable. " + note

    traits = [k for k in rows[0] if k not in {"group", "acquisition", "rig_reference"}]
    results = compare(rows, groups, traits)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "plant_table.csv", rows)
    write_csv(args.out_dir / "group_comparison.csv", results)
    save_figure(rows, groups, results, args.out_dir / "group_comparison.png", note)
    print(f"{len(rows)} plants in {len(groups)} groups, {len(traits)} traits -> {args.out_dir}")
    for r in results[:5]:
        print(f"  {r['trait']:40s} p = {r['p']:.3g}  q = {r['q']:.3g}")


if __name__ == "__main__":
    main()
