import {test,expect} from "@playwright/test";
import {readFileSync,readdirSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {execFileSync} from "node:child_process";
import type {Envelope,Overview} from "../src/types";

test("representative render, filtering and generation switch measurements",async({page,request},info)=>{
  test.setTimeout(120000);
  const start=Date.now();
  await page.goto("/");
  await expect(page.getByRole("heading",{name:"Squad overview"})).toBeVisible({timeout:30000});
  const initial_ms=Date.now()-start;
  const gid=new URLSearchParams(new URL(page.url()).hash.slice(1)).get("generation")!;
  const overview:Envelope<Overview>=await (await request.get("/api/overview",{params:{generation:gid}})).json();
  const target=overview.data.recommendations.find(r=>r.classification!=="already_in_squad")!;
  const slot="lb"; // The alternate fixture deliberately removes this exact slot.
  const name=overview.data.players.find(p=>p.player_id===target.player_id)!.display_name;
  await page.goto("/#"+new URLSearchParams({page:"Recruitment",generation:gid,slot}));
  await expect(page.getByText(new RegExp(overview.data.recommendations.length+" active targets"))).toBeVisible({timeout:30000});
  const table=page.getByRole("table",{name:"Candidate comparison at selected slot"});
  expect(await table.getByRole("row").count()).toBeLessThanOrEqual(21);
  if(overview.data.recommendations.length>20){
    await page.getByRole("button",{name:"Next",exact:true}).click();
    await expect(page.getByText(/Page 2 of/)).toBeVisible();
    await page.getByRole("button",{name:"Previous",exact:true}).click();
  }
  const filterStart=Date.now();
  await page.getByRole("textbox",{name:"Search"}).fill(name);
  await expect(page.getByText(/1 of \d+ active targets/)).toBeVisible();
  await expect(page.getByRole("button",{name,exact:true})).toBeVisible();
  const filter_ms=Date.now()-filterStart;
  const root=join(process.env.TOUCHLINE_FIXTURE_DIR!,"generations");
  const previous=JSON.parse(readFileSync(join(root,"current.json"),"utf8")).generation_id as string;
  const next=readdirSync(join(root,"generations")).find(id=>id!==previous)!;
  const rollback=(id:string)=>execFileSync("python",["-c","import sys; from touchline_generation import rollback; rollback(sys.argv[1],sys.argv[2])",root,id],{cwd:".."});
  try{
    rollback(next);
    await expect(page.getByRole("button",{name:"Switch generation"})).toBeVisible({timeout:30000});
    const switchStart=Date.now();
    await page.getByRole("button",{name:"Switch generation"}).click();
    await expect(page.getByRole("heading",{name:"Tactics & XI"})).toBeVisible({timeout:30000});
    const result={size:process.env.TOUCHLINE_BENCH_SIZE??"small",browser:info.project.name,targets:overview.data.recommendations.length,initial_ms,filter_ms,switch_ms:Date.now()-switchStart};
    console.log("TOUCHLINE PERFORMANCE",JSON.stringify(result));
    writeFileSync(info.outputPath("performance.json"),JSON.stringify(result,null,2));
  }finally{rollback(previous);}
});
