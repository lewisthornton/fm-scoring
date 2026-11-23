import {test} from "node:test";
import assert from "node:assert/strict";
import {filterCandidates, routeFrom, routeTo, switchGeneration} from "./state";
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
test("filter preserves engine order and namesakes remain separate",()=>{
  const rows=[{player_id:"z",eligible:true},{player_id:"a",eligible:false},{player_id:"b",eligible:true}];
  assert.deepEqual(filterCandidates(rows,{z:"Same",a:"Same",b:"Same"},"same",true).map(x=>x.player_id),["z","b"]);
});
