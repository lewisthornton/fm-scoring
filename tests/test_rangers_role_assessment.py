"""R4 scoped integration tests: invented exports, temporary SQLite and tactic JSON."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import formation
import optimal_xi
import rangers_role_assessment as r4
import role_ability
import scoring
import tactic
import tactical_assessment
from test_rangers_integration import player, write_csv, MODEL, bridge, watcher


ROOT=Path(__file__).resolve().parents[1]
CATALOGUE=ROOT/"formations/fm27-role-catalogue.toml"
REGISTRY=ROOT/"formations/r4-role-tactics.example.toml"
CAREER="invented-r4"
DATE="2027-01-01"
META={"game":"FM27","build":"27.0.0","db_version":3754,"fmsave_version":"0.14.3","known_build":True,"game_date":DATE}


def full_player(uid, name, squad=False, keeper=False):
    p=player(uid,name,squad=squad,keeper=keeper)
    p.update({"raw_attributes_"+a:"73" for a in r4.RAW_FIELDS})
    p.update({"positions_"+code:"20" for code in tactic.POSITIONS})
    p.update(raw_left_foot="87",raw_right_foot="48",team_id="1234" if squad else "4321",team_slot="0")
    return p


def tactic_export(index=2):
    # Actual pinned fmsave nested JSON shape (invented masks/roles).
    native=[(0,"centre"),(3,"left"),(4,"left"),(4,"right"),(2,"right"),(7,"centre"),
            (10,"left"),(10,"right"),(12,"left"),(11,"right"),(14,"centre")]
    permutation=[0,4,2,3,9,5,6,7,8,1,10]
    rows=[]
    for i,(code,side) in enumerate(native):
        mask=1<<code
        if code in (4,7,10,13,14):
            mask |= r4.LEFT_FLAG if side=="left" else r4.RIGHT_FLAG if side=="right" else 0
        row={"number":i,"unknown":{"in_possession_role_bits":43,"out_of_possession_role_bits":43,
                                   "out_of_possession_position_index":permutation[i]}}
        for phase in ("in_possession","out_of_possession"):
            row.update({phase+"_mask":mask,phase+"_positions":[r4.TACTIC_CODES[code][0]],phase+"_positions_code":[code]})
        rows.append(row)
    return {"club_uid":100,"team_id":1234,"team_slot":0,"index":index,"name":"Invented saved tactic","slots":rows}


CLUBS=[{"uid":100,"name":"Rangers","short_name":"Rangers","teams":[{"team_id":1234,"slot":0,"club_uid":100,"is_affiliate":False},
                                                                         {"team_id":1235,"slot":1,"club_uid":100,"is_affiliate":False}]}]


class R4Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name); self.dbpath=self.root/"scoped.sqlite3"; self.db=watcher.connect(self.dbpath)
        self.addCleanup(self.db.close)
        self.save=self.root/"invented.fm"; self.save.write_bytes(b"invented save 1")
        self.export=self.root/"filter.csv"; write_csv(self.export,[{"Unique ID":"3"}])
        self.world=[full_player(1,"Invented defender",True),full_player(2,"Invented keeper",True,True),
                    full_player(3,"Invented target"),full_player(4,"Unselected world player")]
        self.meta=dict(META); self.records=[tactic_export()]; self.clubs=copy.deepcopy(CLUBS); self.calls=[]
        self.managed=[{"club_uid":"100","club_name":"Rangers","club_short_name":"Rangers","manager_staff_uid":"800"}]

    def fake_parser(self,command,save,*args):
        self.assertNotEqual(Path(save),self.save)
        self.assertEqual(Path(save).read_bytes(),self.save.read_bytes())
        self.calls.append((command,Path(save),args))
        if command=="info": return json.dumps(self.meta)
        path=Path(args[args.index("-o")+1]); table=args[0]
        if table=="managed-clubs": write_csv(path,self.managed)
        elif table=="clubs":
            if "--format" in args: path.write_text(json.dumps(self.clubs),encoding="utf-8")
            else: write_csv(path,[{"uid":"100","name":"Rangers","short_name":"Rangers"}])
        elif table=="players": write_csv(path,self.world)
        elif table=="tactics": path.write_text(json.dumps(self.records),encoding="utf-8")
        else: self.fail("unexpected parser request "+table)
        return ""

    def process(self):
        with patch.object(watcher,"fmsave",side_effect=self.fake_parser):
            self.assertTrue(watcher.process(self.db,self.save,CAREER,self.export))

    def selection(self, **kwargs):
        return r4.selected_tactic(REGISTRY,CATALOGUE,"r4-example",**kwargs)

    def scope(self): return r4.read_scope(self.dbpath,CAREER)

    def report(self):
        sel,cat=self.selection()
        return r4.build_report(self.scope(),sel,cat,model_id=role_ability.FM27_MODEL_ID)

    def test_raw_scoped_capture_hash_history_and_exact_mapping(self):
        # Pinned CSV raw names and display values are independent.
        self.world[0]["raw_attributes_pace"]="74"
        self.world[0]["raw_attributes_penalty_taking"]="91"
        self.process(); scope=self.scope()
        self.assertEqual(len(scope["people"]),3)
        self.assertNotIn("Unselected world player",str(self.db.execute("SELECT record_json FROM player_versions").fetchall()))
        _,cat=self.selection(); first=scope["people"][0]
        obj,cov,status=r4.normalize_player(first,CAREER,cat)
        self.assertEqual(obj["raw_attributes"]["pace"],74)
        self.assertEqual(obj["raw_attributes"]["penalties"],91)
        self.assertEqual(obj["raw_attributes"]["one_on_ones"],73)
        self.assertEqual((obj["raw_left_foot"],obj["raw_right_foot"]),(87,48))
        self.assertEqual(len(obj["positions"]),15)
        self.assertEqual(status,"captured_supported_contract")
        self.assertEqual(obj["database_version"],3754)
        before=self.db.execute("SELECT record_json,record_hash FROM player_versions ORDER BY snapshot_id,player_key").fetchall()
        self.process()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM player_versions").fetchone()[0],3)
        self.world[0]["raw_attributes_pace"]="75"; self.meta["game_date"]="2027-01-02"; self.save.write_bytes(b"invented save 2")
        self.process(); after=self.scope()["people"][0]
        self.assertEqual(first["player_id"],after["player_id"])
        self.assertNotEqual(first["source"]["record_sha256"],after["source"]["record_sha256"])
        self.assertEqual(self.db.execute("SELECT record_json,record_hash FROM player_versions ORDER BY snapshot_id,player_key LIMIT 3").fetchall(),before)

    def test_legacy_history_and_missing_invalid_unsupported_values(self):
        self.world[0]={k:v for k,v in self.world[0].items() if not k.startswith("raw_")}
        self.meta={"game_date":DATE}; self.process()
        old=self.scope()["people"][0]
        self.assertEqual(self.report()["players"][0]["parser_compatibility"],"legacy_or_missing_provenance")
        self.world[0]=full_player(1,"Invented defender",True)
        self.world[0].update(raw_attributes_handling="0",raw_attributes_pace="73.0",raw_attributes_passing="",positions_dc="21",positions_dr="",natural_positions="DR")
        self.meta=dict(META); self.process(); _,cat=self.selection()
        new=self.scope()["people"][0]; obj,cov,_=r4.normalize_player(new,CAREER,cat)
        self.assertEqual(old["player_id"],new["player_id"])
        self.assertEqual(cov["raw_attributes"]["handling"],"unsupported_value")
        self.assertEqual(cov["raw_attributes"]["pace"],"invalid_type")
        self.assertEqual(cov["raw_attributes"]["passing"],"missing")
        self.assertEqual(cov["positions"]["dc"],"unsupported_value")
        self.assertEqual(cov["positions"]["dr"],"category_only")
        self.assertIsNone(obj["positions"]["dr"])
        self.assertIsNone(self.report()["players"][0]["slots"][0]["ip"]["role_rating"])

    def test_complete_report_deterministic_and_unsupported_build(self):
        self.process(); first=self.report(); self.assertEqual(first,self.report())
        self.assertEqual(first["status"],"complete")
        self.assertFalse(first["operational_scoring"])
        self.assertEqual(first["selected_tactic_id"],"r4-example")
        self.assertEqual(len(first["players"][0]["slots"]),11)
        self.assertEqual(first["players"][0]["slots"][0]["ip"]["role_status"],"user_defined")
        self.meta.update(build="27.1.0",db_version=3756); self.process()
        unsupported=self.report(); self.assertEqual(unsupported["status"],"unavailable")
        self.assertEqual(unsupported["players"][0]["parser_compatibility"],"captured_supported_contract")
        self.assertEqual(unsupported["players"][0]["numerical_build_compatibility"],"unsupported_game_build")
        self.assertEqual(unsupported["players"][0]["model_unavailable_reason"],"unsupported_game_build")
        self.assertTrue(all(s["combined_role_ability"] is None for p in unsupported["players"] for s in p["slots"]))

    def test_unsupported_parser_is_independent_of_numerical_build(self):
        self.meta["fmsave_version"]="0.14.0"; self.process()
        p=self.report()["players"][0]
        self.assertEqual(p["parser_compatibility"],"unverified_parser_contract")
        self.assertEqual(p["numerical_build_compatibility"],"compatible")
        self.assertEqual(p["model_unavailable_reason"],"unsupported_observation_schema")

    def test_read_scope_rejects_identity_hash_and_wrong_career(self):
        self.process()
        with self.assertRaises(ValueError): r4.read_scope(self.dbpath,"other-career")
        with self.db:
            self.db.execute("UPDATE player_versions SET record_json=? WHERE player_key=?",(json.dumps({"uid":"99"}),watcher.identity(self.world[0])))
        with self.assertRaises(ValueError): self.scope()

    def test_explicit_cli_selection_and_no_overwrite_on_invalid_request(self):
        self.process()
        argv=["assess","--db",str(self.dbpath),"--career",CAREER,"--catalogue",str(CATALOGUE),"--output-dir",str(self.root),
              "--registry",str(REGISTRY),"--select","r4-example","--model",role_ability.FM27_MODEL_ID]
        r4.main(argv)
        path=self.root/r4.REPORT_FILENAME; before=path.read_bytes()
        self.assertEqual(json.loads(before)["selected_tactic_id"],"r4-example")
        with self.assertRaises(SystemExit): r4.main(argv[:-1]+["unknown-model"])
        self.assertEqual(path.read_bytes(),before)

    def test_selection_revalidates_even_rehashed_invalid_roles_and_origin(self):
        selected,cat=self.selection(); path=self.root/"selected_tactic.json"
        path.write_text(json.dumps(selected),encoding="utf-8"); self.selection(persisted=path)
        forged=copy.deepcopy(selected); forged["tactic"]["slots"][0]["ip"]["role_id"]="ip.winger"
        forged["tactic_sha256"]=tactic.tactic_sha256(forged["tactic"])
        path.write_text(json.dumps(forged),encoding="utf-8")
        with self.assertRaises(ValueError): self.selection(persisted=path)
        with self.assertRaises(ValueError): r4.validate_selection(forged,cat)
        fake=copy.deepcopy(selected); fake["tactic"]["slots"][0]["ip"]["role_status"]="game_observed"
        fake["tactic_sha256"]=tactic.tactic_sha256(fake["tactic"])
        with self.assertRaises(ValueError): r4.validate_selection(fake,cat)
        fake=copy.deepcopy(selected); fake["selected_id"]="other"
        with self.assertRaises(ValueError): r4.validate_selection(fake,cat)
        fake=copy.deepcopy(selected); fake["tactic"]["source"]["kind"]="save_import"
        with self.assertRaises(ValueError): r4.validate_selection(fake,cat)
        cat["roles"]["ip.goalkeeper"]["key_attributes"].append("invented")
        with self.assertRaises(ValueError): r4.validate_selection(selected,cat)

    def test_missing_positive_weight_phase_and_atomic_publication(self):
        self.process(); config=(ROOT/"formations/r4-manual-example.toml").read_text(encoding="utf-8")
        config=config.replace('oop = {position = "gk", side = "centre", role_status = "user_defined", role_id = "oop.goalkeeper"}',
                              'oop = {position = "gk", side = "centre", role_status = "unknown", role_reason = "not confirmed"}')
        (self.root/"draft.toml").write_text(config,encoding="utf-8")
        registry=self.root/"registry.toml"; registry.write_text('version=1\n[tactics]\nr4-example="draft.toml"\n',encoding="utf-8")
        sel,cat=r4.selected_tactic(registry,CATALOGUE,"r4-example")
        report=r4.build_report(self.scope(),sel,cat,model_id=role_ability.FM27_MODEL_ID)
        self.assertEqual(report["status"],"partial")
        self.assertIsNone(report["players"][0]["slots"][0]["combined_role_ability"])
        self.assertEqual(report["players"][0]["slots"][0]["missing_weighted_phases"],["oop"])
        dest=r4.publish(self.root,r4.REPORT_FILENAME,report); original=dest.read_bytes()
        with patch.object(r4.os,"replace",side_effect=OSError("invented failure")),self.assertRaises(OSError):
            r4.publish(self.root,r4.REPORT_FILENAME,self.report())
        self.assertEqual(dest.read_bytes(),original); self.assertEqual(list(self.root.glob(".r4-*.tmp")),[])

    def test_extract_tactics_same_accepted_copy_and_permutation(self):
        self.process(); before=list(self.db.iterdump()); self.calls.clear()
        youth=copy.deepcopy(tactic_export(1)); youth.update(team_id=1235,team_slot=1)
        self.records=[tactic_export(5),youth,tactic_export(2)]
        with patch.object(watcher,"fmsave",side_effect=self.fake_parser):
            inventory=r4.extract_inventory(self.dbpath,CAREER,self.save,CATALOGUE)
        self.assertEqual([x["stored_index"] for x in inventory["tactics"]],[2,5])
        self.assertIsNone(inventory["active_tactic_id"])
        slots=inventory["tactics"][0]["tactic"]["slots"]
        self.assertEqual([slots[i]["oop"]["position"] for i in (1,4,9)],["dr","amr","dl"])
        self.assertEqual(slots[2]["ip"]["side"],"left")
        self.assertEqual(slots[3]["ip"]["side"],"right")
        self.assertTrue(all(s[p]["role_id"] is None for s in slots for p in tactic.PHASES))
        self.assertEqual(slots[1]["oop"]["role_status"],"ambiguous")
        self.assertTrue(all(not path.exists() for _,path,_ in self.calls))
        self.assertEqual(list(self.db.iterdump()),before)
        self.assertNotIn("players",[args[0] for cmd,_,args in self.calls if cmd=="export"])

    def test_tactic_identity_and_invalid_permutation_fail_closed(self):
        self.process(); scope=self.scope(); _,cat=self.selection(); digest=watcher.sha_file(self.save)
        for bad in ({"club_uid":999},{"team_id":999},{"team_slot":1}):
            row=tactic_export(); row.update(bad)
            with self.assertRaises(ValueError): r4.inventory(scope,self.meta,digest,self.clubs,[row],cat)
        row=tactic_export(); row["slots"][1]["unknown"]["out_of_possession_position_index"]=0
        result=r4.inventory(scope,self.meta,digest,self.clubs,[row],cat)
        self.assertIsNone(result["tactics"][0]["tactic"])
        row=tactic_export(); row["slots"][1]["out_of_possession_positions_code"]=[5]
        result=r4.inventory(scope,self.meta,digest,self.clubs,[row],cat)
        self.assertIsNone(result["tactics"][0]["tactic"]["slots"][9]["oop"]["position"])
        self.managed[0]["manager_staff_uid"]="999"
        with patch.object(watcher,"fmsave",side_effect=self.fake_parser),self.assertRaises(ValueError):
            r4.extract_inventory(self.dbpath,CAREER,self.save,CATALOGUE)
        self.save.write_bytes(b"different save")
        with patch.object(watcher,"fmsave",side_effect=self.fake_parser),self.assertRaises(ValueError):
            r4.extract_inventory(self.dbpath,CAREER,self.save,CATALOGUE)

    def test_legacy_operational_assessment_and_xi_parity_after_raw_only_change(self):
        self.process()
        def operational():
            people,_,_=bridge.get_database(self.dbpath,CAREER)
            bridge.scored_people(people,MODEL,scorer=scoring.weighted)
            data=tactical_assessment.build_assessments(formation.load_formation(ROOT/"formations/default.toml",MODEL),MODEL,people,
                codes=formation.FM_POSITION_CODES,scorer=scoring.weighted,career=CAREER,formation_source="default.toml",model_sha256="invented")
            xi=optimal_xi.build_optimal_xi(formation.load_formation(ROOT/"formations/default.toml",MODEL),data)
            return data,xi
        baseline=operational(); role_before=self.report()
        self.world[0]["raw_attributes_pace"]="90"; self.process()
        self.assertEqual(operational(),baseline)
        self.assertNotEqual(self.report(),role_before)


if __name__=="__main__": unittest.main()
