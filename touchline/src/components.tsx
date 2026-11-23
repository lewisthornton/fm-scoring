import React from "react";
import {pages, type Route} from "./state";
import type {Provenance} from "./types";

export function Panel({title,children}:React.PropsWithChildren<{title:string}>) {
  return <section className="panel"><h2>{title}</h2>{children}</section>;
}
export function Tag({children,tone=""}:React.PropsWithChildren<{tone?:string}>) {
  return <span className={"tag "+tone}>{children}</span>;
}
/** Only render a control where existing analysis supports navigation. */
export function PlayerAction({name,onInspect,selected}:{
  name:string;onInspect?:()=>void;selected?:boolean
}) {
  return onInspect?<button className="text-button player-action" aria-pressed={selected} onClick={onInspect}>{name}</button>:<span>{name}</span>;
}
export function StateMessage({kind,children,action}:React.PropsWithChildren<{
  kind:"loading"|"empty"|"error"|"unavailable";action?:React.ReactNode
}>) {
  const labels={loading:"Loading",empty:"No results",error:"Unable to load",unavailable:"Unavailable"};
  return <div className={"state-message state-"+kind} role={kind==="error"?"alert":kind==="loading"?"status":undefined}>
    <strong>{labels[kind]}</strong><p>{children}</p>{action}
  </div>;
}

const descriptions:Partial<Record<Route["page"],string>>={
  Analysis:"Planned · M2c", Staff:"Not yet available"
};
export function AppShell({route,context,currentError,onNavigate,children}:React.PropsWithChildren<{
  route:Route;context:Provenance|null;currentError:string;onNavigate:(page:Route["page"])=>void
}>) {
  return <div className="shell">
    <a className="skip" href="#main-content" onClick={e=>{e.preventDefault();document.getElementById("main-content")?.focus();}}>Skip to content</a>
    <aside className="sidebar">
      <div className="brand"><span className="logo" aria-hidden="true">T</span><div><b>Touchline</b><small>FOOTBALL INTELLIGENCE</small></div></div>
      <div className="career"><small>ACTIVE CAREER</small><b>{context?.career??"Local career"}</b><span>Operational analysis</span></div>
      <nav aria-label="Workspaces"><span className="nav-label">WORKSPACES</span>{pages.map((page,i)=><button key={page} aria-current={route.page===page?"page":undefined} className={route.page===page?"nav-active":""} onClick={()=>onNavigate(page)}><span aria-hidden="true">{["◈","▦","▧","◎","▤","♙","⚙"][i]}</span><span className="nav-text">{page}{descriptions[page]&&<small>{descriptions[page]}</small>}</span></button>)}</nav>
      <div className="sidefoot"><span className="dot"/> Local · read only<br/><small>Touchline / M2b.2</small></div>
    </aside>
    <div className="workspace">
      <header className="topbar" aria-label="Pinned analysis context">
        <div><small>CAREER</small><b>{context?.career??"—"}</b></div>
        <div><small>GAME DATE</small><b>{context?.game_date??"—"}</b></div>
        <div><small>FORMATION</small><b>{context?.configuration.formation.name??"—"}</b></div>
        <div><small>MODEL</small><b>{context?.configuration.scoring_model.name??"—"}</b></div>
        <div><small>PINNED GENERATION</small><b title={route.generation}>{route.generation.slice(0,8)||"—"}</b></div>
        <Tag tone={currentError?"warn":"good"}>{currentError?"Current unavailable":"Read-only"}</Tag>
      </header>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  </div>;
}
