import {test, expect, type Page} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import {join} from "node:path";
import {execFileSync} from "node:child_process";
import type {Envelope, Overview, Signing} from "../src/types";

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
  const axe=await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa"]).analyze();
  expect(axe.violations.map(v=>v.id)).toEqual([]);
  expect(external).toEqual([]);
  const measurements={initial_ms:initial,overview_bytes:bytes,candidates_bytes:(await candidatesResponse.body()).length,signing_bytes:(await signingResponse.body()).length,filter_ms:filterMs,targets:over.data.recommendations.length};
  fs.writeFileSync(info.outputPath("measurements.json"),JSON.stringify(measurements,null,2));
  console.log(measurements);
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
    await expect(page.getByText(/0 of 0 active targets/)).toBeVisible();
    expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")).toEqual(second);
    await page.goto("/#"+new URLSearchParams({page:"Overview",generation:"0".repeat(32)}));
    await expect(page.getByRole("heading",{name:"Pinned generation unavailable"})).toBeVisible();
  }finally{rollback(first);}
});
