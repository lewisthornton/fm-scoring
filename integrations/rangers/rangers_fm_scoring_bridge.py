#!/usr/bin/env python3
"""Read-only Rangers scoped SQLite -> fm-scoring CSV observations + recruitment dashboard.

Designed for fm_rangers_scoped.sqlite3 produced by rangers_autosave_watcher.py.
Never runs fmsave, reads game saves, or writes to the SQLite database.

Python 3.11+ standard library only.

  py rangers_fm_scoring_bridge.py --fm-scoring-root "C:\\...\\fm-scoring"
  py rangers_fm_scoring_bridge.py --fm-scoring-root "C:\\...\\fm-scoring" --watch
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
import html
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import tomllib
import webbrowser
from rangers_club import loan_state, rangers_ids

DEFAULT_DB = Path(__file__).resolve().parent / "fm_rangers_scoped.sqlite3"
DEFAULT_SLUG = "rangers-recruitment"
META = ["Name", "Club", "Age", "Left Foot", "Wage", "Transfer Value", "Loan", "Player ID"]
POSITION_CODES = {
    "GK": ("gk",),
    "FB": ("dl", "dr", "wbl", "wbr"),
    "CB": ("dc", "sw"),
    "6": ("dm", "mc"),
    "wing": ("aml", "amr", "ml", "mr"),
    "10": ("amc", "mc"),
    "9": ("stc",),
}
DISPLAY_POSITION = {"GK": "Goalkeeper", "FB": "Full-back / wing-back", "CB": "Centre-back", "6": "Defensive / central midfield", "wing": "Wide attacker", "10": "Attacking / central midfield", "9": "Striker"}


def log(text):
    print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {text}", flush=True)


def find_root(explicit: Path | None):
    if explicit is not None:
        p = explicit.expanduser().resolve()
        if not (p / "score.py").is_file() or not (p / "weights" / "fm27v2.toml").is_file():
            raise RuntimeError(f"Not an fm-scoring checkout with weights/fm27v2.toml: {p}")
        return p
    checkout = Path(__file__).resolve().parent.parent.parent
    if (checkout / "score.py").is_file() and (checkout / "weights" / "fm27v2.toml").is_file():
        return checkout
    # Windows normal and OneDrive-redirected Documents, plus a checkout beside the bridge.
    home = Path.home()
    candidates = [
        Path(__file__).resolve().parent / "fm-scoring",
        Path(__file__).resolve().parent.parent / "fm-scoring",
        home / "Documents" / "fm-scoring",
        home / "OneDrive" / "Documents" / "fm-scoring",
        Path.cwd() / "fm-scoring",
    ]
    if sys.platform == "win32":
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('MyDocuments')"],
                capture_output=True, text=True, timeout=8,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                candidates.insert(0, Path(proc.stdout.strip()) / "fm-scoring")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    for p in candidates:
        if (p / "score.py").is_file() and (p / "weights" / "fm27v2.toml").is_file():
            return p.resolve()
    raise RuntimeError("Can't find fm-scoring. Clone https://github.com/jamiebolden/fm-scoring, then pass --fm-scoring-root \"C:\\path\\to\\fm-scoring\".")


def load_checkout_module(root: Path, filename, label):
    """Load the exact module from the checkout selected for native rendering."""
    path = root / filename
    if not path.is_file():
        raise RuntimeError(f"{label} module missing: {path}. Update the selected fm-scoring checkout.")
    spec = importlib.util.spec_from_file_location(f"_fm_scoring_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {label.lower()} module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_weighted(root: Path):
    return load_checkout_module(root, "scoring.py", "Shared scoring").weighted


def formation_path(root, explicit):
    return explicit.expanduser().resolve() if explicit is not None else root / "formations" / "default.toml"


def get_database(dbpath: Path, career: str):
    """Consistent SQLite snapshot; does not create or modify an absent DB."""
    if not dbpath.is_file():
        raise RuntimeError(f"Scoped watcher database does not exist: {dbpath}")
    try:
        con = sqlite3.connect(dbpath.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        with con:
            con.execute("BEGIN")
            bound = None
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='career_club'").fetchone():
                bound = con.execute("SELECT club_uid FROM career_club WHERE career=?", (career,)).fetchone()
            rows = con.execute("""
                SELECT m.player_key, m.cohort, p.record_json, m.last_seen_game_date, m.source_export,
                       s.game_date AS record_game_date, s.game_build
                  FROM cohort_membership AS m
                  JOIN player_latest AS l
                    ON l.career=m.career AND l.player_key=m.player_key
                  JOIN player_versions AS p
                    ON p.snapshot_id=l.snapshot_id AND p.player_key=l.player_key
                  JOIN snapshots AS s ON s.id=p.snapshot_id
                 WHERE m.career=? AND m.active=1
            """, (career,)).fetchall()
        con.close()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Can't read expected scoped database tables in {dbpath}: {exc}") from exc
    if not rows:
        raise RuntimeError(f"No active squad or targets for career {career!r}. Run the autosave watcher first.")
    people = {}
    date = None
    sources = set()
    for row in rows:
        key = row["player_key"]
        if key not in people:
            try:
                record = json.loads(row["record_json"])
            except (ValueError, TypeError) as exc:
                raise RuntimeError(f"Invalid JSON for player {key}: {exc}") from exc
            people[key] = {"key": key, "raw": record, "cohorts": set(),
                           "player_id": json.dumps(["rangers", career, key], ensure_ascii=False, separators=(",", ":")),
                           "record_game_date": row["record_game_date"], "game_build": row["game_build"],
                           "last_seen_game_date": None}
        people[key]["cohorts"].add(row["cohort"])
        if row["last_seen_game_date"] and (not people[key]["last_seen_game_date"] or
                                          row["last_seen_game_date"] > people[key]["last_seen_game_date"]):
            people[key]["last_seen_game_date"] = row["last_seen_game_date"]
        if row["last_seen_game_date"] and (date is None or row["last_seen_game_date"] > date):
            date = row["last_seen_game_date"]
        if row["source_export"]:
            sources.add(Path(row["source_export"]).name)
    # Preserve human-readable names; disambiguate actual duplicate identities instead of merging.
    names = Counter(p["raw"].get("name", "") for p in people.values())
    legacy_ids = rangers_ids(p["raw"] for p in people.values() if "squad" in p["cohorts"])
    managed_uid = bound[0] if bound else next(iter(legacy_ids)) if len(legacy_ids) == 1 else None
    for person in people.values():
        raw = person["raw"]
        if not raw.get("name") or as_int(raw.get("age")) is None:
            raise RuntimeError(f"Missing name/age for matched player {person['key']}; review the watcher output")
        if names[raw["name"]] > 1:
            person["name"] = f"{raw['name']} [UID {raw.get('unique_id') or raw.get('uid')}]"
        else:
            person["name"] = raw["name"]
        person["loan_state"], person["availability"] = loan_state(raw, managed_uid) if "squad" in person["cohorts"] else ("unknown", "unknown")
    return list(people.values()), date or datetime.today().date().isoformat(), sorted(sources)


def as_int(x):
    try:
        return int(float(x)) if x not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None


def as_num(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None


def fm_attribute_name(name):
    """Convert fmsave's snake_case attributes to fm-scoring's display names.

    Generic title case misses mixed-case keys in the weights, such as
    'One on Ones' and 'Command of Area'.
    """
    return {
        "one_on_ones": "One on Ones",
        "command_of_area": "Command of Area",
    }.get(name, " ".join(w.capitalize() for w in name.split("_")))


def attributes(raw, canonical_names=None):
    out = {}
    for key, value in raw.items():
        if key.startswith("attributes_"):
            n = as_int(value)
            if n is not None and 1 <= n <= 20:
                name = fm_attribute_name(key[len("attributes_"):])
                # Prefer current model's exact spelling for case-only differences.
                if canonical_names is not None:
                    name = canonical_names.get(name.casefold(), name)
                # A few names are written as one token in fm-scoring weights.
                if name == "Teamwork" or name == "Team Work":
                    name = "Teamwork"
                out[name] = n
    return out


def is_keeper(raw):
    n = as_int(raw.get("positions_gk"))
    if n is not None:
        return n >= 18
    p = str(raw.get("natural_positions") or "").upper()
    return bool(re.search(r"\bGK\b", p))


def position_rating(raw, role):
    scores = [as_int(raw.get("positions_" + code)) for code in POSITION_CODES[role]]
    observed = [n for n in scores if n is not None]
    if observed:
        return max(observed)
    # Fallback only if fmsave flat position ratings weren't included in older records.
    natural = set(re.findall(r"[A-Z]+", str(raw.get("natural_positions") or "").upper()))
    accomplished = set(re.findall(r"[A-Z]+", str(raw.get("accomplished_positions") or "").upper()))
    codes = {c.upper() for c in POSITION_CODES[role]}
    return 18 if natural & codes else 15 if accomplished & codes else None


def score(attrs, weights, *, scorer=None):
    """Adapt the shared grouped scorer to a single optional score."""
    if not weights:
        return None
    if scorer is None:
        scorer = load_weighted(find_root(None))
    try:
        return scorer(attrs, {"score": weights}).get("score")
    except ZeroDivisionError:
        # Preserve the bridge's existing treatment of zero-total profiles.
        return None


def scored_people(people, model, *, scorer=None):
    if scorer is None:
        scorer = load_weighted(find_root(None))
    canonical_names = {name.casefold(): name for profile in [model["gk"], *model["outfield"].values()]
                       for name in profile}
    for person in people:
        raw = person["raw"]
        attrs = attributes(raw, canonical_names)
        keeper = is_keeper(raw)
        models = {"GK": model["gk"]} if keeper else model["outfield"]
        person["attrs"] = attrs
        person["keeper"] = keeper
        person["scores"] = {role: score(attrs, weights, scorer=scorer) for role, weights in models.items()}
        person["fit"] = {role: position_rating(raw, role) for role in models}
        state = str(raw.get("transfer_value_state") or "").strip().lower()
        person["valuation"] = as_num(raw.get("transfer_value")) if state in {"ok", "zero"} else None
        person["wage"] = as_num(raw.get("contract_wage"))
        person["age"] = as_int(raw.get("age"))
        person["club"] = raw.get("club_name") or ("Rangers" if "squad" in person["cohorts"] else "Unattached")
    return people


def fm_foot(raw):
    value = as_int(raw.get("left_foot"))
    if value is None:
        return ""
    if value >= 18:
        return "Very Strong"
    if value >= 15:
        return "Strong"
    if value >= 12:
        return "Fairly Strong"
    if value >= 8:
        return "Reasonable"
    if value >= 5:
        return "Fairly Weak"
    if value >= 3:
        return "Weak"
    return "Very Weak"


def fm_money(v, symbol):
    if v is None:
        return ""
    if v >= 1e9:
        return f"{symbol}{v/1e9:.2f}B"
    if v >= 1e6:
        return f"{symbol}{v/1e6:.2f}M"
    if v >= 1e3:
        return f"{symbol}{v/1e3:.2f}K"
    return f"{symbol}{v:.0f}"


def toml_literal(value):
    return json.dumps(value, ensure_ascii=False)


def write_atomic(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def csv_string(fieldnames, rows):
    import io
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def native_rows(records, symbol):
    attrs = sorted({a for person in records for a in person["attrs"]})
    rows = []
    for p in records:
        r = p["raw"]
        squad = "squad" in p["cohorts"]
        loan = {"incoming": "in", "outgoing": "out", "unknown": "unknown"}.get(p.get("loan_state"), "") if squad else ""
        rows.append({"Name": r["name"], "Player ID": p["player_id"], "Club": "Rangers" if squad else p["club"], "Age": p["age"], "Left Foot": fm_foot(r),
                     "Wage": fm_money(p["wage"], symbol) + " p/w" if p["wage"] is not None else "",
                     "Transfer Value": fm_money(p["valuation"], symbol), "Loan": loan,
                     **p["attrs"]})
    return META + attrs, rows


def write_native_files(fmroot, slug, people, date, symbol, weights):
    save_dir = fmroot / "saves" / slug
    if (fmroot / "saves" / slug / "world").exists():
        raise RuntimeError(f"Refusing to use {slug!r}: it already has a full-world import. Use a distinct --slug.")
    obs = save_dir / "obs"
    obs.mkdir(parents=True, exist_ok=True)
    squad = [p for p in people if "squad" in p["cohorts"]]
    targets = [p for p in people if "target" in p["cohorts"] and "squad" not in p["cohorts"]]
    if not squad:
        raise RuntimeError("Cannot generate fm-scoring pages with no Rangers squad")
    latest_batch = []
    wrote = 0
    for cohort, group in (("squad", squad), ("targets", targets)):
        for view, is_gk in (("outfield", False), ("gk", True)):
            selected = [p for p in group if p["keeper"] is is_gk and any(s is not None for s in p["scores"].values())]
            fname = f"{date}_{'rangers-scoped' if cohort == 'squad' else 'search-rangers-targets'}_{view}.csv"
            path = obs / fname
            # Remove an older same-date file if a cohort has become empty.
            if not selected:
                if path.exists():
                    path.unlink()
                continue
            columns, rows = native_rows(selected, symbol)
            write_atomic(path, csv_string(columns, rows))
            wrote += len(rows)
            if cohort == "targets":
                latest_batch.append(fname)
    (save_dir / "staff").mkdir(exist_ok=True)
    config_path = save_dir / "save.toml"
    desired = {"weights": "fm27v2", "managed_club": "Rangers", "short_name": "Rangers", "last_batch": latest_batch}
    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
        # This slug is dedicated to the bridge. Preserve any other user keys.
        for key, value in desired.items():
            replacement = f"{key} = {toml_literal(value)}"
            pattern = re.compile(r"^" + re.escape(key) + r"\s*=.*$", re.M)
            if pattern.search(text):
                text = pattern.sub(lambda _: replacement, text)
            else:
                text = text.rstrip() + "\n" + replacement + "\n"
    else:
        text = "# Generated by Rangers SQLite bridge. Save data remains local.\n"
        text += "\n".join(f"{k} = {toml_literal(v)}" for k, v in desired.items()) + "\n"
    write_atomic(config_path, text)
    return latest_batch, wrote


def ensure_config(fmroot, slug, symbol):
    path = fmroot / "config.toml"
    if not path.exists():
        home = Path.home()
        write_atomic(path, f"active_save = {toml_literal(slug)}\nscreenshots_dir = {toml_literal(str(home))}\ncurrency = {toml_literal(symbol)}\n")


def delta_breakdown(target, incumbent, weights):
    if incumbent is None:
        return []
    denom = sum(weights.values())
    if not denom:
        return []
    result = []
    for attr, weight in weights.items():
        a = target["attrs"].get(attr)
        b = incumbent["attrs"].get(attr)
        if a is not None and b is not None:
            effect = (a - b) * weight / denom
            result.append({"name": attr, "candidate": a, "starter": b, "effect": round(effect, 3)})
    return sorted(result, key=lambda x: abs(x["effect"]), reverse=True)[:8]


def dashboard_data(people, weights, date, source_files, symbol):
    squad = [p for p in people if "squad" in p["cohorts"]]
    targets = [p for p in people if "target" in p["cohorts"] and "squad" not in p["cohorts"]]
    roles = [*weights["outfield"], "GK"]
    result = {}
    for role in roles:
        familiar = [p for p in squad if p["scores"].get(role) is not None and (p["fit"].get(role) or 0) >= 15]
        group = [p for p in familiar if p["availability"] == "available"]
        uncertain = sorted((p for p in familiar if p["availability"] == "unknown"),
                           key=lambda p: p["scores"][role], reverse=True)
        incumbent = max(group, key=lambda p: p["scores"][role], default=None)
        candidates = []
        for t in targets:
            rated = t["scores"].get(role)
            if rated is None:
                continue
            uplift = rated - incumbent["scores"][role] if incumbent else None
            candidates.append({
                "uid": t["raw"].get("unique_id") or t["raw"].get("uid"),
                "name": t["name"], "club": t["club"], "age": t["age"],
                "score": round(rated, 3), "fit": t["fit"].get(role),
                "uplift": round(uplift, 3) if uplift is not None else None,
                "value": t["valuation"], "wage": t["wage"],
                "attributes": delta_breakdown(t, incumbent, {"GK": weights["gk"], **weights["outfield"]}[role]),
            })
        candidates.sort(key=lambda p: p["score"], reverse=True)
        result[role] = {
            "label": DISPLAY_POSITION.get(role, role),
            "incumbent": ({"name": incumbent["name"], "score": round(incumbent["scores"][role], 3),
                           "fit": incumbent["fit"].get(role)} if incumbent else None),
            "uncertain_incumbents": [{"name": p["name"], "score": round(p["scores"][role], 3),
                                      "fit": p["fit"][role]} for p in uncertain],
            "candidates": candidates,
        }
    return {"meta": {"date": date, "squad": len(squad), "targets": len(targets),
                     "source": ", ".join(source_files), "symbol": symbol,
                     "weights": "fm27v2.toml (from fm-scoring)"},
            "roles": result,
            "squad_availability": [{"name": p["name"], "key": p["key"], "club": p["club"],
                                    "loan_state": p["loan_state"], "availability": p["availability"]}
                                   for p in squad]}


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rangers | Recruitment intelligence</title>
<style>
:root{font-family:Inter,"Segoe UI",Arial,sans-serif;color-scheme:dark;--bg:#0e1420;--panel:#182333;--panel2:#202e40;--text:#ebf2fa;--dim:#a9b7c9;--line:#34465c;--blue:#67bdff;--green:#80e5b9;--red:#ff9999}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text)}.wrap{max-width:1280px;margin:auto;padding:28px 24px}header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}h1{margin:0;font-size:28px;letter-spacing:-.7px}h2{font-size:15px;margin:0 0 10px}.subtitle{color:var(--dim);margin:8px 0 0;font-size:14px}a{color:var(--blue)}.nav{display:flex;gap:10px;flex-wrap:wrap}.nav a{border:1px solid var(--line);border-radius:9px;text-decoration:none;padding:9px 13px;font-size:13px}.nav a:hover{background:var(--panel2)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:25px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:17px}.card .num{font-size:25px;font-weight:700;margin-top:7px}.muted{color:var(--dim)}.small{font-size:12px}.control{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:24px 0}.control label{display:flex;flex-direction:column;gap:7px;font-size:12px;color:var(--dim)}select,input[type=text]{background:var(--panel2);border:1px solid var(--line);border-radius:8px;color:var(--text);font:inherit;padding:10px 12px;min-width:180px}label.check{display:flex;flex-direction:row;align-items:center;gap:7px;min-height:40px}.columns{display:grid;grid-template-columns:1fr;gap:16px}.tablebox{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel)}table{width:100%;border-collapse:collapse;min-width:820px}td,th{border-bottom:1px solid #ffffff12;padding:12px 14px;text-align:left;font-size:13px;white-space:nowrap}th{color:var(--dim);font-weight:600;background:var(--panel2)}tbody tr:hover{background:#293b4e;cursor:pointer}.right{text-align:right;font-variant-numeric:tabular-nums}.positive{color:var(--green)}.negative{color:var(--red)}.pill{font-size:11px;padding:4px 7px;border-radius:6px;background:#293b4e}.notfit{color:var(--dim)}.info{background:var(--panel);padding:18px;border-radius:12px;border:1px solid var(--line);margin-bottom:12px}.footnote{font-size:12px;line-height:1.6;color:var(--dim);margin:20px 0}.detail{border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:18px;display:none}.detail.active{display:block}.line{display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px solid #ffffff12}.line .right{white-space:nowrap}.bar{width:100%;height:6px;background:#ffffff14;border-radius:5px;overflow:hidden;margin-top:5px}.bar>div{height:100%;background:#64b8e9}.key{color:var(--blue);font-weight:600}.error{color:var(--red)}.empty{padding:20px;color:var(--dim)}@media(max-width:700px){.wrap{padding:18px 12px}.cards{grid-template-columns:1fr 1fr}.control{gap:9px}h1{font-size:24px}select,input[type=text]{min-width:130px} .card{padding:12px}}
</style></head><body><div class="wrap">
<header><div><h1>Rangers <span class="muted">/ Recruitment</span></h1><p class="subtitle">Filtered FM27 candidates matched to your save · <span id="gameDate"></span></p></div><nav class="nav"><a href="squad.html">Rangers squad</a><a href="last.html">Latest targets</a><a href="players.html">All observed</a></nav></header>
<div class="cards"><div class="card"><div class="muted small">Rangers players</div><div class="num" id="squadCount">—</div></div><div class="card"><div class="muted small">Active filtered targets</div><div class="num" id="targetCount">—</div></div><div class="card"><div class="muted small">Position-qualified</div><div class="num" id="eligibleCount">—</div></div><div class="card"><div class="muted small">Above current best</div><div class="num" id="upgradeCount">—</div></div></div>
<p class="subtitle" id="availability"></p>
<div class="control"><label>Position <select id="role"></select></label><label>Sort by <select id="sort"><option value="uplift">Upgrade over Rangers player ↓</option><option value="score">Position score ↓</option><option value="value">Transfer value ↑</option><option value="wage">Weekly wage ↑</option><option value="age">Age ↑</option></select></label><label>Find player <input id="find" type="text" placeholder="Name or club"></label><label class="check"><input id="natural" type="checkbox" checked> Natural / accomplished only (15+)</label><label class="check"><input id="upgrade" type="checkbox"> Only upgrades</label></div>
<div class="info"><h2>Best available familiar Rangers player <span class="muted small" id="roleTitle"></span></h2><div id="incumbent"></div><p class="muted small" id="uncertainIncumbents"></p></div>
<div class="columns"><section class="tablebox"><table><thead><tr><th>Candidate</th><th>Club</th><th class="right">Age</th><th class="right">Role fit</th><th class="right">Score</th><th class="right">Upgrade</th><th class="right">Value*</th><th class="right">Wage/wk*</th></tr></thead><tbody id="candidates"></tbody></table><div id="empty" class="empty" style="display:none">No targets match these filters. Try unchecking natural/accomplished or changing position.</div></section><section class="detail" id="detail"><h2 id="detailTitle"></h2><div class="muted small" id="detailInfo"></div><div id="differences" style="margin-top:14px"></div></section></div>
<p class="footnote">*Money is read from the save's base units and is shown with the configured display symbol (check in-game before relying on it). Transfer value is <strong>not</strong> asking price. Position score is fm-scoring's weighted attribute mean (1–20), not a win-probability prediction. Role fit 18–20 = natural, 15–17 = accomplished; under 15 is a calculated attribute score at an unfamiliar position. This tool uses save-file true attributes (including potentially unscouted values), so it is not a fog-of-war-respecting scouting report. Target eligibility comes only from your most recently imported filtered F9 export, not an interest prediction.</p>
<p class="footnote" id="source"></p>
</div><script id="dataset" type="application/json">__PAYLOAD__</script><script>
"use strict";
const D=JSON.parse(document.getElementById('dataset').textContent);
const $=id=>document.getElementById(id);
const fmt=n=>n==null?'—':Number(n).toFixed(1);
function money(n){if(n==null)return '—';let s=D.meta.symbol;if(n>=1e9)return s+(n/1e9).toFixed(2)+'bn';if(n>=1e6)return s+(n/1e6).toFixed(2)+'m';if(n>=1e3)return s+(n/1e3).toFixed(1)+'k';return s+Math.round(n);}
function el(parent,tag,text,cls){const x=document.createElement(tag);if(text!=null)x.textContent=text;if(cls)x.className=cls;parent.appendChild(x);return x;}
function init(){const roles=Object.keys(D.roles);for(const role of roles){const o=el($('role'),'option',D.roles[role].label+' ('+role+')');o.value=role;}
$('role').value=D.roles['CB']?'CB':roles[0];$('squadCount').textContent=D.meta.squad;$('targetCount').textContent=D.meta.targets;$('gameDate').textContent=D.meta.date;$('source').textContent='Weight model: '+D.meta.weights+' · Target source: '+(D.meta.source||'not supplied');
const countAvailability=state=>D.squad_availability.filter(p=>p.availability===state).length;
$('availability').textContent='Club-level selection: '+countAvailability('available')+' available · '+countAvailability('unavailable')+' away on loan · '+countAvailability('unknown')+' unknown. Injury, suspension and registration eligibility are unverified.';
try{const v=JSON.parse(localStorage.getItem('fm:rangers:recruitment')||'{}');for(const k of ['role','sort','find'])if(v[k]!=null)$(k).value=v[k];for(const k of ['natural','upgrade'])if(v[k]!=null)$(k).checked=v[k];}catch(e){}
for(const id of ['role','sort','find','natural','upgrade'])$(id).addEventListener(id==='find'?'input':'change',()=>{try{localStorage.setItem('fm:rangers:recruitment',JSON.stringify(Object.fromEntries(['role','sort','find','natural','upgrade'].map(k=>[k,['natural','upgrade'].includes(k)?$(k).checked:$(k).value]))));}catch(e){}render();});render();}
function render(){const role=$('role').value,section=D.roles[role];$('roleTitle').textContent='('+role+')';const base=section.incumbent;$('incumbent').textContent=base?base.name+' · '+fmt(base.score)+' position score · '+(base.fit>=18?'Natural':base.fit>=15?'Accomplished':'Unfamiliar'):'No confirmed available natural/accomplished Rangers player; upgrades cannot be determined.';
$('uncertainIncumbents').textContent=section.uncertain_incumbents.length?'Availability unknown (excluded from uplift): '+section.uncertain_incumbents.map(p=>p.name+' ('+fmt(p.score)+')').join(', '):'';
let targets=section.candidates.filter(t=>(!$('natural').checked||t.fit>=15)&&(!$('upgrade').checked||(t.uplift!=null&&t.uplift>0))&&(t.name+' '+t.club).toLowerCase().includes($('find').value.trim().toLowerCase()));
const sort=$('sort').value;targets.sort((a,b)=>sort==='age'?((a.age??999)-(b.age??999)):sort==='value'||sort==='wage'?((a[sort]??Infinity)-(b[sort]??Infinity)):((b[sort]??-Infinity)-(a[sort]??-Infinity))||((b.score??0)-(a.score??0)));
$('eligibleCount').textContent=section.candidates.filter(t=>t.fit>=15).length;$('upgradeCount').textContent=section.candidates.filter(t=>t.fit>=15&&t.uplift!=null&&t.uplift>0).length;
const body=$('candidates');body.replaceChildren();$('empty').style.display=targets.length?'none':'block';$('detail').classList.remove('active');
for(const t of targets){const tr=el(body,'tr');el(tr,'td',t.name,'key');el(tr,'td',t.club);el(tr,'td',t.age??'—','right');const fit=t.fit==null?'Unknown':t.fit>=18?'Natural':t.fit>=15?'Accomplished':'Unfamiliar';el(tr,'td',fit,'right '+(t.fit<15?'notfit':''));el(tr,'td',fmt(t.score),'right');el(tr,'td',t.uplift==null?'—':(t.uplift>0?'+':'')+fmt(t.uplift),'right '+(t.uplift>0?'positive':t.uplift<0?'negative':''));el(tr,'td',money(t.value),'right');el(tr,'td',money(t.wage),'right');tr.addEventListener('click',()=>detail(t,base));}
}
function detail(t,base){$('detail').classList.add('active');$('detailTitle').textContent=t.name;$('detailInfo').textContent='Compared with '+(base?base.name+' ('+fmt(base.score)+')':'no familiar Rangers incumbent')+' · Score '+fmt(t.score);$('differences').replaceChildren();if(!t.attributes.length){el($('differences'),'div','No complete attribute comparison available.','muted');return;}for(const item of t.attributes){const row=el($('differences'),'div',null,'line');el(row,'div',item.name);el(row,'div',item.candidate+' vs '+item.starter+' · '+(item.effect>0?'+':'')+item.effect.toFixed(2)+' pts', 'right '+(item.effect>0?'positive':item.effect<0?'negative':''));}}
init();
// Static file: refresh periodically to pick up pages regenerated by the running bridge.
setInterval(()=>location.reload(),90000);
</script></body></html>'''


def render_html(data):
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace("<", "\\u003c").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return HTML.replace("__PAYLOAD__", raw)


def sync_once(args, root):
    path = args.db.expanduser().resolve()
    model_bytes = (root / "weights" / "fm27v2.toml").read_bytes()
    weights = tomllib.loads(model_bytes.decode("utf-8"))
    formation_module = load_checkout_module(root, "formation.py", "Tactical formation")
    selected_formation = formation_path(root, getattr(args, "formation", None))
    formation = formation_module.load_formation(selected_formation, weights)
    people, date, sources = get_database(path, args.career)
    scorer = load_weighted(root)
    scored_people(people, weights, scorer=scorer)
    assessment = load_checkout_module(root, "tactical_assessment.py", "Tactical assessment").build_assessments(
        formation, weights, people, codes=formation_module.FM_POSITION_CODES, scorer=scorer,
        career=args.career, formation_source=selected_formation.name,
        model_sha256=hashlib.sha256(model_bytes).hexdigest())
    keeper_squad = [p for p in people if p["keeper"] and "squad" in p["cohorts"]]
    keeper_targets = [p for p in people if p["keeper"] and "target" in p["cohorts"] and "squad" not in p["cohorts"]]
    unscored_keepers = [p["name"] for p in [*keeper_squad, *keeper_targets]
                         if p["scores"].get("GK") is None]
    if unscored_keepers:
        raise RuntimeError("Goalkeeper scoring incomplete (check attribute names/availability): "
                           + ", ".join(unscored_keepers[:8]))
    log(f"Goalkeepers: {len(keeper_squad)} Rangers, {len(keeper_targets)} active targets (all scoreable)")
    squad_total = sum("squad" in p["cohorts"] for p in people)
    target_total = sum("target" in p["cohorts"] and "squad" not in p["cohorts"] for p in people)
    if not squad_total:
        raise RuntimeError("No active Rangers squad in database")
    # Price units are unconverted fmsave values; a symbol is presentation only.
    batches, exported_rows = write_native_files(root, args.slug, people, date, args.currency, weights)
    ensure_config(root, args.slug, args.currency)
    report = dashboard_data(people, weights, date, sources, args.currency)
    outdir = root / "out" / args.slug
    write_atomic(outdir / "recruitment.html", render_html(report))
    # Use fm-scoring's own renderer so squad / players / last are native pages.
    cmd = [sys.executable, "score.py", "--save", args.slug]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        raise RuntimeError("Dashboard created, but fm-scoring's score.py failed: " + (proc.stderr or proc.stdout)[-1800:])
    write_atomic(outdir / "formation.json", json.dumps(formation, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    write_atomic(outdir / "tactical_assessments.json", json.dumps(assessment, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    log(f"Rangers {squad_total} · active targets {target_total} · exported scored rows {exported_rows} · date {date}")
    log(f"Dashboard: {outdir / 'recruitment.html'}")
    log(f"Formation: {formation['name']} · {outdir / 'formation.json'}")
    log(f"Tactical assessments: {outdir / 'tactical_assessments.json'}")
    if args.open:
        webbrowser.open((outdir / "recruitment.html").resolve().as_uri())
    return outdir / "recruitment.html"


def signatures(db: Path, weights: Path, formation: Path | None = None):
    signatures = []
    paths = [db, Path(str(db) + "-wal"), weights]
    if formation is not None:
        paths.append(formation)
    for p in paths:
        try:
            st = p.stat()
            signatures.append((st.st_size, st.st_mtime_ns))
        except FileNotFoundError:
            signatures.append(None)
    return tuple(signatures)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to scoped SQLite database")
    ap.add_argument("--fm-scoring-root", type=Path, help="Local jamiebolden/fm-scoring repository checkout")
    ap.add_argument("--career", default="rangers", help="Career key in scoped database")
    ap.add_argument("--slug", default=DEFAULT_SLUG, help="Dedicated local fm-scoring save name")
    ap.add_argument("--currency", default="£", help="Display symbol ONLY (does not convert save monetary units)")
    ap.add_argument("--formation", type=Path, help="Tactical TOML file (default: selected checkout's formations/default.toml)")
    ap.add_argument("--watch", action="store_true", help="Refresh continuously when SQLite database changes")
    ap.add_argument("--interval", type=float, default=15, help="Watch polling interval in seconds")
    ap.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    args = ap.parse_args(argv)
    if args.interval <= 0:
        ap.error("--interval must be positive")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", args.slug):
        ap.error("--slug must be a simple directory name")
    root = find_root(args.fm_scoring_root)
    args.formation = formation_path(root, args.formation)
    db = args.db.expanduser().resolve()
    weights = root / "weights" / "fm27v2.toml"
    if not args.watch:
        sync_once(args, root)
        return 0
    log("Watching read-only SQLite for Rangers changes; press Ctrl+C to stop")
    last = None
    while True:
        try:
            sig = signatures(db, weights, args.formation)
            if sig != last and sig[0] is not None:
                sync_once(args, root)
                last = sig
                # Only open a browser for the initial build, not on every autosave.
                args.open = False
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
            log("Sync failed; will retry: " + str(exc))
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            log("Stopped")
            return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, sqlite3.Error, OSError, ValueError) as e:
        log("ERROR: " + str(e))
        raise SystemExit(1)

