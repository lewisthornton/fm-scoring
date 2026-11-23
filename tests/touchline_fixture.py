"""Invented-data M1b fixture, generated exclusively through operational builders."""
import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_rangers_integration import IntegrationTests, CAREER, player, bridge
import touchline_generation as generation


def create(root):
    fixture = IntegrationTests()
    fixture.setUp()
    try:
        # Distinct namesakes and an eligible shared bench defender, with vacancies.
        fixture.target["name"] = "Alex Example"
        fixture.target_gk["name"] = "Alex Example"
        fixture.cb["name"] = "Morgan Example"
        fixture.gk["name"] = "Jamie Example"
        for uid, name, code in [(6, "Taylor Example", "dr"), (7, "Sam Example", "dc"),
                                (8, "Casey Example", "dm"), (9, "Riley Example", "aml"),
                                (10, "Drew Example", "stc"), (11, "Avery Example", "dc"),
                                (12, "Quinn Example", "dc")]:
            p = player(uid, name, squad=True)
            p["positions_dc"] = "20" if code == "dc" else "1"
            p["positions_" + code] = "20"
            if uid in (11, 12):
                p["positions_dr"] = "20"
                p["positions_dl"] = "20"
                for k in p:
                    if k.startswith("attributes_"):
                        p[k] = "5" if uid == 11 else "3"
            fixture.squad.append(p)
            fixture.world.append(p)
        for uid in range(20, 36):
            p = player(uid, f"Invented target {uid}")
            p["positions_dc"] = "1"
            p["positions_dl"] = "20"
            if uid == 20:
                p["positions_dl"] = ""
                p["positions_dc"] = ""
                p["attributes_crossing"] = ""
            fixture.world.append(p)
            fixture.candidates.append({"Unique ID": str(uid)})
        fixture.process()
        args = SimpleNamespace(db=fixture.dbpath, career=CAREER, formation=None, signing_depth_limit=2)
        def publish():
            evidence = {}
            reports = bridge.build_reports(args, ROOT, provenance=evidence)[:6]
            return generation.publish(root, reports, evidence)
        first = publish()
        fixture.process(candidates=[])
        second = publish()
        generation.rollback(root, first)
        return first, second
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print("Fixture generations:", *create(args.directory))
