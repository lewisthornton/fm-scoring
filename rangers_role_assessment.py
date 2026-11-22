"""Opt-in R4 scoped role reports and read-only tactic inventory extraction.

Neither command is part of the operational watcher/bridge launch workflow.
Run from the repository checkout, with local/private output directories.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

import role_ability
import tactic
import tactical_assessment

# Use the checkout's existing standalone watcher identity/copy/CLI helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent / "integrations" / "rangers"))
import rangers_autosave_watcher as watcher
from rangers_club import club_uid, loan_state, rangers_names


PARSER_VERSION = "0.14.3"
PARSER_REVISION = "755fe9c566bb0497d4ad6ef6e1ac1fd2fde7351b"
REPORT_FILENAME = "role_assessments.json"
INVENTORY_FILENAME = "stored_tactics.json"

# fmsave 0.14.3 exports nested Attributes as raw_attributes_<name> in CSV.
# R3 classifier names already agree for every used attribute. These three
# unused-in-R3 fields have distinct reference spellings; retain source names
# in SQLite, normalize only at the R4 reader boundary.
RAW_ALIASES = {"penalty_taking": "penalties", "free_kick_taking": "free_kicks", "punching": "tendency_to_punch"}
RAW_FIELDS = frozenset("""crossing dribbling finishing heading long_shots marking off_the_ball passing penalty_taking tackling
vision handling aerial_reach command_of_area communication kicking throwing anticipation decisions one_on_ones positioning
reflexes first_touch technique flair corners teamwork work_rate long_throws eccentricity rushing_out punching acceleration
free_kick_taking strength stamina pace jumping_reach leadership dirtiness balance bravery consistency aggression agility
important_matches injury_proneness versatility natural_fitness determination composure concentration""".split())

# Named position bits from fmsave TacticPosition at the pinned revision.
# Unknown bits (including 1,5,6) are deliberately not decoded. Side flags
# corroborated by the pinned fm-mcp tacticnames.go PositionMask definitions.
TACTIC_CODES = {0: ("goalkeeper", "gk"), 2: ("defender_right", "dr"), 3: ("defender_left", "dl"),
                4: ("defender_centre", "dc"), 7: ("defensive_midfielder", "dm"), 8: ("midfielder_right", "mr"),
                9: ("midfielder_left", "ml"), 10: ("midfielder_centre", "mc"),
                11: ("attacking_midfielder_right", "amr"), 12: ("attacking_midfielder_left", "aml"),
                13: ("attacking_midfielder_centre", "amc"), 14: ("striker_centre", "stc")}
LEFT_FLAG, RIGHT_FLAG = 0x100000, 0x200000


def parser_number(value):
    """Decode only exact CSV integer syntax; retain invalid evidence for R3."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
        try:
            return int(value)
        except ValueError:  # excessively long malformed numeric value
            pass
    return value


def numeric_status(value, minimum, maximum):
    if value is None:
        return "missing"
    if type(value) is not int:
        return "invalid_type"
    return "observed" if minimum <= value <= maximum else "unsupported_value"


def read_scope(dbpath, career):
    """One read-only DB snapshot, scoped to active memberships and bound career.

    Never run watcher.connect(), migrations or write SQL on a user's database.
    Verify the existing record hashes and identity joins before consuming data.
    """
    dbpath = Path(dbpath)
    if not dbpath.is_file():
        raise ValueError("Scoped database does not exist")
    con = sqlite3.connect(dbpath.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN")
        binding = con.execute("SELECT club_uid,manager_staff_uid FROM career_club WHERE career=?", (career,)).fetchone()
        date = con.execute("SELECT latest_game_date FROM career_chronology WHERE career=?", (career,)).fetchone()
        if not binding or club_uid(binding["club_uid"]) != binding["club_uid"] or not date or not watcher.valid_game_date(date[0]):
            raise ValueError("Unbound career or missing chronology; run the normal watcher first")
        rows = con.execute("""SELECT m.player_key,m.cohort,m.last_seen_game_date,p.record_json,p.record_hash,
            l.record_hash AS latest_hash,p.snapshot_id,s.game_date,s.game_build,s.source_sha256,s.selection_sha256
            FROM cohort_membership m JOIN player_latest l ON l.career=m.career AND l.player_key=m.player_key
            JOIN player_versions p ON p.snapshot_id=l.snapshot_id AND p.player_key=l.player_key AND p.career=m.career
            JOIN snapshots s ON s.id=p.snapshot_id AND s.career=m.career
            WHERE m.career=? AND m.active=1 ORDER BY m.player_key,m.cohort""", (career,)).fetchall()
        count = con.execute("SELECT COUNT(*) FROM cohort_membership WHERE career=? AND active=1", (career,)).fetchone()[0]
        if count != len(rows):
            raise ValueError("Incomplete career-scoped observation join")
        accepted_hashes = [r[0] for r in con.execute("SELECT DISTINCT source_sha256 FROM snapshots WHERE career=? AND game_date=? ORDER BY source_sha256", (career,date[0]))]
    finally:
        con.close()
    people = {}
    for row in rows:
        key = row["player_key"]
        raw = json.loads(row["record_json"])
        digest = hashlib.sha256(row["record_json"].encode("utf-8")).hexdigest()
        if (not isinstance(raw, dict) or not raw.get("uid") or watcher.identity(raw) != key or
                digest != row["record_hash"] or digest != row["latest_hash"]):
            raise ValueError("Player identity or observation hash mismatch")
        if row["last_seen_game_date"] != date[0] or (row["game_date"] is not None and
                (not watcher.valid_game_date(row["game_date"]) or row["game_date"] > date[0])):
            raise ValueError("Player observation chronology mismatch")
        if key not in people:
            provenance = raw.get("role_evidence")
            if isinstance(provenance, dict) and provenance.get("game_build") is not None and provenance["game_build"] != row["game_build"]:
                raise ValueError("Player build provenance conflicts with snapshot")
            people[key] = {"player_key": key, "player_id": json.dumps(["rangers",career,key], ensure_ascii=False,separators=(",",":")),
                           "raw": raw, "cohorts": [], "record_game_date": row["game_date"], "game_build": row["game_build"],
                           "last_seen_game_date": date[0], "source": {"snapshot_id": row["snapshot_id"], "record_sha256": digest,
                           "save_sha256": row["source_sha256"], "selection_sha256": row["selection_sha256"]}}
        people[key]["cohorts"].append(row["cohort"])
    return {"career": career, "club_id": binding["club_uid"], "manager_id": binding["manager_staff_uid"],
            "game_date": date[0], "accepted_save_hashes": accepted_hashes, "people": list(people.values())}


def normalize_player(person, career, catalogue):
    raw = person["raw"]
    meta = raw.get("role_evidence")
    meta = meta if isinstance(meta, dict) else {}
    fields = {RAW_ALIASES.get(name,name): parser_number(raw.get("raw_attributes_"+name)) for name in sorted(RAW_FIELDS)}
    positions = {code: parser_number(raw.get("positions_"+code)) for code in sorted(tactic.POSITIONS)}
    categories = {key: item["category"] for key,item in tactical_assessment.position_evidence(raw,tactic.POSITIONS).items()
                  if item["status"] == "inferred_category"}
    ca = parser_number(raw.get("ability_current"))
    db_version = parser_number(meta.get("database_version"))
    parser_ok = (type(meta.get("version")) is int and meta["version"] == 1 and meta.get("game") == "FM27" and
                 meta.get("parser_version") == PARSER_VERSION and meta.get("game_build") == person["game_build"] and
                 type(meta.get("parser_known_build")) is bool)
    parser_status = "captured_supported_contract" if parser_ok else ("legacy_or_missing_provenance" if not meta else "unverified_parser_contract")
    required = {name for r in catalogue["roles"].values() for group in ("key_attributes","preferable_attributes","negative_attributes") for name in r[group]}
    coverage = {"raw_attributes": {name: numeric_status(value,1,100) for name,value in sorted(fields.items())},
                "model_attribute_fields": sorted(required),
                "positions": {code: ("category_only" if value is None and code in categories else numeric_status(value,1,20)) for code,value in positions.items()},
                "current_ability": numeric_status(ca,1,200),
                "raw_left_foot": numeric_status(parser_number(raw.get("raw_left_foot")),1,100),
                "raw_right_foot": numeric_status(parser_number(raw.get("raw_right_foot")),1,100)}
    # An unsupported parser cannot accidentally become a numerically compatible
    # observation merely because its raw fields happen to be integers.
    observation = {"schema_version": 1 if parser_ok else None, "player_id": person["player_id"], "career": career,
                   "record_game_date": person["record_game_date"], "game_build": person["game_build"],
                   "database_version": db_version, "attribute_scale": "raw_1_100" if parser_ok else None,
                   "raw_attributes": fields, "positions": positions, "position_categories": categories,
                   "current_ability": ca, "raw_left_foot": parser_number(raw.get("raw_left_foot")),
                   "raw_right_foot": parser_number(raw.get("raw_right_foot")),
                   "source": {**person["source"], "parser": meta, "parser_contract": parser_status}}
    return observation, coverage, parser_status


def selected_tactic(registry, catalogue_path, selected_id, persisted=None):
    """Reload the trusted explicit manual source, not just self-consistent JSON."""
    catalogue = tactic.load_catalogue(catalogue_path)
    if catalogue.get("origin") != "fm27_reference" or tactic.canonical_sha256(catalogue) != role_ability.CATALOGUE_SHA256:
        raise ValueError("Catalogue does not match the pinned R3 numerical model")
    # R2 reads and validates the TOML, including role placements/context and
    # manual-only source constraints. Its hash alone is not authorization.
    selection = tactic.select_tactic(registry,catalogue_path,selected_id)
    if selection["catalogue"]["sha256"] != tactic.canonical_sha256(catalogue):
        raise ValueError("Catalogue changed during selection")
    if selection["tactic"]["input_version"] != 2 or selection["tactic"]["source"]["kind"] != "manual":
        raise ValueError("R4 requires a manually confirmed version 2 tactic")
    if persisted is not None:
        supplied = json.loads(Path(persisted).read_text(encoding="utf-8"))
        if tactic.canonical_sha256(supplied) != tactic.canonical_sha256(selection):
            raise ValueError("Persisted selection differs from revalidated source and catalogue")
    validate_selection(selection,catalogue)
    return selection, catalogue


def validate_selection(selection,catalogue):
    """Validate the precise normalized R2 shape again at the report boundary."""
    digest=tactic.canonical_sha256(catalogue)
    if digest!=role_ability.CATALOGUE_SHA256 or catalogue.get("origin")!="fm27_reference":
        raise ValueError("Catalogue does not match the pinned R3 numerical model")
    config=selection["tactic"]
    source=config["source"]
    file_hash=source.get("file_sha256")
    if (type(selection.get("version")) is not int or selection["version"]!=1 or
            type(config.get("version")) is not int or config["version"]!=2 or
            type(config.get("input_version")) is not int or config["input_version"]!=2 or
            selection.get("selected_id")!=config["id"] or source.get("kind")!="manual" or
            not isinstance(file_hash,str) or not re.fullmatch(r"[0-9a-f]{64}",file_hash)):
        raise ValueError("Unsupported selection identity or source")
    raw={k:config[k] for k in ("version","id","name","phase_weights")}
    raw["source"]={k:v for k,v in source.items() if k!="file_sha256"}
    raw["slots"]=[]
    for slot in config["slots"]:
        item={k:v for k,v in slot.items() if k not in tactic.PHASES}
        for phase in tactic.PHASES:
            item[phase]={k:v for k,v in slot[phase].items() if k!="instruction_source"}
        raw["slots"].append(item)
    validated=tactic.validate_tactic(raw,catalogue)
    validated["source"]["file_sha256"]=file_hash
    missing=[{"slot_id":s["id"],"phase":p} for s in validated["slots"] for p in tactic.PHASES
             if validated["phase_weights"][p]>0 and (s[p]["role_id"] is None or s[p]["position"] is None or s[p]["side"] is None)]
    expected={"version":1,"selected_id":validated["id"],"tactic":validated,"tactic_sha256":tactic.tactic_sha256(validated),
              "catalogue":{**{k:catalogue[k] for k in ("id","version","origin","source")},"sha256":digest},
              "configuration_status":"draft" if missing else "configured","unresolved_weighted_phases":missing,"role_scoring_available":False}
    if tactic.canonical_sha256(selection)!=tactic.canonical_sha256(expected):
        raise ValueError("Selection differs from its revalidated normalized contract")


def build_report(scope, selection, catalogue, *, model_id):
    if model_id != role_ability.FM27_MODEL_ID:
        raise ValueError("Select the explicit R3 model ID")
    validate_selection(selection,catalogue)
    reports = []
    for person in sorted(scope["people"], key=lambda p:p["player_id"]):
        if person["player_id"]!=json.dumps(["rangers",scope["career"],person["player_key"]],ensure_ascii=False,separators=(",",":")):
            raise ValueError("Player/career identity mismatch")
        observation, coverage, parser_status = normalize_player(person,scope["career"],catalogue)
        report = role_ability.assess_tactic(selection,catalogue,observation,model_id=model_id,
                                            game_build=observation["game_build"],database_version=observation["database_version"])
        build_pair={"game_build":observation["game_build"],"database_version":observation["database_version"]}
        build_status="compatible" if type(observation["database_version"]) is int and build_pair in role_ability.MODEL["supported_builds"] else "unsupported_game_build"
        loan, availability = loan_state(person["raw"],scope["club_id"]) if "squad" in person["cohorts"] else ("unknown","unknown")
        report.update(player_key=person["player_key"],name=person["raw"].get("name"),cohorts=sorted(person["cohorts"]),
                      last_seen_game_date=person["last_seen_game_date"],loan_state=loan,availability=availability,
                      parser_compatibility=parser_status,numerical_build_compatibility=build_status,input_coverage=coverage,
                      raw_foot_evidence={"left":observation["raw_left_foot"],"right":observation["raw_right_foot"]})
        reports.append(report)
    return {"version":1,"career":scope["career"],"club_id":scope["club_id"],"game_date":scope["game_date"],
            "selected_tactic_id":selection["selected_id"],"tactic":selection["tactic"],"tactic_sha256":selection["tactic_sha256"],
            "catalogue":selection["catalogue"],"model":{**role_ability.MODEL,"sha256":role_ability.MODEL_SHA256},
            "tactic_configuration_status":selection["configuration_status"],"operational_scoring":False,
            "compatibility_summary":{"parser":dict(sorted(Counter(p["parser_compatibility"] for p in reports).items())),
                                     "build":dict(sorted(Counter(p["numerical_build_compatibility"] for p in reports).items())),
                                     "numerical_model":dict(sorted(Counter(p["model_unavailable_reason"] or "compatible" for p in reports).items()))},
            "players":reports,"status":"complete" if reports and all(s["combined_role_ability"] is not None for p in reports for s in p["slots"]) else
            "partial" if any(s["combined_role_ability"] is not None for p in reports for s in p["slots"]) else "unavailable"}


def publish(output_dir, filename, report):
    """Publish only a dedicated R4 filename, no writes before full validation."""
    if filename not in (REPORT_FILENAME,INVENTORY_FILENAME):
        raise ValueError("Invalid R4 output filename")
    directory = Path(output_dir)
    payload = json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    path = directory / filename
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",newline="\n",dir=directory,prefix=".r4-",suffix=".tmp",delete=False) as stream:
            temp = Path(stream.name)
            stream.write(payload)
        os.replace(temp,path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return path


def decode_geometry(row, prefix):
    """Decode only corroborated singleton native position bits and sides."""
    mask = row.get(prefix+"_mask")
    codes = row.get(prefix+"_positions_code")
    labels = row.get(prefix+"_positions")
    evidence = {"mask":mask,"codes":codes,"labels":labels}
    if (type(mask) is not int or mask < 0 or not isinstance(codes,list) or len(codes)!=1 or
            type(codes[0]) is not int or codes[0] not in TACTIC_CODES):
        return None,None,evidence,"unknown_or_ambiguous_position"
    label,pos = TACTIC_CODES[codes[0]]
    flags = mask & (LEFT_FLAG|RIGHT_FLAG)
    if labels != [label] or mask & ~(LEFT_FLAG|RIGHT_FLAG) != 1<<codes[0] or flags == (LEFT_FLAG|RIGHT_FLAG):
        return None,None,evidence,"conflicting_position_mask"
    side = "left" if flags == LEFT_FLAG else "right" if flags == RIGHT_FLAG else (
        "left" if pos in tactic.LEFT else "right" if pos in tactic.RIGHT else "centre")
    if not tactic.side_allowed(pos,side):
        return None,None,evidence,"conflicting_side"
    return pos,side,evidence,None


def inventory(scope, metadata, save_hash, clubs, records, catalogue):
    """Normalize the pinned fmsave nested JSON export; never decode role tokens."""
    if metadata.get("game") != "FM27" or metadata.get("fmsave_version") != PARSER_VERSION or type(metadata.get("known_build")) is not bool:
        raise ValueError("Unsupported tactic parser contract; require FM27 fmsave 0.14.3")
    if not isinstance(metadata.get("build"),str) or not metadata["build"]:
        raise ValueError("Missing exact game build")
    if metadata.get("game_date") != scope["game_date"] or save_hash not in scope["accepted_save_hashes"]:
        raise ValueError("Save is not an evidenced accepted snapshot at the current career date")
    if not isinstance(clubs,list) or len(clubs)!=1 or club_uid(clubs[0].get("uid")) != scope["club_id"] or not rangers_names(clubs[0].get("name"),clubs[0].get("short_name")):
        raise ValueError("Managed club identity mismatch")
    teams = clubs[0].get("teams")
    if not isinstance(teams,list) or not all(isinstance(t,dict) for t in teams):
        raise ValueError("Missing managed club team list")
    first = [t for t in teams if type(t.get("slot")) is int and t["slot"]==0]
    if len(first)!=1 or first[0].get("is_affiliate") is not False or club_uid(first[0].get("club_uid")) != scope["club_id"]:
        raise ValueError("Ambiguous managed first-team identity")
    team_id = club_uid(first[0].get("team_id"))
    # Require corroboration from scoped current-club squad registrations from
    # the same source snapshot; neither a tactic name nor team slot alone proves identity.
    evidence = {club_uid(p["raw"].get("team_id")) for p in scope["people"] if "squad" in p["cohorts"] and
                p["source"]["save_sha256"] == save_hash and club_uid(p["raw"].get("club_uid")) == scope["club_id"] and
                type(parser_number(p["raw"].get("team_slot"))) is int and parser_number(p["raw"].get("team_slot")) == 0}
    if team_id is None or evidence != {team_id}:
        raise ValueError("First-team ID is not corroborated by scoped player observations")
    if not isinstance(records,list) or not all(isinstance(r,dict) for r in records):
        raise ValueError("Invalid tactic export")
    expected = {"career":scope["career"],"club_id":scope["club_id"],"team_id":team_id}
    selected = []
    for record in records:
        # Other own-team records may appear in the export. A claimed first-team
        # record with inconsistent identifiers is a conflict, not a candidate.
        club = club_uid(record.get("club_uid")); team = club_uid(record.get("team_id")); slot = record.get("team_slot")
        if club != scope["club_id"]:
            raise ValueError("Unexpected club in scoped tactic export")
        if team != team_id and slot != 0:
            continue
        if team != team_id or type(slot) is not int or slot!=0:
            raise ValueError("Conflicting first-team tactic identity")
        selected.append(record)
    indices = [r.get("index") for r in selected]
    if any(type(i) is not int or i<0 for i in indices) or len(set(indices))!=len(indices):
        raise ValueError("Missing or duplicate stored tactic index")
    result = []
    for record in sorted(selected,key=lambda r:r["index"]):
        source = {"kind":"save_import","reference":"fmsave nested tactic export",**expected,
                  "game_build":metadata["build"],"parser_version":PARSER_VERSION,"save_sha256":save_hash,"stored_index":record["index"]}
        # Preserve even unresolved slot evidence; no raw role bit is used as an ID.
        item = {"stored_index":record["index"],"name":record.get("name"),"source":source,"raw_slots":record.get("slots"),
                "raw_tactic_metadata":{k:record[k] for k in ("style_name","mentality","mentality_code","unknown") if k in record},
                "tactic":None,"status":"unavailable"}
        try:
            slots = record.get("slots")
            if not isinstance(slots,list) or len(slots)!=11 or not all(isinstance(s,dict) for s in slots) or any(type(s.get("number")) is not int or s["number"]!=i for i,s in enumerate(slots)):
                raise ValueError("invalid_stored_slot_order")
            rows=[]
            for s in slots:
                unknown=s.get("unknown")
                if not isinstance(unknown,dict):
                    raise ValueError("missing_defending_index")
                phases={}
                for phase,prefix in (("ip","in_possession"),("oop","out_of_possession")):
                    pos,side,_,reason=decode_geometry(s,prefix)
                    token=unknown.get(prefix+"_role_bits")
                    part={"role_status":"ambiguous" if token is not None else "unknown","role_reason":"raw_role_bits_not_verified" if token is not None else "role_identity_missing"}
                    if token is not None:
                        part["raw_role_token"]=json.dumps(token,sort_keys=True)
                    if pos is not None: part["position"]=pos
                    if side is not None: part["side"]=side
                    if reason: part["geometry_reason"]=reason
                    phases[phase]=part
                ip=phases["ip"]
                if "position" not in ip or "side" not in ip:
                    raise ValueError("unresolved_selection_geometry")
                rows.append({"id":f"slot-{s['number']}","label":f"Stored slot {s['number']}","selection_position":ip["position"],
                             "side":ip["side"],"defending_index":unknown.get("out_of_possession_position_index"),**phases})
            item["tactic"]=tactic.adapt_save_tactic({"source":source,"team_slot":0,"name":record.get("name"),"slots":rows},expected,catalogue,
                                                    tactic_id=f"stored-{record['index']}",weights={"ip":0.5,"oop":0.5})
            item["status"]="draft"
            item["tactic_sha256"]=tactic.tactic_sha256(item["tactic"])
        except (ValueError,KeyError,TypeError) as exc:
            item["reason"]=str(exc)
        result.append(item)
    return {"version":1,**expected,"game_date":scope["game_date"],"save_sha256":save_hash,
            "parser_version":PARSER_VERSION,"parser_revision":PARSER_REVISION,"game_build":metadata["build"],
            "database_version":metadata.get("db_version"),"parser_known_build":metadata.get("known_build"),
            "active_tactic_id":None,"status":"available" if result else "unavailable",
            "reason":None if result else "no_stored_first_team_tactics","tactics":result}


def extract_inventory(db, career, save, catalogue_path):
    scope=read_scope(db,career)
    catalogue=tactic.load_catalogue(catalogue_path)
    if tactic.canonical_sha256(catalogue)!=role_ability.CATALOGUE_SHA256:
        raise ValueError("Catalogue does not match R3")
    with tempfile.TemporaryDirectory(prefix="fm-role-tactics-") as td:
        root=Path(td); copy=root/"snapshot.fm"
        digest=watcher.checked_copy(Path(save),copy)
        metadata=json.loads(watcher.fmsave("info",str(copy),"--json"))
        if not isinstance(metadata,dict) or metadata.get("game_date")!=scope["game_date"] or digest not in scope["accepted_save_hashes"]:
            raise ValueError("Unconfirmed accepted snapshot for this career/date")
        if metadata.get("fmsave_version")!=PARSER_VERSION or metadata.get("game")!="FM27":
            raise ValueError("Unsupported tactic parser contract")
        managed=root/"managed.csv"
        watcher.fmsave("export",str(copy),"managed-clubs","--all","-o",str(managed),"--strict")
        club, manager=watcher.managed_identity(managed)
        if club!=scope["club_id"] or not manager or manager!=scope["manager_id"]:
            raise ValueError("Managed career/club/manager identity mismatch")
        outputs={}
        for table in ("clubs","tactics"):
            target=root/f"{table}.json"
            watcher.fmsave("export",str(copy),table,"--club",club,"--format","json","-o",str(target),"--strict")
            outputs[table]=json.loads(target.read_text(encoding="utf-8"))
        return inventory(scope,metadata,digest,outputs["clubs"],outputs["tactics"],catalogue)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    report=commands.add_parser("assess")
    extract=commands.add_parser("extract-tactics")
    for cmd in (report,extract):
        cmd.add_argument("--db",type=Path,required=True)
        cmd.add_argument("--career",required=True)
        cmd.add_argument("--catalogue",type=Path,required=True)
        cmd.add_argument("--output-dir",type=Path,required=True,help="Existing private output directory")
    report.add_argument("--registry",type=Path,required=True)
    report.add_argument("--select",required=True)
    report.add_argument("--model",required=True)
    report.add_argument("--selected-tactic",type=Path,help="Optional previously published R2 selection to compare against fresh validation")
    extract.add_argument("--save",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=="assess":
            selection,catalogue=selected_tactic(args.registry,args.catalogue,args.select,args.selected_tactic)
            data=build_report(read_scope(args.db,args.career),selection,catalogue,model_id=args.model)
            output=publish(args.output_dir,REPORT_FILENAME,data)
        else:
            data=extract_inventory(args.db,args.career,args.save,args.catalogue)
            output=publish(args.output_dir,INVENTORY_FILENAME,data)
    except (OSError,ValueError,RuntimeError,sqlite3.Error,KeyError,TypeError) as exc:
        parser.error(str(exc))
    print(f"Published {output} ({data['status']}; operational scoring unchanged)")


if __name__=="__main__":
    main()
