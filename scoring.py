"""Pure scoring mathematics for fm-scoring and its integrations.

Profiles and coefficients are supplied by callers, normally from the existing
weights TOML. Weighted positional scores require every named attribute.
The experimental outfield win index and goalkeeper points per season sum
observed contributions separately; neither is a calibrated match probability.
"""


def weighted(attrs, groups):
    """Each group's Σ(attribute × weight) / Σ(weights), for the groups whose attributes are all known."""
    return {key: sum(attrs[a] * x for a, x in w.items()) / sum(w.values())
            for key, w in groups.items() if all(a in attrs for a in w)}


def curve_value(points, x):
    """An attribute's win-rate value at level x: straight lines through (1, 6, 12, 18) = (*points[:2], 0, points[2])."""
    (x0, y0), (x1, y1) = ((1, points[0]), (6, points[1])) if x < 6 else ((6, points[1]), (12, 0)) if x < 12 else ((12, 0), (18, points[2]))
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def curve_scores(attrs, w):
    """Each [curve_scores.<label>]: Σ(curve value × weight/5) over the known attributes, as the level at which a player
    with all of them equal would be worth the same. Attributes not observed are left out."""
    out = {}
    for label, prof in w.get("curve_scores", {}).items():
        m = {a: prof.get(a, 5) / 5 for a in w["curve"] if a in attrs and prof.get(a, 5)}
        total = sum(x * curve_value(w["curve"][a], attrs[a]) for a, x in m.items())
        lo, hi = 1.0, 20.0
        for _ in range(30):  # the total rises with the level: bisect for it
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if sum(x * curve_value(w["curve"][a], mid) for a, x in m.items()) < total else (lo, mid)
        if m:
            out[label] = lo
    return out


def win_score(attrs, w):
    """%win: Σ [win] value at the player's level over their observed attributes (None without a [win] table)."""
    return sum(curve_value(pts, attrs[a]) for a, pts in w["win"].items() if a in attrs) if w.get("win") else None


PTS_LEVELS = (1, 8, 12, 16, 20)


def pts_value(points, x):
    """A keeper attribute's points per season at level x: straight lines through (1, 8, 12, 16, 20) = (*points[:2], 0, *points[2:])."""
    ys = (*points[:2], 0, *points[2:])
    i = next(i for i in range(1, 4) if x < PTS_LEVELS[i]) if x < 16 else 4
    (x0, y0), (x1, y1) = (PTS_LEVELS[i - 1], ys[i - 1]), (PTS_LEVELS[i], ys[i])
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def pts_score(attrs, w):
    """Keeper pts: Σ [gk_pts] value at the keeper's level over their observed attributes (None without a [gk_pts] table)."""
    return sum(pts_value(pts, attrs[a]) for a, pts in w["gk_pts"].items() if a in attrs) if w.get("gk_pts") else None
