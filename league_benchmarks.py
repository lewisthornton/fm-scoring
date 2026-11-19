"""Competition detection and aggregate-only positional league benchmarks."""
from collections import Counter, defaultdict
from datetime import date
import math


MIN_LEAGUE_CLUBS = 8
MIN_SAMPLE = 20
MIN_CONTRIBUTING_CLUBS = 4
MIN_ATTRIBUTE_COVERAGE = 0.75
REFRESH_DAYS = 30
SEASON_GRACE_DAYS = 31


def identifier(value):
    value = str(value) if value is not None else ""
    return str(int(value)) if value.isascii() and value.isdecimal() and len(value) <= 20 else None


def game_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def unavailable(reason, **extra):
    return {"status": "unavailable", "reason": reason, **extra}


def detect_competition(managed_uid, nation_id, clubs, competitions, tables, fixtures, observed_date,
                       *, override=None, names=None, nation_database_id=None, nation_code=None):
    """Join live tables, domestic first teams and dated managed fixtures.

    fmsave does not expose a reliable league/cup discriminator or current
    season on a live table. Require corroboration and refuse ambiguous cases.
    """
    today = game_date(observed_date)
    if today is None or identifier(nation_id) is None:
        return unavailable("missing_game_date_or_managed_league_nation")
    managed_uid, nation_id = identifier(managed_uid), identifier(nation_id)
    club_records = defaultdict(list)
    for club in clubs:
        uid = identifier(club.get("uid"))
        if uid is not None:
            club_records[uid].append(club)
    domestic = {uid for uid, records in club_records.items()
                if len(records) == 1 and identifier(records[0].get("nation_id")) == nation_id}
    if managed_uid not in domestic:
        return unavailable("managed_club_missing_from_nation_export")
    by_id = defaultdict(list)
    for comp in competitions:
        key = identifier(comp.get("id"))
        if key is not None:
            by_id[key].append(comp)
    groups, invalid, unresolved = defaultdict(set), set(), False
    for table in tables:
        rows = table.get("rows")
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        ids = [identifier(row.get("club_uid")) for row in rows]
        comp = identifier(table.get("competition_id"))
        supplied_count = table.get("club_count")
        valid = ((supplied_count is None or identifier(supplied_count) == str(len(rows)))
                 and len(set(ids)) == len(ids) and all(uid in domestic for uid in ids)
                 and all(identifier(row.get("team_slot")) == "0" for row in rows))
        if not valid:
            if comp is not None:
                invalid.add(comp)
            continue
        if comp is None:
            unresolved |= managed_uid in ids and len(ids) >= MIN_LEAGUE_CLUBS
            continue
        groups[comp].update(ids)

    # The saved season_start_year field is authoritative for each fixture;
    # dates establish which of those seasons is plausibly current.
    calendars = defaultdict(list)
    for fixture in fixtures:
        comp = identifier(fixture.get("competition_id"))
        year = identifier(fixture.get("season_start_year"))
        played = game_date(fixture.get("date"))
        home = identifier(fixture.get("home_club_uid"))
        away = identifier(fixture.get("away_club_uid"))
        if (comp is None or year is None or played is None or
                identifier(fixture.get("home_team_slot")) != "0" or
                identifier(fixture.get("away_team_slot")) != "0" or
                managed_uid not in (home, away)):
            continue
        if not 1 <= int(year) <= 9999 or played.year not in (int(year), int(year) + 1):
            continue
        opponent = away if home == managed_uid else home
        calendars[(comp, int(year))].append((played, opponent))

    candidates = []
    for comp, members in sorted(groups.items()):
        if comp in invalid or managed_uid not in members or len(members) < MIN_LEAGUE_CLUBS:
            continue
        if len(by_id[comp]) != 1:
            continue
        for (fixture_comp, season), calendar in sorted(calendars.items()):
            if fixture_comp != comp:
                continue
            dates = sorted(d for d, _ in calendar)
            opponents = {uid for _, uid in calendar}
            if not opponents <= members - {managed_uid} or len(opponents) < 4:
                continue
            gap = max((dates[0] - today).days, (today - dates[-1]).days, 0)
            if gap > SEASON_GRACE_DAYS:
                continue
            record = by_id[comp][0]
            database_id = identifier(record.get("database_id"))
            mapped = (names or {}).get(database_id)
            exported_name = record.get("name")
            name = mapped or exported_name or f"Competition {'database ID ' + database_id if database_id else 'save ID ' + comp}"
            candidates.append({
                "competition": {"id": comp, "database_id": database_id, "display_name": name,
                                "name_source": "manual_name_map" if mapped else "fmsave" if exported_name else "identifier_label",
                                "league_nation_id": nation_id, "league_nation_database_id": nation_database_id,
                                "league_nation_code": nation_code},
                "season_start_year": season, "club_uids": sorted(members),
                "evidence": {"fixture_count": len(calendar), "opponent_count": len(opponents),
                             "first_fixture_date": dates[0].isoformat(), "last_fixture_date": dates[-1].isoformat()},
            })
    options = [{"id": c["competition"]["id"], "season_start_year": c["season_start_year"]} for c in candidates]
    if override is not None:
        selected = [c for c in candidates if c["competition"]["id"] == identifier(override)]
        method = "manual_override"
        if len(selected) != 1:
            return unavailable("override_not_uniquely_supported_by_current_evidence", candidates=options)
    else:
        selected = candidates
        method = "automatic"
        if unresolved or len(selected) != 1:
            return unavailable("ambiguous_competition_or_season" if unresolved or selected else
                               "no_corroborated_current_domestic_league", candidates=options)
    return {"status": "available", "reason": None, **selected[0], "method": method,
            "candidates": options}


def quantile(values, probability):
    """Linear interpolation at (n-1)*p on the sorted empirical observations."""
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def percentile(histogram, score):
    """Empirical midrank percentile: equal scores count as half."""
    n = sum(count for _, count in histogram)
    if not n:
        return None
    below = sum(count for value, count in histogram if value < score)
    equal = sum(count for value, count in histogram if value == score)
    return 100 * (below + equal / 2) / n


def familiarity(evidence, codes):
    ratings = [evidence[code]["rating"] for code in codes]
    if any(rating is not None and rating >= 15 for rating in ratings):
        return "confirmed"
    return "unknown" if any(rating is None for rating in ratings) else "below_threshold"


def aggregate_reference(rows, club_uids, model, profile_codes, *, evidence_for, attrs_for, scorer):
    """Aggregate first-team registered players only; no player identities leave this function."""
    members = set(club_uids)
    groups = defaultdict(list)
    unknown_team = missing_uid = 0
    for row in rows:
        if identifier(row.get("club_uid")) not in members:
            continue
        slot = identifier(row.get("team_slot"))
        if slot is None:
            unknown_team += 1
            continue
        if slot != "0":
            continue
        uid = identifier(row.get("uid"))
        if uid is None:
            missing_uid += 1
            continue
        groups[uid].append(row)
    duplicates = sum(len(group) for group in groups.values() if len(group) != 1)
    profiles = {"GK": model["gk"], **model["outfield"]}
    counts = {profile: Counter() for profile in profiles}
    scores = {profile: [] for profile in profiles}
    eligible_clubs = {profile: set() for profile in profiles}
    scored_clubs = {profile: set() for profile in profiles}
    population = 0
    population_clubs = set()
    for group in groups.values():
        if len(group) != 1:
            continue
        row = group[0]
        population += 1
        club = identifier(row["club_uid"])
        population_clubs.add(club)
        evidence = evidence_for(row)
        gk = evidence["gk"]["rating"]
        attrs = attrs_for(row)
        # No category-only or malformed goalkeeper rating determines type.
        applicable = {"GK": profiles["GK"]} if gk is not None and gk >= 18 else model["outfield"]
        weighted = scorer(attrs, applicable) if gk is not None else {}
        for profile in profiles:
            count = counts[profile]
            if gk is None:
                count["unknown_type"] += 1
            elif profile not in applicable:
                count["incompatible_type"] += 1
            else:
                fit = familiarity(evidence, profile_codes[profile])
                if fit != "confirmed":
                    count[fit] += 1
                    continue
                count["eligible"] += 1
                eligible_clubs[profile].add(club)
                score = weighted.get(profile)
                if score is None:
                    count["missing_attributes"] += 1
                    continue
                scores[profile].append(score)
                scored_clubs[profile].add(club)
    result = {}
    for profile, values in scores.items():
        count = counts[profile]
        n = len(values)
        coverage = n / count["eligible"] if count["eligible"] else None
        reasons = []
        if n < MIN_SAMPLE:
            reasons.append("insufficient_players")
        if len(scored_clubs[profile]) < MIN_CONTRIBUTING_CLUBS:
            reasons.append("insufficient_clubs")
        if coverage is None or coverage < MIN_ATTRIBUTE_COVERAGE:
            reasons.append("insufficient_attribute_coverage")
        result[profile] = {
            "status": "unavailable" if reasons else "available", "reasons": reasons,
            "sample_size": n, "contributing_clubs": len(scored_clubs[profile]),
            "eligible_clubs": len(eligible_clubs[profile]), "eligible_players": count["eligible"],
            "missing_attributes": count["missing_attributes"], "unknown_familiarity": count["unknown"],
            "below_familiarity": count["below_threshold"], "unknown_type": count["unknown_type"],
            "incompatible_type": count["incompatible_type"], "attribute_coverage": coverage,
            "median": quantile(values, 0.5) if not reasons else None,
            "p25": quantile(values, 0.25) if not reasons else None,
            "p75": quantile(values, 0.75) if not reasons else None,
            "p90": quantile(values, 0.9) if not reasons else None,
            "histogram": [[value, frequency] for value, frequency in sorted(Counter(values).items())],
            "warnings": [warning for condition, warning in (
                (count["unknown_type"] > 0, "unknown_player_type_excluded"),
                (count["unknown"] > 0, "unknown_familiarity_excluded"),
                (count["missing_attributes"] > 0, "incomplete_attribute_profiles_excluded"),
            ) if condition],
        }
    return {"status": "available" if any(p["status"] == "available" for p in result.values()) else "insufficient_samples",
            "population": population, "league_clubs": len(members), "population_clubs": len(population_clubs),
            "unknown_team_slot": unknown_team,
            "missing_player_uid": missing_uid, "duplicate_player_rows": duplicates, "profiles": result}


def reuse_reference(cache, detection, model_hash, observed_date):
    """Reuse aggregate only within the same competition, season, clubs and model."""
    if not cache or cache.get("version") != 1 or cache.get("status") != "available" or cache.get("model_sha256") != model_hash:
        return None
    previous = cache["detection"]
    if cache["reference"].get("status") != "available":
        return None
    if any(previous[key] != detection[key] for key in ("competition", "season_start_year", "club_uids")):
        return None
    current, extracted = game_date(observed_date), game_date(cache.get("extraction_game_date"))
    if current is None or extracted is None or not 0 <= (current - extracted).days < REFRESH_DAYS:
        return None
    return cache["reference"]


def build_report(cache, people, career, observed_date, model_hash, profile_codes, evidence_for):
    """Compare scoped players only; stale or mismatched caches fail closed."""
    report = {"version": 1, "career": career, "game_date": observed_date,
              "scoring_model": {"name": "fm27v2.toml", "sha256": model_hash},
              "criteria": {"current_club": "detected_league", "team_slot": 0, "position_minimum": 15,
                           "exact_numeric_familiarity": True, "min_sample": MIN_SAMPLE,
                           "min_contributing_clubs": MIN_CONTRIBUTING_CLUBS,
                           "min_attribute_coverage": MIN_ATTRIBUTE_COVERAGE, "refresh_game_days": REFRESH_DAYS},
              "source": "temporary fmsave export", "competition": None, "season_start_year": None,
              "extraction_game_date": None, "reference": None, "comparisons": [], "warnings": []}
    if not isinstance(cache, dict) or not cache:
        report.update(unavailable("benchmark_not_captured"))
    elif cache.get("version") != 1:
        report.update(unavailable("unsupported_benchmark_cache_version"))
    elif cache.get("observed_game_date") != observed_date:
        report.update(unavailable("benchmark_detection_date_mismatch"))
    elif cache.get("model_sha256") != model_hash:
        report.update(unavailable(cache.get("reason") or "benchmark_model_mismatch"))
    elif cache.get("status") != "available":
        report.update(unavailable(cache["reason"], detection=cache.get("detection")))
    else:
        detection = cache["detection"]
        report.update(status="available", reason=None, competition=detection["competition"],
                      season_start_year=detection["season_start_year"], detection=detection,
                      extraction_game_date=cache["extraction_game_date"], reference=cache["reference"],
                      provenance=cache["provenance"])
        report["warnings"].append("competition_inferred_from_live_tables_and_fixtures")
        if detection["competition"]["name_source"] == "identifier_label":
            report["warnings"].append("competition_display_name_unavailable")
    if isinstance(cache, dict) and "provenance" in cache:
        report["provenance"] = cache["provenance"]
    for person in sorted(people, key=lambda p: p["player_id"]):
        evidence = evidence_for(person["raw"])
        gk = evidence["gk"]["rating"]
        for profile, codes in profile_codes.items():
            score = person["scores"].get(profile)
            fit = familiarity(evidence, codes)
            distribution = report["reference"]["profiles"].get(profile) if report["reference"] else None
            reason = (report["reason"] if report["status"] != "available" else
                      "unknown_player_type" if gk is None else
                      "incompatible_player_type" if (profile == "GK") != (gk >= 18) else
                      "missing_attribute_profile_score" if score is None else
                      "position_familiarity_not_confirmed" if fit != "confirmed" else
                      "insufficient_reference_sample" if distribution["status"] != "available" else None)
            report["comparisons"].append({
                "player_id": person["player_id"], "profile": profile, "attribute_profile_score": score,
                "position_familiarity": fit, "status": "unavailable" if reason else "available", "reason": reason,
                "sample_size": distribution["sample_size"] if distribution else None,
                "competition_id": report["competition"]["id"] if report["competition"] else None,
                "season_start_year": report["season_start_year"],
                "league_median": distribution["median"] if distribution else None,
                "difference_from_median": score - distribution["median"] if not reason else None,
                "percentile": percentile(distribution["histogram"], score) if not reason else None,
                "warnings": (distribution["warnings"] if distribution else []) +
                            (["reference_extracted_on_earlier_game_date"] if report["extraction_game_date"] and
                             report["extraction_game_date"] != observed_date else []),
            })
    return report
