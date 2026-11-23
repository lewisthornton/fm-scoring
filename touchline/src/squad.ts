import type {Player, Assignment, Slot} from "./types";

export type SquadRow = {player:Player; slot?:Slot};
export type SortKey = "name"|"club"|"cohort"|"position"|"availability"|"xi"|"observed";
export function squadRows(players:Player[], assignments:Assignment[], slots:Slot[]):SquadRow[] {
  const assigned=new Map(assignments.filter(a=>a.player_id!==null).map(a=>[a.player_id,a.slot_id]));
  const bySlot=new Map(slots.map(s=>[s.id,s]));
  return players.filter(p=>p.cohorts.includes("squad")).map(player=>({player,slot:bySlot.get(assigned.get(player.player_id)??"")}));
}
export function availability(p:Player) {return p.availability==="available"||p.availability==="unavailable"?p.availability:"unknown";}
export function squadSummary(rows:SquadRow[]) {
  const known=rows.filter(r=>availability(r.player)!=="unknown").length;
  return {total:rows.length,known,unknown:rows.length-known,assigned:rows.filter(r=>r.slot).length};
}
export function position(p:Player) {return p.keeper===true?"keeper":p.keeper===false?"outfield":"unknown";}
function value(r:SquadRow,key:SortKey):string {
  const p=r.player;
  switch(key){
    case "name":return p.display_name;
    case "club":return p.club??"";
    case "cohort":return [...p.cohorts].sort().join(", ");
    case "position":return position(p);
    case "availability":return availability(p);
    case "xi":return r.slot?.label??"";
    case "observed":return p.record_game_date??"";
  }
}
const compare=(a:string,b:string)=>a<b?-1:a>b?1:0;
export function filterSquad(rows:SquadRow[],query:string,availabilityFilter:string,positionFilter:string,key:SortKey,reverse:boolean) {
  return rows.filter(({player:p})=>p.display_name.toLowerCase().includes(query.trim().toLowerCase())&&(availabilityFilter==="all"||availability(p)===availabilityFilter)&&(positionFilter==="all"||position(p)===positionFilter)).sort((a,b)=>{
    const x=value(a,key).toLowerCase(),y=value(b,key).toLowerCase();
    return (!x!==!y?(!x?1:-1):compare(x,y)*(reverse?-1:1))||compare(a.player.player_id,b.player.player_id);
  });
}
