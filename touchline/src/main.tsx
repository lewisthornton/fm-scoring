import React, {useEffect, useMemo, useRef, useState} from "react";
import {createRoot} from "react-dom/client";
import {filterCandidates, pages, routeFrom, routeTo, switchGeneration, type Route} from "./state";
import type {Assignment, Candidate, Change, Envelope, Evidence, Overview, Player, Provenance, Signing, Slot, SlotData, Totals} from "./types";
import "./style.css";

type Status = {generation_id:string; provenance:Provenance};
const human = (value:string|null|undefined) => value ? value.replaceAll("_"," ") : "Not available";
const num = (value:number|null|undefined) => value == null ? "—" : value.toFixed(2);
const nameOf = (players:Map<string,Player>, id:string|null|undefined) => id ? (players.get(id)?.display_name ?? "Unavailable player") : "Vacant";
const slotOf = (slots:Slot[], id:string|null|undefined) => id ? slots.find(s=>s.id===id)?.label ?? id : "None";
async function api<T>(path:string, params:Record<string,string> = {}, signal?:AbortSignal):Promise<T> {
  const response = await fetch("/api/"+path+"?"+new URLSearchParams(params), {signal});
  const body = await response.json();
  if (!response.ok) throw new Error(human(body.error));
  if (params.generation && body.generation_id !== params.generation) throw new Error("Generation response mismatch");
  return body as T;
}
function useData<T>(path:string, params:Record<string,string>|null) {
  const key = params ? path+"?"+new URLSearchParams(params) : "";
  const [state,setState] = useState<{key:string;data?:T;error?:string}>({key:""});
  useEffect(()=>{
    if (!key || !params) return;
    const controller = new AbortController();
    api<Envelope<T>>(path,params,controller.signal).then(r=>{if(!controller.signal.aborted)setState({key,data:r.data});})
      .catch(e=>{if(!controller.signal.aborted)setState({key,error:String(e.message)});});
    return ()=>controller.abort();
  },[key]);
  return state.key===key ? state : {key};
}
function Panel({title,children}:React.PropsWithChildren<{title:string}>) {
  return <section className="panel"><h2>{title}</h2>{children}</section>;
}
function Tag({children,tone=""}:React.PropsWithChildren<{tone?:string}>) {return <span className={"tag "+tone}>{children}</span>;}
function TotalsView({totals,label}: {totals:Totals;label:string}) {
  return <div className="totals"><small>{label}</small><strong>{totals.filled_slots}/11</strong><span>XI filled</span><strong>{num(totals.outfield_total)}</strong><span>Outfield sum</span><strong>{num(totals.goalkeeper_total)}</strong><span>GK quality</span></div>;
}
function AssignmentTable({slots,rows,players,onSlot}: {slots:Slot[];rows:Assignment[];players:Map<string,Player>;onSlot?:(slot:string)=>void}) {
  return <div className="table-wrap"><table><caption>XI assignments · weighted profile scores (1–20)</caption><thead><tr><th scope="col">Slot</th><th scope="col">Player</th><th scope="col">Quality</th><th scope="col">Evidence</th></tr></thead><tbody>{slots.map(s=>{
    const a=rows.find(r=>r.slot_id===s.id);return <tr key={s.id}><td>{onSlot?<button className="text-button" onClick={()=>onSlot(s.id)}>{s.label}</button>:s.label}<small>{s.selection_position.toUpperCase()} · {s.profile}</small></td><td>{nameOf(players,a?.player_id)}</td><td>{num(a?.attribute_profile_score)}</td><td>{a?.player_id ? [a.eligibility_position?.toUpperCase(),...a.warnings.map(human)].filter(Boolean).join(" · ") || "Assigned":human(a?.vacancy_reason)}</td></tr>;
  })}</tbody></table></div>;
}
const bands:Record<string,number>={gk:6,sw:5,dl:4,dc:4,dr:4,wbl:3,wbr:3,dm:3,ml:2,mc:2,mr:2,aml:1,amc:1,amr:1,stc:0};
function Pitch({slots,rows,players,selected,onSlot}: {slots:Slot[];rows:Assignment[];players:Map<string,Player>;selected:string;onSlot:(id:string)=>void}) {
  return <div className="pitch" aria-label="Tactical pitch, selection positions">{[0,1,2,3,4,5,6].map(b=>{
    const line=slots.filter(s=>(bands[s.selection_position]??3)===b).sort((a,c)=>["left","centre","right"].indexOf(a.side)-["left","centre","right"].indexOf(c.side));
    return <div className="pitch-line" key={b}>{line.map(s=>{const a=rows.find(r=>r.slot_id===s.id);return <button key={s.id} className={"pitch-player "+(!a?.player_id?"vacant ":"")+(selected===s.id?"selected":"")} aria-pressed={selected===s.id} onClick={()=>onSlot(s.id)}><small>{s.label}</small><b>{nameOf(players,a?.player_id)}</b><span>{s.selection_position.toUpperCase()} · {num(a?.attribute_profile_score)}</span></button>;})}</div>;
  })}</div>;
}
function EvidenceView({evidence}: {evidence:Evidence|null|undefined}) {
  if (!evidence) return <p className="muted">No assigned-player evidence.</p>;
  return <div className="evidence"><p>Attribute profile <strong>{num(evidence.attribute_profile_score)}</strong> {evidence.attribute_profile_reason && human(evidence.attribute_profile_reason)}</p>
    <ul>{Object.entries(evidence.accepted_positions).map(([code,v])=><li key={code}>{code.toUpperCase()}: {v.rating??v.category??"Unknown"} · {human(v.status)} {v.reason&&"· "+human(v.reason)}</li>)}</ul>
    <p>IP / OOP fit: {num(evidence.ip.position_fit)} / {num(evidence.oop.position_fit)}. Contextual familiarity, not role ability.</p>
    {evidence.missing_evidence.length>0&&<details><summary>Evidence limitations</summary><ul>{evidence.missing_evidence.map((v,i)=><li key={i}>{human(v)}</li>)}</ul></details>}</div>;
}
function Changes({changes,slots,players}: {changes:Change[];slots:Slot[];players:Map<string,Player>}) {
  return changes.length?<div className="table-wrap"><table><caption>Assignment changes</caption><thead><tr><th>Slot</th><th>Before</th><th>After</th></tr></thead><tbody>{changes.map(c=><tr key={c.slot_id}><td>{slotOf(slots,c.slot_id)}</td><td>{nameOf(players,c.before_player_id)}</td><td>{nameOf(players,c.after_player_id)}</td></tr>)}</tbody></table></div>:<p>No assignment changes.</p>;
}
function OverviewPage({data,players,go}: {data:Overview;players:Map<string,Player>;go:(r:Partial<Route>)=>void}) {
  const vacancies=data.baseline.filter(a=>!a.player_id), uncovered=data.coverage.filter(a=>a.direct_cover_count===0), shared=data.coverage.filter(a=>a.shared_direct_deputy_ids.length>0);
  const improvements=data.recommendations.filter(r=>["completeness_upgrade","starting_upgrade"].includes(r.classification));
  return <><div className="intro"><p className="eyebrow">DECISION CENTRE</p><h1>Squad overview</h1><p>Review selection gaps, depth dependencies and precomputed recruitment opportunities.</p></div>
    <div className="metrics"><TotalsView totals={data.summary.totals} label="Current optimal XI"/><div className="metric"><small>Direct cover gaps</small><strong>{uncovered.length}</strong><span>Slots without an eligible bench deputy</span></div><div className="metric"><small>Simultaneous bench cover</small><strong>{data.bench_cover.bench_only_matching_capacity}</strong><span>Existing matching capacity</span></div><div className="metric"><small>XI upgrades</small><strong>{improvements.length}</strong><span>Hypothetical, not transfer feasibility</span></div></div>
    <div className="grid"><Panel title="XI vacancies">{vacancies.length?vacancies.map(a=><button key={a.slot_id} className="priority" onClick={()=>go({page:"Tactics & XI",slot:a.slot_id})}><Tag tone="warn">Vacancy</Tag><b>{slotOf(data.slots,a.slot_id)}</b><span>{human(a.vacancy_reason)} →</span></button>):<p>No vacancies.</p>}</Panel>
    <Panel title="Depth / shared dependencies">{uncovered.map(a=><button className="priority" key={a.slot_id} onClick={()=>go({page:"Tactics & XI",slot:a.slot_id})}><Tag tone="warn">No direct cover</Tag><b>{slotOf(data.slots,a.slot_id)}</b><span>Inspect →</span></button>)}{shared.map(a=><button className="priority" key={a.slot_id} onClick={()=>go({page:"Tactics & XI",slot:a.slot_id})}><Tag>Shared cover</Tag><b>{slotOf(data.slots,a.slot_id)}</b><span>Inspect →</span></button>)}{!uncovered.length&&!shared.length&&<p>No gaps or shared dependencies.</p>}</Panel>
    <Panel title="Starter-loss consequences">{data.absences.map(a=><button className="priority" key={a.removed_player_id} onClick={()=>go({page:"Tactics & XI",slot:a.original_slot_id})}><Tag tone={a.filled_slot_loss?"warn":""}>{a.filled_slot_loss} slots lost</Tag><b>{nameOf(players,a.removed_player_id)}</b><span>Reassignment →</span></button>)}{!data.absences.length&&<p>No starter-loss scenarios.</p>}</Panel>
    <Panel title="Recruitment · engine order">{improvements.length?improvements.map(r=><button className="priority" key={r.player_id} onClick={()=>go({page:"Recruitment",slot:r.selected_slot_id??r.eligible_slot_ids[0]??"",player:r.player_id,impact:true})}><Tag tone="good">{human(r.classification)}</Tag><b>{nameOf(players,r.player_id)}</b><span>{slotOf(data.slots,r.selected_slot_id)} →</span></button>):<p>No demonstrated XI upgrades in the active target cohort.</p>}</Panel></div></>;
}
function Tactics({data,players,route,go}: {data:Overview;players:Map<string,Player>;route:Route;go:(r:Partial<Route>)=>void}) {
  const detail=useData<SlotData>("slot",route.slot?{generation:route.generation,slot:route.slot}:null);
  const selected=detail.data;
  return <><div className="intro"><p className="eyebrow">TACTICAL ANALYSIS</p><h1>Tactics & XI</h1><p>Select a position to inspect its assignment, eligibility and depth.</p></div><div className="two-pane"><Panel title="Selection shape"><TotalsView totals={data.summary.totals} label="Optimal XI · canonical"/><Pitch slots={data.slots} rows={data.baseline} players={players} selected={route.slot} onSlot={slot=>go({slot})}/><AssignmentTable slots={data.slots} rows={data.baseline} players={players} onSlot={slot=>go({slot})}/></Panel>
    <Panel title={selected?.slot.label??"Position detail"}>{!route.slot?<p>Select a pitch position or table row.</p>:detail.error?<p role="alert">{detail.error}</p>:!selected?<p role="status">Loading position…</p>:<>
      <p className="eyebrow">{selected.slot.selection_position.toUpperCase()} · {selected.slot.profile}</p><h3>{nameOf(players,selected.assignment.player_id)} <span className="accent">{num(selected.assignment.attribute_profile_score)}</span></h3><p>IP: {selected.slot.ip.position?.toUpperCase()??"Not configured"} {selected.slot.ip.role??""} · OOP: {selected.slot.oop.position?.toUpperCase()??"Not configured"} {selected.slot.oop.role??""}</p>
      <p>{selected.assignment.player_id?human(selected.assignment.availability):human(selected.assignment.vacancy_reason)} · {selected.assignment.warnings.map(human).join(" · ")}</p><EvidenceView evidence={selected.assignment.assessment}/>
      <p>Benchmark: {selected.assignment.league_benchmark? "Percentile "+num(selected.assignment.league_benchmark.percentile)+" · extracted "+selected.assignment.league_benchmark.extraction_game_date:human(selected.assignment.league_benchmark_reason)}</p>
      <h3>Eligible alternatives</h3><div className="table-wrap"><table><caption>Canonical eligible squad players</caption><thead><tr><th>Player</th><th>Quality</th><th>Current slot</th></tr></thead><tbody>{selected.coverage.eligible_players.map(p=><tr key={p.player_id}><td>{nameOf(players,p.player_id)}<small>{p.eligibility_position.toUpperCase()}</small></td><td>{num(p.attribute_profile_score)}</td><td>{slotOf(data.slots,p.baseline_slot)}</td></tr>)}</tbody></table></div>{!selected.coverage.eligible_players.length&&<p>No eligible players.</p>}
      <h3>Bench cover</h3><p>{selected.coverage.direct_cover_count} direct deputies · {human(selected.coverage.cover_type)}</p><p>Direct: {selected.coverage.direct_deputy_ids.map(id=>nameOf(players,id)).join(", ")||"None"}</p><p>Shared: {selected.coverage.shared_direct_deputy_ids.map(id=>nameOf(players,id)).join(", ")||"None"}</p>
      {selected.shared_cover.map(r=><p key={r.slot_ids.join(",")}>{r.slot_ids.map(id=>slotOf(data.slots,id)).join(" / ")}: {r.simultaneously_coverable_slots} slots simultaneously coverable by bench.</p>)}{selected.dependencies.map(r=><p key={r.player_id}>Without {nameOf(players,r.player_id)}: capacity {r.simultaneous_capacity_without_player}; uncovered {r.newly_uncovered_slot_ids.map(id=>slotOf(data.slots,id)).join(", ")||"none"}</p>)}
      <details><summary>Rejected squad players</summary>{selected.coverage.rejected_squad_players.map(p=><p key={p.player_id}>{nameOf(players,p.player_id)}: {p.reasons.map(human).join(", ")}</p>)}</details>
      <h3>Starter-loss simulation</h3>{selected.absence?<><p>{selected.absence.filled_slot_loss} filled slots lost · outfield loss {num(selected.absence.outfield_score_loss)} · GK loss {num(selected.absence.goalkeeper_score_loss)}</p><TotalsView totals={selected.absence.reoptimised} label="Without starter"/><Changes changes={selected.absence.changes} slots={data.slots} players={players}/></>:<p>Not applicable for a vacant slot.</p>}
      <button className="primary" onClick={()=>go({page:"Recruitment",slot:selected.slot.id,impact:false})}>Find recruitment candidates →</button></>}</Panel></div></>;
}
function SigningImpact({signing,data,players}: {signing:Signing;data:Overview;players:Map<string,Player>}) {
  return <><h3>Hypothetical completed signing · {nameOf(players,signing.player_id)}</h3><p className="notice">Availability assumed; interest, affordability, registration and fitness are not established. Attribute-quality scores are not predicted goals, wins or points.</p><Tag>{human(signing.classification)}</Tag>
    {signing.xi?<><p>{signing.xi.enters_xi?"Enters the XI at "+slotOf(data.slots,signing.xi.selected_slot_id):"Does not enter the optimal XI"}.</p><div className="grid"><TotalsView totals={signing.xi.baseline} label="Baseline"/><TotalsView totals={signing.xi.hypothetical} label="Hypothetical XI"/></div><p>Change in completeness: {signing.xi.impact.filled_slot_gain} · outfield gain {num(signing.xi.impact.outfield_score_gain)} · GK gain {num(signing.xi.impact.goalkeeper_score_gain)} {signing.xi.impact.tie_break_only&&"· tie-break only"}</p>
    <Changes changes={signing.xi.impact.changes} slots={data.slots} players={players}/><p>Displaced: {signing.xi.impact.newly_benched_player_ids.map(id=>nameOf(players,id)).join(", ")||"None"}.</p><p>Reassigned: {signing.xi.impact.moved_starters.map(r=>nameOf(players,r.player_id)+" "+slotOf(data.slots,r.from_slot_id)+" → "+slotOf(data.slots,r.to_slot_id)).join("; ")||"None"}.</p><p>Newly filled: {signing.xi.impact.newly_filled_slot_ids.map(id=>slotOf(data.slots,id)).join(", ")||"None"} · Remaining vacancies: {signing.xi.impact.vacant_slot_ids.map(id=>slotOf(data.slots,id)).join(", ")||"None"}</p><div className="grid"><section><h3>Baseline XI</h3><AssignmentTable slots={data.slots} rows={data.baseline} players={players}/></section><section><h3>Revised XI</h3><AssignmentTable slots={data.slots} rows={signing.xi.assignments} players={players}/></section></div></>:<p>No hypothetical signing scenario: already in squad.</p>}
    <h3>Squad-depth effects</h3><Tag>{human(signing.depth.status)}</Tag>{signing.depth.status==="evaluated"?<><p>Bench matching capacity: {signing.depth.bench_capacity_before} → {signing.depth.bench_capacity_after}</p>{signing.depth.coverage_changes?.map(r=><p key={r.slot_id}>{slotOf(data.slots,r.slot_id)}: {r.before_direct_ids.length} → {r.after_direct_ids.length} direct deputies</p>)}{signing.depth.same_original_starter_absences?.map(r=><p key={r.removed_player_id}>Without {nameOf(players,r.removed_player_id)}: filled-slot gain {r.impact.filled_slot_gain}; outfield {num(r.impact.outfield_score_gain)}; GK {num(r.impact.goalkeeper_score_gain)}</p>)}</>:<p>{signing.depth.status==="not_evaluated_limit"?"Detailed depth was not evaluated within the configured limit; no conclusion about depth improvement.":"Detailed depth not applicable to this candidate."}</p>}</>;
}
function Recruitment({data,players,route,go}: {data:Overview;players:Map<string,Player>;route:Route;go:(r:Partial<Route>)=>void}) {
  const [query,setQuery]=useState(""),[eligibleOnly,setEligibleOnly]=useState(false);
  const list=useData<{candidates:Candidate[]}>("candidates",route.slot?{generation:route.generation,slot:route.slot}:null);
  const impact=useData<Signing>("signing",route.player&&route.impact?{generation:route.generation,player:route.player}:null);
  const chosen=list.data?.candidates.find(c=>c.player_id===route.player);
  const names=useMemo(()=>Object.fromEntries(data.players.map(p=>[p.player_id,p.display_name])),[data.players]);
  const filtered=filterCandidates(list.data?.candidates??[],names,query,eligibleOnly);
  const baseline=data.baseline.find(a=>a.slot_id===route.slot);
  return <><div className="intro"><p className="eyebrow">RECRUITMENT INTELLIGENCE</p><h1>Recruitment targets</h1><p>Active F9 cohort · compare exact tactical eligibility and precomputed signing effects.</p></div>
    <Panel title="Tactical context"><label>Selection slot <select value={route.slot} onChange={e=>go({slot:e.target.value,impact:false})}><option value="">Choose a slot</option>{data.slots.map(s=><option key={s.id} value={s.id}>{s.label}</option>)}</select></label>{route.slot&&<button onClick={()=>go({page:"Tactics & XI"})}>Inspect tactical depth</button>}<p>Incumbent: {nameOf(players,baseline?.player_id)} · quality {num(baseline?.attribute_profile_score)}</p></Panel>
    <div className="two-pane"><Panel title="Candidate list · engine order"><div className="filters"><label>Search <input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Player name"/></label><label><input type="checkbox" checked={eligibleOnly} onChange={e=>setEligibleOnly(e.target.checked)}/> Hypothetically eligible only</label></div>{!route.slot?<p>Select a slot.</p>:list.error?<p role="alert">{list.error}</p>:!list.data?<p role="status">Loading candidates…</p>:<><p>{filtered.length} of {list.data.candidates.length} active targets</p><div className="table-wrap"><table><caption>Candidate comparison at selected slot</caption><thead><tr><th>Candidate</th><th>Quality</th><th>Eligibility</th><th>Impact</th></tr></thead><tbody>{filtered.map(c=><tr key={c.player_id} className={route.player===c.player_id?"active-row":""}><td><button className="text-button" onClick={()=>go({player:c.player_id,impact:false})}>{nameOf(players,c.player_id)}</button><small>{players.get(c.player_id)?.club} · {human(c.observed_availability)}</small></td><td>{num(c.assessment.attribute_profile_score)}</td><td>{c.classification==="already_in_squad"?"Already in squad":c.eligible?"Eligible if signed":c.reasons.map(human).join(", ")||"Not eligible"}</td><td>{human(c.classification)}<small>Depth: {human(c.depth_status)}</small></td></tr>)}</tbody></table></div>{!filtered.length&&<p>No matching targets.</p>}</>}</Panel>
    <Panel title="Candidate vs incumbent">{chosen?<><h3>{nameOf(players,chosen.player_id)}</h3><p>Observed availability: {human(chosen.observed_availability)} · cohorts {chosen.observed_cohorts.join(", ")}</p><p>Hypothetical eligibility: {chosen.eligible?"Eligible if signed":chosen.classification==="already_in_squad"?"Already in squad":chosen.reasons.map(human).join(", ")||"Not eligible"}.</p><div className="grid"><div className="metric"><small>Incumbent quality</small><strong>{num(baseline?.attribute_profile_score)}</strong></div><div className="metric"><small>Candidate quality</small><strong>{num(chosen.assessment.attribute_profile_score)}</strong></div></div><EvidenceView evidence={chosen.assessment}/><p>Scenario assignment: {slotOf(data.slots,chosen.selected_slot_id)}.</p><p>Depth: {human(chosen.depth_status)}</p><button className="primary" onClick={()=>go({impact:true})}>Inspect signing impact →</button></>:<p>Select a candidate to inspect evidence.</p>}</Panel></div>
    {route.impact&&route.player&&<Panel title="Before & after">{impact.error?<p role="alert">{impact.error}</p>:impact.data?<SigningImpact signing={impact.data} data={data} players={players}/>:<p role="status">Loading signing impact…</p>}</Panel>}</>;
}
function App() {
  const [route,setRoute]=useState(()=>routeFrom(location.hash));
  const latestRoute=useRef(route);latestRoute.current=route;
  const [current,setCurrent]=useState<Status|null>(null),[currentError,setCurrentError]=useState(""),[pinnedError,setPinnedError]=useState(""),[notice,setNotice]=useState(""),[switching,setSwitching]=useState(false);
  const overview=useData<Overview>("overview",route.generation?{generation:route.generation}:null);
  const [meta,setMeta]=useState<Provenance|null>(null);
  function go(changes:Partial<Route>,replace=false) {const next={...route,...changes};if(replace){history.replaceState(null,"",routeTo(next));setRoute(next);}else location.hash=routeTo(next);}
  useEffect(()=>{const update=()=>setRoute(routeFrom(location.hash));window.addEventListener("hashchange",update);return()=>window.removeEventListener("hashchange",update);},[]);
  useEffect(()=>{document.getElementById("main-content")?.focus();},[route.page]);
  useEffect(()=>{
    let cancelled=false;
    async function poll(){
      try {const value=await api<Status>("current");if(cancelled)return;setCurrent(value);setCurrentError("");if(!route.generation)go({generation:value.generation_id},true);}
      catch(e){if(!cancelled){setCurrentError((e as Error).message);setCurrent(null);}}
      if(route.generation)try {const value=await api<Status>("generation",{generation:route.generation});if(!cancelled){setMeta(value.provenance);setPinnedError("");}}
      catch(e){if(!cancelled)setPinnedError((e as Error).message);}
    }
    setPinnedError("");void poll();const interval=setInterval(poll,10000);return()=>{cancelled=true;clearInterval(interval);};
  },[route.generation]);
  const data=overview.data;
  const players=useMemo(()=>new Map(data?.players.map(p=>[p.player_id,p])??[]),[data]);
  async function accept(){
    if(!current)return;const gid=current.generation_id;setSwitching(true);
    try{const loaded=await api<Envelope<Overview>>("overview",{generation:gid});if(latestRoute.current.generation!==route.generation)return;const next=switchGeneration(latestRoute.current,gid,loaded.data.slots.map(s=>s.id),loaded.data.players.map(p=>p.player_id),loaded.data.recommendations.map(r=>r.player_id));setNotice(next.notice);go(next.route); }
    catch(e){setNotice("Could not switch: "+(e as Error).message);}finally{setSwitching(false);}
  }
  const context=meta?.generation_id===route.generation?meta:null;
  const available=data&&!pinnedError&&!overview.error;
  return <div className="shell"><a className="skip" href="#main-content" onClick={e=>{e.preventDefault();document.getElementById("main-content")?.focus();}}>Skip to content</a>
    <aside className="sidebar"><div className="brand"><span className="logo">T</span><div><b>TOUCHLINE</b><small>FOOTBALL INTELLIGENCE</small></div></div><div className="career"><small>ACTIVE CAREER</small><b>{context?.career??"Local career"}</b><span>Operational analysis</span></div><nav aria-label="Workspaces">{pages.map((page,i)=><button key={page} aria-current={route.page===page?"page":undefined} className={route.page===page?"nav-active":""} onClick={()=>go({page})}><span aria-hidden="true">{["◈","▦","▧","◎","▤","♙","⚙"][i]}</span>{page}</button>)}</nav><div className="sidefoot"><span className="dot"/> Local · read only<br/><small>Touchline M1b</small></div></aside>
    <div className="workspace"><header className="topbar"><div><small>GAME DATE</small><b>{context?.game_date??"—"}</b></div><div><small>FORMATION</small><b>{context?.configuration.formation.name??"—"}</b></div><div><small>MODEL</small><b>{context?.configuration.scoring_model.name??"—"}</b></div><div><small>GENERATION</small><b>{route.generation.slice(0,8)||"—"}</b></div><Tag tone={currentError?"warn":"good"}>{currentError?"Current unavailable":"Read-only"}</Tag></header>
      <main id="main-content" tabIndex={-1}>{currentError&&<div className="notice" role="status">Current generation unavailable: {currentError}. {route.generation?"Pinned view retained if still valid.":""}</div>}
      {current&&route.generation&&current.generation_id!==route.generation&&<div className="notice" role="status">A different valid generation is available. Your current decision is pinned. <button disabled={switching} onClick={accept}>{switching?"Validating…":"Switch generation"}</button></div>}
      {notice&&<div className="notice" role="status">{notice}</div>}
      {pinnedError||overview.error?<Panel title="Pinned generation unavailable"><p role="alert">{pinnedError||overview.error}. No replacement has been selected.</p></Panel>:!available?<Panel title="Waiting for validated generation"><p role="status">{currentError? "Publish a valid generation and retry.":"Loading local analysis…"}</p></Panel>:<>
        <div className="context-strip"><span>Generated {context?.generated_utc??"—"}</span><span>Eligibility: {context?.configuration.eligibility_policy.mode??"—"}</span><span>Benchmark: {context?.benchmark.status??"—"} {context?.benchmark.extraction_game_date??""}</span></div>
        {route.page==="Overview"?<OverviewPage data={data} players={players} go={go}/>:route.page==="Tactics & XI"?<Tactics data={data} players={players} route={route} go={go}/>:route.page==="Recruitment"?<Recruitment data={data} players={players} route={route} go={go}/>:route.page==="Data & Settings"?<Panel title="Generation evidence"><p>Operational fm27v2 only. Experimental role models are unavailable for real-save use.</p><pre>{JSON.stringify(context,null,2)}</pre>{Object.entries(data.limitations).map(([key,values])=><section key={key}><h3>{human(key)}</h3><ul>{values.map(v=><li key={v}>{v}</li>)}</ul></section>)}</Panel>:<Panel title={route.page}><p>This workspace is not implemented in M1b. Use existing legacy functionality separately.</p><button onClick={()=>go({page:"Overview"})}>Return to overview</button></Panel>}
      </>}</main></div></div>;
}

createRoot(document.getElementById("root")!).render(<App/>);
