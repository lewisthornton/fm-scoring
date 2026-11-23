import {test, expect, type Page} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import {join} from "node:path";
import {execFileSync} from "node:child_process";
import type {Envelope, Overview, Signing} from "../src/types";

test("shared shell preserves pinned navigation and exposes squad directory",async ({page,request},info)=>{
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"Squad overview"})).toBeVisible();
  const generation=new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation");
  const nav=page.getByRole("navigation",{name:"Workspaces"});
  await expect(nav.getByRole("button",{name:"Overview"})).toHaveAttribute("aria-current","page");
  await page.keyboard.press("Tab");
  await page.getByRole("link",{name:"Skip to content"}).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await nav.getByRole("button",{name:"Overview"}).focus();
  await page.evaluate(()=>window.scrollTo(0,0));
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:900});
    await page.screenshot({path:info.outputPath("overview-"+width+".png"),fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa"]).analyze()).violations.map(v=>v.id)).toEqual([]);
  }
  await nav.getByRole("button",{name:"Squad",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Squad directory",exact:true})).toBeVisible();
  await expect(page.getByRole("region",{name:"Squad directory table"})).toBeVisible();
  await expect(page.getByRole("main")).toBeFocused();
  await nav.getByRole("button",{name:"Tactics & XI"}).click();
  await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();
  await expect(page.getByText("Select a pitch position or table row.")).toBeVisible();
  await page.screenshot({path:info.outputPath("tactics-mobile.png"),fullPage:true});
  const overview:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation:generation!}})).json();
  const assigned=overview.data.baseline.find(a=>a.player_id)!;
  const player=overview.data.players.find(p=>p.player_id===assigned.player_id)!;
  const slot=overview.data.slots.find(s=>s.id===assigned.slot_id)!;
  await page.getByRole("table",{name:/XI assignments/}).getByRole("button",{name:player.display_name,exact:true}).click();
  await expect(page.getByRole("heading",{name:slot.label,exact:true})).toBeVisible();
  expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("slot")).toBe(slot.id);
  await nav.getByRole("button",{name:"Data & Settings"}).click();
  await expect(page.getByRole("heading",{name:"Generation evidence"})).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();
  expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")).toBe(generation);
});

test("squad search, sorting, evidence, navigation and responsive layouts",async ({page,request},info)=>{
  const historySnapshot=()=>page.evaluate(()=>({href:location.href,length:history.length,state:history.state}));
  await page.emulateMedia({reducedMotion:"reduce"});
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"Squad overview"})).toBeVisible();
  const generation=new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")!;
  const over:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation}})).json();
  const squad=over.data.players.filter(p=>p.cohorts.includes("squad"));
  const assigned=over.data.baseline.find(a=>a.player_id&&squad.some(p=>p.player_id===a.player_id))!;
  const player=squad.find(p=>p.player_id===assigned.player_id)!;
  await page.getByRole("button",{name:"Squad",exact:true}).click();
  await expect(page.getByRole("status").filter({hasText:`${squad.length} of ${squad.length} active squad players`})).toBeVisible();
  const squadHistory=await historySnapshot();
  for(const [label,count] of [["Active squad",squad.length],["Known availability",squad.filter(p=>p.availability!=="unknown").length],["Unknown availability",squad.filter(p=>p.availability==="unknown").length],["Assigned in XI",over.data.baseline.filter(a=>a.player_id).length]] as const){
    await expect(page.locator(".squad-metrics .metric").filter({has:page.getByText(label,{exact:true})}).locator("strong")).toHaveText(String(count));
  }
  const table=page.getByRole("region",{name:"Squad directory table"});
  await expect(table.getByRole("row")).toHaveCount(Math.min(25,squad.length)+1);
  for(const width of [1440,1280,768,390]){
    await page.setViewportSize({width,height:900});
    await page.screenshot({path:info.outputPath(`squad-${width}.png`),fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    expect((await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa"]).analyze()).violations.map(v=>v.id)).toEqual([]);
  }
  const search=page.getByRole("searchbox",{name:"Search"});
  await search.fill(player.display_name.toUpperCase());
  await expect(table.getByRole("button",{name:player.display_name,exact:true})).toBeVisible();
  for(const width of [1440,390]){await page.setViewportSize({width,height:900});await page.screenshot({path:info.outputPath(`squad-filtered-${width}.png`),fullPage:true});}
  await table.getByRole("button",{name:player.display_name,exact:true}).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();
  const params=new URLSearchParams(new URL(page.url()).hash.slice(1));
  expect(params.get("slot")).toEqual(assigned.slot_id);expect(params.get("player")).toEqual(player.player_id);expect(params.get("generation")).toEqual(generation);
  const tacticsHistory=await historySnapshot();
  expect(tacticsHistory.length).toBe(squadHistory.length+1);
  const expectSquad=async()=>{await expect(page).toHaveURL(squadHistory.href);await expect(page.getByRole("heading",{name:"Squad directory"})).toBeVisible();};
  const expectTactics=async()=>{await expect(page).toHaveURL(tacticsHistory.href);await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();await expect(page.getByRole("heading",{name:over.data.slots.find(s=>s.id===assigned.slot_id)!.label,exact:true})).toBeVisible();};
  await page.goBack();await expectSquad();
  await page.goForward();await expectTactics();
  // Firefox 141 can add a same-URL history entry on full reload of a hash
  // navigation, even on a plain HTML page. Verify restoration separately;
  // traverse exactly one extra entry only if reload demonstrably added it.
  await page.reload();await expectTactics();
  const reloaded=await historySnapshot();
  expect([tacticsHistory.length,tacticsHistory.length+1]).toContain(reloaded.length);
  await page.goBack();
  const backed=await historySnapshot();
  const historyEvidence=info.outputPath("history-navigation.json");
  fs.writeFileSync(historyEvidence,JSON.stringify({squadHistory,tacticsHistory,reloaded,backed},null,2));
  await info.attach("history-navigation",{path:historyEvidence,contentType:"application/json"});
  if(backed.href===tacticsHistory.href){
    expect(reloaded.length).toBe(tacticsHistory.length+1);
    await expectTactics();
    await page.goBack();
  }
  await expectSquad();
  await page.goForward();await expectTactics();
  await page.goBack();await expectSquad();
  await table.getByRole("button",{name:/Player ↑/}).click();
  await expect(table.getByRole("columnheader",{name:/Player/})).toHaveAttribute("aria-sort","descending");
  await page.getByRole("combobox",{name:"Availability",exact:true}).selectOption("unknown");
  const unknown=squad.filter(p=>p.availability==="unknown").length;
  await expect(page.getByRole("status").filter({hasText:`${unknown} of ${squad.length} active squad players`})).toBeVisible();
  await page.getByRole("button",{name:"Reset filters"}).click();
  await page.getByRole("combobox",{name:"Analysis domain"}).selectOption("keeper");
  await expect(page.getByRole("status").filter({hasText:`${squad.filter(p=>p.keeper).length} of ${squad.length} active squad players`})).toBeVisible();
  await page.getByRole("button",{name:"Reset filters"}).click();
  await search.fill("zzzz-no-player");
  await expect(page.getByText("No players match these filters.")).toBeVisible();
  for(const width of [1440,390]){await page.setViewportSize({width,height:900});await page.screenshot({path:info.outputPath(`squad-empty-${width}.png`),fullPage:true});}
  await page.getByRole("button",{name:"Reset filters"}).click();
  await expect(table).toBeVisible();
});

test("empty directory is distinct from unavailable pinned generation",async ({page,request},info)=>{
  // An empty import is rejected by the watcher. Exercise the defensive UI
  // boundary using an explicitly synthetic overview card projection only.
  const current=await (await request.get("/api/current")).json();
  const generation=current.generation_id;
  const over:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation}})).json();
  await page.route("**/api/overview?*",async route=>route.fulfill({json:{...over,data:{...over.data,players:[],baseline:[]}}}));
  await page.goto("/#"+new URLSearchParams({page:"Squad",generation}));
  await expect(page.getByText(/No active squad players represented/)).toBeVisible();
  await expect(page.getByText(/0 of 0 active squad players/)).toBeVisible();
  for(const width of [1440,390]){await page.setViewportSize({width,height:900});await page.screenshot({path:info.outputPath(`squad-no-active-${width}.png`),fullPage:true});}
  await page.unroute("**/api/overview?*");
  await page.goto("/#"+new URLSearchParams({page:"Squad",generation:"0".repeat(32)}));
  await expect(page.getByRole("heading",{name:"Pinned generation unavailable"})).toBeVisible();
  await expect(page.getByText(/No active squad players represented/)).toHaveCount(0);
});

test("squad pagination is bounded and keyboard-accessible",async ({page,request})=>{
  const {generation_id:generation}=await (await request.get("/api/current")).json();
  const over:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation}})).json();
  const original=over.data.players.filter(p=>p.cohorts.includes("squad"));
  // Explicit synthetic card projection; no extra imports or fabricated XI assignments.
  const extra=Array.from({length:26},(_,i)=>({...original[0],player_id:JSON.stringify(["rangers","invented-career",`pagination-${i}`]),display_name:`ZZ invented squad ${String(i+1).padStart(2,"0")}`,cohorts:["squad"]}));
  const total=original.length+extra.length;
  await page.route("**/api/overview?*",route=>route.fulfill({json:{...over,data:{...over.data,players:[...over.data.players,...extra]}}}));
  await page.goto("/#"+new URLSearchParams({page:"Squad",generation}));
  const table=page.getByRole("region",{name:"Squad directory table"}),rows=table.getByRole("row");
  const previous=page.getByRole("button",{name:"Previous",exact:true}),next=page.getByRole("button",{name:"Next",exact:true});
  await expect(rows).toHaveCount(26);await expect(previous).toBeDisabled();
  await expect(page.getByText(`${total} of ${total} active squad players`)).toBeVisible();
  await next.focus();await page.keyboard.press("Enter");
  await expect(page.getByText(`Page 2 of ${Math.ceil(total/25)}`)).toBeVisible();
  await expect(rows).toHaveCount(Math.min(25,total-25)+1);
  await previous.focus();await page.keyboard.press("Enter");await expect(previous).toBeDisabled();
  await next.click();
  await page.getByRole("searchbox",{name:"Search"}).fill(extra.at(-1)!.display_name);
  await expect(rows).toHaveCount(2);
  await expect(table.getByText("No supported player destination")).toBeVisible();
  await expect(table.getByRole("button",{name:extra.at(-1)!.display_name})).toHaveCount(0);
  await page.getByRole("button",{name:"Reset filters"}).click();await expect(rows).toHaveCount(26);await expect(previous).toBeDisabled();
  expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")).toBe(generation);
});

test("squad remains pinned until explicit generation switch",async ({page,request})=>{
  const root=join(process.env.TOUCHLINE_FIXTURE_DIR!,"generations");
  const first=JSON.parse(fs.readFileSync(join(root,"current.json"),"utf8")).generation_id as string;
  const second=fs.readdirSync(join(root,"generations")).find(id=>id!==first)!;
  const rollback=(id:string)=>execFileSync("python",["-c","import sys; from touchline_generation import rollback; rollback(sys.argv[1],sys.argv[2])",root,id],{cwd:".."});
  const overview:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation:first}})).json();
  const overlap=overview.data.players.find(p=>p.cohorts.includes("squad")&&p.cohorts.includes("target"))!;
  try{
    await page.goto("/#"+new URLSearchParams({page:"Squad",generation:first,slot:"lb"}));
    const row=page.getByRole("row").filter({hasText:overlap.display_name});
    await expect(row.getByText("target",{exact:true})).toBeVisible();
    rollback(second);
    await expect(page.getByRole("button",{name:"Switch generation"})).toBeVisible({timeout:20000});
    await expect(row.getByText("target",{exact:true})).toBeVisible();
    await page.getByRole("button",{name:"Switch generation"}).click();
    await expect(page.getByRole("heading",{name:"Squad directory"})).toBeVisible();
    await expect(row.getByText("squad",{exact:true})).toBeVisible();
    await expect(row.getByText("target",{exact:true})).toHaveCount(0);
    expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")).toEqual(second);
    await page.goBack();await expect(row.getByText("target",{exact:true})).toBeVisible();
  }finally{rollback(first);}
});

test("assigned squad link reconciles canonical identity across generation switch",async ({page,request})=>{
  const root=join(process.env.TOUCHLINE_FIXTURE_DIR!,"generations");
  const first=JSON.parse(fs.readFileSync(join(root,"current.json"),"utf8")).generation_id as string;
  const second=fs.readdirSync(join(root,"generations")).find(id=>id!==first)!;
  const rollback=(id:string)=>execFileSync("python",["-c","import sys; from touchline_generation import rollback; rollback(sys.argv[1],sys.argv[2])",root,id],{cwd:".."});
  const old:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation:first}})).json();
  const destination:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation:second}})).json();
  const assigned=old.data.baseline.find(a=>a.slot_id==="lb")!;
  const player=old.data.players.find(p=>p.player_id===assigned.player_id)!;
  const moved=destination.data.baseline.find(a=>a.player_id===player.player_id);
  expect(moved?.slot_id).toBe("lb_new");
  const params=()=>new URLSearchParams(new URL(page.url()).hash.slice(1));
  try{
    rollback(second);
    for(const scenario of ["moved","unassigned","no longer squad","removed"] as const){
      // Moved uses the genuine published generations. The other cases are
      // explicit invented overview projections to isolate frontend reconciliation.
      if(scenario!=="moved")await page.route("**/api/overview?*",route=>{
        if(new URL(route.request().url()).searchParams.get("generation")!==second)return route.continue();
        const players=destination.data.players.flatMap(p=>p.player_id!==player.player_id?[p]:scenario==="removed"?[]:[scenario==="no longer squad"?{...p,cohorts:["target"]}:p]);
        const baseline=destination.data.baseline.map(a=>a.player_id===player.player_id?{...a,player_id:null}:a);
        return route.fulfill({json:{...destination,data:{...destination.data,players,baseline}}});
      });
      await page.goto("/#"+new URLSearchParams({page:"Squad",generation:first}));
      await page.getByRole("searchbox",{name:"Search"}).fill(player.display_name);
      await page.getByRole("button",{name:player.display_name,exact:true}).click();
      await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();
      expect(params().get("generation")).toBe(first);expect(params().get("slot")).toBe("lb");expect(params().get("player")).toBe(player.player_id);
      await page.getByRole("button",{name:"Switch generation"}).click();
      await expect.poll(()=>params().get("generation")).toBe(second);
      if(scenario==="moved"){
        expect(params().get("slot")).toBe("lb_new");expect(params().get("player")).toBe(player.player_id);
        await expect(page.getByRole("heading",{name:"Left-back",exact:true})).toBeVisible();
      }else{
        expect(params().get("slot")).toBe("");expect(params().get("player")).toBe("");
        await expect(page.getByText("Select a pitch position or table row.")).toBeVisible();
        await expect(page.getByText(/Selected player is no longer/)).toBeVisible();
      }
      await page.unroute("**/api/overview?*");
    }
  }finally{rollback(first);}
});

async function keyboardActivate(page:Page, text:RegExp) {
  for(let i=0;i<180;i++){
    const label=await page.evaluate(()=>document.activeElement?.textContent??"");
    const button=await page.evaluate(()=>document.activeElement?.tagName==="BUTTON");
    if(button&&text.test(label)){await page.keyboard.press("Enter");return;}
    await page.keyboard.press("Tab");
  }
  throw new Error("Keyboard target not reached: "+text);
}
test("canonical workflow, keyboard, offline requests, responsive evidence and measurements",async ({page,request},info)=>{
  await page.emulateMedia({reducedMotion:"reduce"});
  const external:string[]=[];
  page.on("request",r=>{if(!r.url().startsWith("http://127.0.0.1:8765/"))external.push(r.url());});
  const start=Date.now();
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"Squad overview"})).toBeVisible();
  const initial=Date.now()-start;
  const gid=new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")!;
  const response=await request.get("/api/overview",{params:{generation:gid}});
  const bytes=(await response.body()).length;
  const over:Envelope<Overview>=await response.json();
  expect(over.provenance.historical_selection_fingerprint_evidence).toEqual({
    snapshot_count:1,sha256_format_count:0,unverified:[{snapshot_id:1,status:"unverified_invalid"}]
  });
  const target=over.data.recommendations.find(r=>r.classification==="completeness_upgrade"||r.classification==="starting_upgrade")!;
  const sid=target.selected_slot_id!;
  const slot=over.data.slots.find(s=>s.id===sid)!;
  // Overview → weakness, using Tab/Enter only.
  await keyboardActivate(page,new RegExp(slot.label));
  await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();
  await expect(page.getByRole("heading",{name:slot.label,exact:true})).toBeVisible();
  await expect(page.getByRole("table",{name:/XI assignments/})).toBeVisible();
  await keyboardActivate(page,/Find recruitment candidates/);
  await expect(page.getByRole("heading",{name:"Recruitment targets"})).toBeVisible();
  const targetPlayer=over.data.players.find(p=>p.player_id===target.player_id)!;
  await expect(page.getByRole("button",{name:targetPlayer.display_name,exact:true})).toBeVisible();
  await keyboardActivate(page,new RegExp(targetPlayer.display_name.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")));
  await expect(page.getByRole("heading",{name:targetPlayer.display_name,exact:true})).toBeVisible();
  await expect(page.getByRole("heading",{name:targetPlayer.display_name,exact:true})).toBeFocused();
  await keyboardActivate(page,/Back to candidate list/);
  await expect(page.getByRole("button",{name:targetPlayer.display_name,exact:true})).toBeFocused();
  await keyboardActivate(page,/Inspect signing impact/);
  await expect(page.getByRole("heading",{name:"Revised XI"})).toBeVisible();
  const signingResponse=await request.get("/api/signing",{params:{generation:gid,player:target.player_id}});
  const signing:Envelope<Signing>=await signingResponse.json();
  await expect(page.getByText("Enters the XI at "+slot.label+".",{exact:true})).toBeVisible();
  const revised=page.getByRole("table",{name:/XI assignments/}).last();
  for(const row of signing.data.xi!.assignments){
    const label=over.data.slots.find(s=>s.id===row.slot_id)!.label;
    const player=over.data.players.find(p=>p.player_id===row.player_id)?.display_name??"Vacant";
    const tr=revised.getByRole("row").filter({hasText:label});
    await expect(tr.getByText(player,{exact:true})).toBeVisible();
    await expect(tr.getByText(row.attribute_profile_score==null?"—":row.attribute_profile_score.toFixed(2),{exact:true})).toBeVisible();
  }
  await page.getByRole("button",{name:"Inspect tactical depth"}).click();
  await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading",{name:"Revised XI"})).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading",{name:"Revised XI"})).toBeVisible();
  const search=page.getByRole("textbox",{name:"Search"});
  const filterStart=Date.now();
  await search.fill(targetPlayer.display_name);
  await expect(page.getByText(/1 of \d+ active targets/)).toBeVisible();
  const filterMs=Date.now()-filterStart;
  await search.fill("");
  const candidatesResponse=await request.get("/api/candidates",{params:{generation:gid,slot:sid}});
  for(const width of [1440,1280,768,390]){
    await page.setViewportSize({width,height:900});
    await page.screenshot({path:info.outputPath("recruitment-"+width+".png"),fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  }
  // 1440px at 200% zoom corresponds to a 720 CSS-pixel layout viewport.
  // This is a reflow check, not a claim of testing browser chrome zoom.
  await page.setViewportSize({width:720,height:450});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  expect(await page.evaluate(()=>matchMedia("(prefers-reduced-motion: reduce)").matches)).toBeTruthy();
  await page.setViewportSize({width:390,height:900});
  const axe=await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa"]).analyze();
  expect(axe.violations.map(v=>v.id)).toEqual([]);
  expect(external).toEqual([]);
  const measurements={initial_ms:initial,overview_bytes:bytes,candidates_bytes:(await candidatesResponse.body()).length,signing_bytes:(await signingResponse.body()).length,filter_ms:filterMs,targets:over.data.recommendations.length};
  fs.writeFileSync(info.outputPath("measurements.json"),JSON.stringify(measurements,null,2));
  console.log(measurements);
  const elsewhere=over.data.slots.find(s=>s.id!==sid&&!target.eligible_slot_ids.includes(s.id))!;
  await page.getByLabel("Selection slot").selectOption(elsewhere.id);
  await expect(page.getByText("Ineligible for this slot, but improves the XI elsewhere.")).toBeVisible();
  await expect(page.getByText("Actual hypothetical assignment: "+slot.label+".",{exact:true})).toBeVisible();
});

test("generation remains pinned through updates and missing selections clear",async ({page,request})=>{
  const root=join(process.env.TOUCHLINE_FIXTURE_DIR!,"generations");
  const pointer=join(root,"current.json");
  const first=JSON.parse(fs.readFileSync(pointer,"utf8")).generation_id as string;
  const second=fs.readdirSync(join(root,"generations")).find(id=>id!==first)!;
  const rollback=(id:string)=>execFileSync("python",["-c","import sys; from touchline_generation import rollback; rollback(sys.argv[1],sys.argv[2])",root,id],{cwd:".."});
  const overview:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation:first}})).json();
  const candidate=overview.data.recommendations.find(r=>r.classification!=="already_in_squad")!;
  const url="/#"+new URLSearchParams({page:"Recruitment",generation:first,slot:"lb",player:candidate.player_id,impact:"1"});
  try{
    await page.goto(url);
    await expect(page.getByRole("heading",{name:"Revised XI"})).toBeVisible();
    rollback(second);
    await expect(page.getByRole("button",{name:"Switch generation"})).toBeVisible({timeout:20000});
    await expect(page.getByRole("heading",{name:"Revised XI"})).toBeVisible();
    expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")).toEqual(first);
    const saved=fs.readFileSync(pointer);
    fs.writeFileSync(pointer,"{}");
    await expect(page.getByText(/Current generation unavailable/)).toBeVisible({timeout:20000});
    await expect(page.getByRole("heading",{name:"Revised XI"})).toBeVisible();
    fs.writeFileSync(pointer,saved);
    await expect(page.getByRole("button",{name:"Switch generation"})).toBeVisible({timeout:20000});
    await page.getByRole("button",{name:"Switch generation"}).click();
    await expect(page.getByText(/Selected player is no longer/)).toBeVisible();
    await expect(page.getByText(/Selected slot no longer exists/)).toBeVisible();
    await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible();
    await page.getByRole("navigation",{name:"Workspaces"}).getByRole("button",{name:"Recruitment"}).click();
    await page.getByLabel("Selection slot").selectOption("lb_new");
    await expect(page.getByText(/0 of 0 active targets/)).toBeVisible();
    expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")).toEqual(second);
    await page.goto("/#"+new URLSearchParams({page:"Overview",generation:"0".repeat(32)}));
    await expect(page.getByRole("heading",{name:"Pinned generation unavailable"})).toBeVisible();
  }finally{rollback(first);}
});
