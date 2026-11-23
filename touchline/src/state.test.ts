import {test} from "node:test";
import assert from "node:assert/strict";
import {filterCandidates, routeFrom, routeTo, switchGeneration} from "./state";
import {squadRows, filterSquad, squadSummary} from "./squad";
import type {Player, Assignment, Slot} from "./types";
const player=(id:string,cohorts:string[],availability:string,keeper=false):Player=>({player_id:id,display_name:"Namesake",club:"Invented",cohorts,availability,keeper,loan_state:"unknown",record_game_date:"2026-07-01",last_seen_game_date:"2026-07-02",game_build:null});
test("directory only includes active squad, counts overlap once and preserves unknown",()=>{
  const rows=squadRows([player("b",["squad","target"],"unknown"),player("a",["squad"],"available",true),player("c",["target"],"available")],[],[]);
  assert.deepEqual(squadSummary(rows),{total:2,known:1,unknown:1,assigned:0});
  assert.deepEqual(filterSquad(rows,"NAMESAKE","unknown","all","name",false).map(r=>r.player.player_id),["b"]);
  assert.deepEqual(filterSquad(rows,"","all","keeper","name",false).map(r=>r.player.player_id),["a"]);
  for(const reverse of [false,true]) assert.deepEqual(filterSquad(rows,"","all","all","name",reverse).map(r=>r.player.player_id),["a","b"]);
});
test("published assignments attach by canonical identity and not player name",()=>{
  const rows=squadRows([player("b",["squad"],"unknown"),player("a",["squad"],"available")],[{player_id:"a",slot_id:"lb"} as Assignment],[{id:"lb",label:"Left back"} as Slot]);
  assert.equal(rows.find(r=>r.player.player_id==="a")?.slot?.id,"lb");
  assert.equal(rows.find(r=>r.player.player_id==="b")?.slot,undefined);
});
test("all sort directions preserve deterministic namesake identity and missing values",()=>{
  const a=player("a",["squad"],"unknown"),b=player("b",["squad"],"unavailable"),c=player("c",["squad"],"available");
  a.club="";a.record_game_date=null;b.club="Z";c.club="A";b.record_game_date="2026-05-01";
  const rows=squadRows([b,a,c],[],[]);
  for(const key of ["name","club","cohort","position","availability","xi","observed"] as const)for(const reverse of [false,true]){
    const ordered=filterSquad(rows,"","all","all",key,reverse).map(r=>r.player.player_id);
    assert.deepEqual(ordered,filterSquad([...rows].reverse(),"","all","all",key,reverse).map(r=>r.player.player_id));
    if(key==="club"||key==="observed")assert.equal(ordered.at(-1),"a");
  }
  assert.deepEqual(filterSquad(rows,"","unavailable","all","name",false).map(r=>r.player.player_id),["b"]);
  assert.equal(rows.find(r=>r.player.player_id==="b")?.player.record_game_date,"2026-05-01");
});
test("squad switching clears selection no longer in active squad without leaving directory",()=>{
  const r={page:"Squad" as const,generation:"old",slot:"lb",player:"A",impact:false};
  const next=switchGeneration(r,"new",["rb"],["A"],["A"],[]);
  assert.equal(next.route.page,"Squad");assert.equal(next.route.player,"");assert.equal(next.route.slot,"");assert.match(next.notice,/no longer/);
});
test("assigned-player tactical link follows the same canonical player or clears when unassigned",()=>{
  const r={page:"Tactics & XI" as const,generation:"old",slot:"lb",player:"A",impact:false};
  const moved=switchGeneration(r,"new",["lb","rb"],["A"],[],["A"],"rb");
  assert.equal(moved.route.slot,"rb");assert.equal(moved.route.player,"A");
  const removed=switchGeneration(r,"new",["lb"],["A"],["A"],[],null);
  assert.equal(removed.route.slot,"");assert.equal(removed.route.player,"");assert.match(removed.notice,/no longer/);
});
test("opaque IDs round trip across route and back",()=>{
  const r={page:"Recruitment" as const,generation:"a".repeat(32),slot:"lcb",player:'["rangers","test","a/b & ñ"]',impact:true};
  assert.deepEqual(routeFrom(routeTo(r)),r);
});
test("switch clears missing slot and player, keeps valid context",()=>{
  const r={page:"Recruitment" as const,generation:"old",slot:"lb",player:"A",impact:true};
  assert.equal(switchGeneration(r,"new",["lb"],["A"],["A"]).route.impact,true);
  const gone=switchGeneration(r,"new",["rb"],["B"],["B"]);
  assert.equal(gone.route.page,"Tactics & XI");assert.equal(gone.route.player,"");assert.equal(gone.route.slot,"");assert.match(gone.notice,/no longer/);
});
test("missing tactical slot clears action context while retaining a valid M1 candidate identity",()=>{
  const r={page:"Recruitment" as const,generation:"old",slot:"lb",player:"A",impact:true};
  const gone=switchGeneration(r,"new",["rb"],["A"],["A"]);
  assert.equal(gone.route.page,"Tactics & XI");assert.equal(gone.route.slot,"");
  assert.equal(gone.route.impact,false);assert.equal(gone.route.player,"A");
  assert.match(gone.notice,/Selected slot no longer exists/);
});
test("filter preserves engine order and namesakes remain separate",()=>{
  const rows=[{player_id:"z",eligible:true},{player_id:"a",eligible:false},{player_id:"b",eligible:true}];
  assert.deepEqual(filterCandidates(rows,{z:"Same",a:"Same",b:"Same"},"same",true).map(x=>x.player_id),["z","b"]);
});
