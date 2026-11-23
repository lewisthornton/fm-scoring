export const pages = ["Overview", "Squad", "Tactics & XI", "Recruitment", "Analysis", "Staff", "Data & Settings"] as const;
export type Page = typeof pages[number] | "Player Profile";
export type Route = { page: Page; generation: string; slot: string; player: string; impact: boolean };
export function routeFrom(hash: string): Route {
  const q = new URLSearchParams(hash.replace(/^#/, ""));
  const page = q.get("page") as Page;
  return {page: page==="Player Profile" || pages.some(p=>p===page) ? page : "Overview", generation: q.get("generation") || "",
    slot: q.get("slot") || "", player: q.get("player") || "", impact: q.get("impact") === "1"};
}
export function routeTo(route: Route) {
  return "#" + new URLSearchParams({page: route.page, generation: route.generation, slot: route.slot, player: route.player, impact: route.impact ? "1" : "0"}).toString();
}
export function switchGeneration(route: Route, generation: string, slots: string[], players: string[], candidates: string[], squad=players, assignedPlayerSlot?:string|null) {
  const assignmentLost=assignedPlayerSlot===null;
  const selectedSlot=assignedPlayerSlot??route.slot;
  const slotLost = !!selectedSlot && !slots.includes(selectedSlot);
  const playerLost = !!route.player && (assignmentLost||!(route.page==="Squad"?squad:players).includes(route.player));
  const candidateLost = !!route.player && !candidates.includes(route.player) && route.page === "Recruitment";
  return {route: {...route, generation, slot: slotLost||assignmentLost ? "" : selectedSlot, player: playerLost || candidateLost ? "" : route.player,
    impact: !slotLost && !playerLost && !candidateLost && route.impact, page: slotLost && route.page!=="Squad" && route.page!=="Player Profile" ? "Tactics & XI" as const : route.page},
    notice: [slotLost && (route.page==="Squad"||route.page==="Player Profile"?"Selected slot no longer exists; selection cleared.":"Selected slot no longer exists; returned to tactical overview."), (playerLost || candidateLost) && "Selected player is no longer in this context."].filter(Boolean).join(" ")};
}
export function filterCandidates<T extends {player_id:string; eligible:boolean}>(rows:T[], names:Record<string,string>, query:string, eligibleOnly:boolean) {
  return rows.filter(row => (!eligibleOnly || row.eligible) && (names[row.player_id] || "").toLowerCase().includes(query.toLowerCase()));
}
