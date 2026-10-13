import type {Result,Clip,HudName} from './shared';
export const playerNameKey=(name:string)=>name.normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu,'');
function glyphFamily(key:string){return /^[a-z0-9]{12,}$/.test(key)?key.replace(/[il]+/g,'i'):key;}
type Entry={name:string;hits:number;sources:Set<string>;spellings:Map<string,number>};
function aliases(clips:Clip[],getNames:(clip:Clip)=>string[]){
 const entries=new Map<string,Entry>();
 for(const clip of clips)for(const name of getNames(clip)){const key=playerNameKey(name);if(!key)continue;const entry=entries.get(key)||{name,hits:0,sources:new Set<string>(),spellings:new Map<string,number>()};entry.hits++;entry.sources.add(clip.source||clip.path);entry.spellings.set(name,(entry.spellings.get(name)||0)+1);entries.set(key,entry);}
 for(const entry of entries.values())entry.name=[...entry.spellings].sort((a,b)=>Number(/^\[[^\]]+\]/.test(b[0]))-Number(/^\[[^\]]+\]/.test(a[0]))||b[1]-a[1])[0][0];
 const families=new Map<string,string[]>();for(const key of entries.keys()){const family=glyphFamily(key);families.set(family,[...(families.get(family)||[]),key]);}
 const resolved=new Map<string,{name:string;alternatives:string[]}>();
 for(const keys of families.values()){
  keys.sort((a,b)=>entries.get(b)!.hits-entries.get(a)!.hits);
  const winner=entries.get(keys[0])!,others=keys.slice(1).reduce((n,key)=>n+entries.get(key)!.hits,0);
  const merge=keys.length===1||winner.hits>=4&&winner.sources.size>=2&&winner.hits>=others*2;
  for(const key of keys){const chosen=merge?winner:entries.get(key)!;resolved.set(key,{name:chosen.name,alternatives:merge?keys.map(key=>entries.get(key)!.name):[chosen.name]});}
 }
 return resolved;
}
/** Only observed spellings can become canonical; raw HUD evidence stays in metadata. */
export function normalizeLibraryNames(results:Result[]):Result[]{
 const clips=results.flatMap(result=>result.clips),accounts=aliases(clips,clip=>clip.accountName?[clip.accountName]:[]),teams=aliases(clips,clip=>(clip.teammates||[]).map(value=>value.name));
 return results.map(result=>({...result,clips:result.clips.map(clip=>{
  const account=clip.accountName?accounts.get(playerNameKey(clip.accountName)):undefined;
  const teammates=new Map<string,HudName>();for(const value of clip.teammates||[]){const name=teams.get(playerNameKey(value.name))?.name||value.name,key=playerNameKey(name);if(!teammates.has(key))teammates.set(key,{...value,name});}
  return {...clip,accountName:account?.name||clip.accountName,accountAliases:account?.alternatives,teammates:[...teammates.values()]};
 })}));
}
