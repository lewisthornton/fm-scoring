"""Invented competition, season and aggregate reference fixtures."""
import json
import tomllib
import unittest
from datetime import date, timedelta
from pathlib import Path

import formation
import league_benchmarks as league
import scoring
import tactical_assessment as tactical


ROOT = Path(__file__).resolve().parents[1]
MODEL = tomllib.loads((ROOT / "weights/fm27v2.toml").read_text(encoding="utf-8"))
CODES = {"GK": ("gk",), "FB": ("dl", "dr", "wbl", "wbr"), "CB": ("dc", "sw"),
         "6": ("dm", "mc"), "wing": ("aml", "amr", "ml", "mr"), "10": ("mc", "amc"), "9": ("stc",)}


def competition_fixture(comp="500", db_id="9000", season=2026, members=None):
    members = members or [str(i) for i in range(100, 112)]
    clubs = [{"uid": uid, "nation_id": "7"} for uid in members]
    competitions = [{"id": comp, "database_id": db_id, "name": ""}]
    tables = [{"competition_id": comp, "rows": [{"club_uid": uid, "team_slot": 0} for uid in members]}]
    fixtures = [{"competition_id": comp, "season_start_year": season,
                 "date": (date(season, 8, 1) + timedelta(days=index * 12)).isoformat(),
                 "home_club_uid": uid if away else "100", "away_club_uid": "100" if away else uid,
                 "home_team_slot": 0, "away_team_slot": 0, "stage_id": comp, "round": "", "round_code": ""}
                for index, (away, uid) in enumerate((away, uid) for away in (False, True) for uid in members[1:])]
    return clubs, competitions, tables, fixtures


def detect(fixture, when="2027-01-01", **kwargs):
    return league.detect_competition("100", "7", *fixture, when, **kwargs)


def evidence(raw):
    return tactical.position_evidence(raw, formation.FM_POSITION_CODES)


def reference_player(uid, club, value, *, keeper=False):
    attrs = {a: value for profile in [MODEL["gk"], *MODEL["outfield"].values()] for a in profile}
    return {"uid": str(uid), "club_uid": str(club), "team_slot": "0", "name": f"Private {uid}",
            "attrs": attrs, **{"positions_" + code: (20 if (code == "gk") == keeper else 1)
                               for code in formation.FM_POSITION_CODES}}


def aggregate(rows, clubs):
    return league.aggregate_reference(rows, clubs, MODEL, CODES, evidence_for=evidence,
                                      attrs_for=lambda row: row["attrs"], scorer=scoring.weighted)


class LeagueBenchmarkTests(unittest.TestCase):
    def test_scottish_detection_and_split_tables(self):
        clubs, comps, tables, fixtures = competition_fixture()
        all_rows = tables[0]["rows"]
        split = [{"competition_id": "500", "rows": all_rows[:6]},
                 {"competition_id": "500", "rows": all_rows[6:]}]
        result = detect((clubs, comps, split, fixtures), names={"9000": "Scottish Premiership (invented ID)"},
                        nation_database_id="793", nation_code="SCO")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["competition"]["id"], "500")
        self.assertEqual(result["competition"]["database_id"], "9000")
        self.assertEqual(result["competition"]["league_nation_code"], "SCO")
        self.assertEqual(result["competition"]["name_source"], "manual_name_map")
        self.assertEqual(result["season_start_year"], 2026)
        self.assertEqual(len(result["club_uids"]), 12)

    def test_different_competition_and_promotion_season_change(self):
        old = competition_fixture(comp="501", db_id="9001")
        new = competition_fixture(comp="500", db_id="9000", season=2027)
        clubs, comps, tables, fixtures = new
        combined = (clubs, old[1] + comps, old[2] + tables, old[3] + fixtures)
        result = detect(combined, "2027-09-01")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["competition"]["id"], "500")
        self.assertEqual(result["season_start_year"], 2027)
        self.assertEqual(detect(old)["competition"]["id"], "501")
        self.assertEqual(result["competition"]["name_source"], "identifier_label")
        cache = {"version": 1, "detection_policy": league.DETECTION_POLICY, "status": "available", "model_sha256": "m", "detection": detect(old),
                 "extraction_game_date": "2027-01-01", "reference": {"status": "available", "invented": True}}
        self.assertIsNone(league.reuse_reference(cache, result, "m", "2027-09-01"))
        self.assertEqual(league.reuse_reference(cache, detect(old), "m", "2027-01-20"), cache["reference"])
        self.assertIsNone(league.reuse_reference(cache, detect(old), "m", "2027-02-01"))
        self.assertIsNone(league.reuse_reference(cache, detect(old), "new-model", "2027-01-02"))

    def test_conflicting_or_missing_evidence_and_explicit_override(self):
        first = competition_fixture()
        second = competition_fixture(comp="501", db_id="9001")
        both = (first[0], first[1] + second[1], first[2] + second[2], first[3] + second[3])
        result = detect(both)
        self.assertEqual(result["reason"], "ambiguous_competition_or_season")
        selected = detect(both, override="501")
        self.assertEqual(selected["method"], "manual_override")
        self.assertEqual(selected["competition"]["id"], "501")
        self.assertEqual(len(selected["candidates"]), 2)
        self.assertEqual(detect(first, override="501")["reason"], "override_not_uniquely_supported_by_current_evidence")
        self.assertEqual(detect((first[0], first[1], first[2], []))["status"], "unavailable")
        unresolved = [{"competition_id": None, "rows": first[2][0]["rows"]}]
        self.assertEqual(detect((first[0], first[1], unresolved, first[3]))["status"], "unavailable")
        self.assertEqual(detect(first, "2030-01-01")["status"], "unavailable")

    def test_eight_team_cup_group_never_becomes_the_league(self):
        clubs, comps, tables, fixtures = competition_fixture(comp="600", members=[str(i) for i in range(100,108)])
        # Satisfies every old criterion, even with reciprocal season-length fixtures.
        for fixture in fixtures:
            fixture.update(round="UNKNOWN", round_code="42")
        cup = clubs, comps, tables, fixtures
        self.assertEqual(detect(cup)["reason"], "no_corroborated_current_domestic_league")
        self.assertEqual(detect(cup, override="600")["status"], "unavailable")
        # A missing or unresolved league cannot promote that cup to the baseline.
        genuine = competition_fixture()
        unresolved = {"competition_id": None, "rows": genuine[2][0]["rows"]}
        mixed = genuine[0], comps + genuine[1], tables + [unresolved], fixtures + genuine[3]
        self.assertEqual(detect(mixed)["status"], "unavailable")
        self.assertEqual(detect(mixed, override="600")["status"], "unavailable")
        resolved = genuine[0], comps + genuine[1], tables + genuine[2], fixtures + genuine[3]
        self.assertEqual(detect(resolved)["competition"]["id"], "500")
        self.assertEqual(detect(resolved, override="500")["method"], "manual_override")
        unresolved_split = {"competition_id": None, "rows": genuine[2][0]["rows"][:6]}
        self.assertEqual(detect((resolved[0], resolved[1], resolved[2] + [unresolved_split], resolved[3]))["status"], "unavailable")

    def test_roundless_cup_like_or_missing_metadata_fails_closed(self):
        clubs, comps, tables, fixtures = competition_fixture(members=[str(i) for i in range(100,108)])
        self.assertEqual(detect((clubs, comps, tables, fixtures[:7]), "2026-10-01")["status"], "unavailable")
        short = [dict(f, date=(date(2026,8,1)+timedelta(days=i*3)).isoformat()) for i,f in enumerate(fixtures)]
        self.assertEqual(detect((clubs, comps, tables, short), "2026-09-01")["status"], "unavailable")
        fixtures[0].pop("round_code")
        self.assertEqual(detect((clubs, comps, tables, fixtures))["status"], "unavailable")

    def test_genuine_league_in_another_career(self):
        clubs, comps, tables, fixtures = competition_fixture(comp="700", db_id="8000")
        def new_uid(uid):
            return str(int(uid) + 1000)
        clubs = [dict(c, uid=new_uid(c["uid"]), nation_id="9") for c in clubs]
        tables[0]["rows"] = [dict(row, club_uid=new_uid(row["club_uid"])) for row in tables[0]["rows"]]
        fixtures = [dict(f, home_club_uid=new_uid(f["home_club_uid"]), away_club_uid=new_uid(f["away_club_uid"])) for f in fixtures]
        result = league.detect_competition("1100", "9", clubs, comps, tables, fixtures, "2027-01-01")
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["competition"]["id"], "700")
        self.assertEqual(result["competition"]["league_nation_id"], "9")

    def test_non_domestic_and_youth_tables_rejected(self):
        clubs, comps, tables, fixtures = competition_fixture()
        clubs[-1]["nation_id"] = "8"
        self.assertEqual(detect((clubs, comps, tables, fixtures))["status"], "unavailable")
        clubs[-1]["nation_id"] = "7"
        tables[0]["rows"][-1]["team_slot"] = 1
        self.assertEqual(detect((clubs, comps, tables, fixtures))["status"], "unavailable")

    def test_quantile_and_empirical_percentile_edges(self):
        self.assertIsNone(league.quantile([], 0.5))
        self.assertEqual(league.quantile([7], 0.9), 7)
        self.assertEqual(league.quantile([20, 10], 0.25), 12.5)
        self.assertEqual(league.quantile([1, 2, 3, 4], 0.75), 3.25)
        self.assertIsNone(league.percentile([], 1))
        histogram = [[10, 2], [15, 2], [20, 1]]
        self.assertEqual(league.percentile(histogram, 9), 0)
        self.assertEqual(league.percentile(histogram, 21), 100)
        self.assertEqual(league.percentile(histogram, 15), 60)
        self.assertEqual(league.percentile([[12, 5]], 12), 50)

    def test_reference_population_exact_positions_missing_data_and_keeper_separation(self):
        clubs = [str(i) for i in range(100, 108)]
        rows = []
        for club in clubs:
            for value in (10, 12, 14, 16, 18):
                rows.append(reference_player(len(rows) + 1, club, value))
            for value in (9, 11, 13):
                rows.append(reference_player(len(rows) + 1, club, value, keeper=True))
        missing = reference_player(1000, "100", 15)
        del missing["attrs"]["Pace"]
        unknown = reference_player(1001, "100", 20)
        unknown["positions_dc"] = ""
        unknown["positions_sw"] = ""
        unknown["natural_positions"] = "DC"
        unknown_type = reference_player(1002, "100", 20)
        unknown_type["positions_gk"] = ""
        youth = reference_player(1003, "100", 20)
        youth["team_slot"] = "1"
        other = reference_player(1004, "999", 20)
        duplicate = reference_player(1005, "100", 20)
        rows.extend([missing, unknown, unknown_type, youth, other, duplicate, dict(duplicate)])
        result = aggregate(rows, clubs)
        cb = result["profiles"]["CB"]
        self.assertEqual(cb["sample_size"], 40)
        self.assertEqual(cb["eligible_players"], 41)
        self.assertEqual(cb["missing_attributes"], 1)
        self.assertEqual(cb["unknown_familiarity"], 1)
        self.assertEqual(cb["unknown_type"], 1)
        self.assertEqual(cb["contributing_clubs"], 8)
        self.assertEqual((cb["median"], cb["p25"], cb["p75"], cb["p90"]), (14, 12, 16, 18))
        self.assertEqual(result["profiles"]["GK"]["sample_size"], 24)
        self.assertEqual(result["profiles"]["GK"]["median"], 11)
        self.assertEqual(result["duplicate_player_rows"], 2)
        self.assertNotIn("Private", json.dumps(result))
        self.assertEqual(aggregate(list(reversed(rows)), clubs), result)

    def test_insufficient_sample_and_incomplete_comparisons(self):
        clubs = ["100", "101", "102", "103"]
        rows = [reference_player(i, clubs[i % 4], 12) for i in range(20)]
        result = aggregate(rows[:3], clubs)
        self.assertEqual(result["profiles"]["CB"]["status"], "unavailable")
        self.assertIsNone(result["profiles"]["CB"]["median"])
        result = aggregate(rows, clubs)
        competition = detect(competition_fixture())
        cache = {"version": 1, "detection_policy": league.DETECTION_POLICY, "status": "available", "model_sha256": "model", "observed_game_date": "2027-01-01",
                 "detection": competition, "extraction_game_date": "2027-01-01", "reference": result, "provenance": {}}
        people = [{"player_id": "career:1", "raw": rows[0], "scores": {"CB": 12}},
                  {"player_id": "career:2", "raw": dict(rows[0], positions_dc="", positions_sw=""), "scores": {"CB": 12}}]
        report = league.build_report(cache, people, "career", "2027-01-01", "model", CODES, evidence)
        cb = [c for c in report["comparisons"] if c["profile"] == "CB"]
        self.assertEqual(cb[0]["percentile"], 50)
        self.assertEqual(cb[0]["difference_from_median"], 0)
        self.assertIsNone(cb[1]["percentile"])
        self.assertEqual(cb[1]["reason"], "position_familiarity_not_confirmed")
        stale = league.build_report(cache, people, "career", "2027-01-02", "model", CODES, evidence)
        self.assertEqual(stale["reason"], "benchmark_detection_date_mismatch")
        cache.pop("detection_policy")
        self.assertEqual(league.build_report(cache, people, "career", "2027-01-01", "model", CODES, evidence)["reason"], "benchmark_detection_requires_refresh")
        self.assertIsNone(league.reuse_reference(cache, competition, "model", "2027-01-01"))


if __name__ == "__main__":
    unittest.main()
