import type {Clip} from './shared';
import {playerNameKey} from './libraryNames';
import {recordingDay} from './clipTimeline';

export interface LibraryMetadataFilters {source?:string;date?:string;account?:string;teammate?:string;hero?:string;weapon?:string;rank?:string;rankDivision?:string}
export interface ClipDetailFilter {field:'source'|'date'|'account'|'teammate'|'hero'|'weapon'|'rank';value:string;label:string;division?:string}
export function detailFilterPatch(filter:ClipDetailFilter):LibraryMetadataFilters{
 return filter.field==='rank'?{rank:filter.value,rankDivision:filter.division||''}:{[filter.field]:filter.value};
}
export function dateFilterLabel(value:string){
 if(!value)return'全部日期';if(value==='unknown')return'日期未识别';
 const parts=value.split('-').map(Number);return`${parts[0]}年${parts.length>1?parts[1]+'月':''}${parts.length>2?parts[2]+'日':''}`;
}
export function matchesLibraryMetadata(clip:Clip,source:string,filters:LibraryMetadataFilters){
 if(filters.source&&source!==filters.source&&clip.source!==filters.source)return false;
 if(filters.date){
  const day=recordingDay(clip,source);
  if(filters.date==='unknown'?!!day:!/^\d{4}(?:-\d{2}(?:-\d{2})?)?$/.test(filters.date)||!day.startsWith(filters.date))return false;
 }
 if(filters.account&&![clip.accountName,...(clip.accountAliases||[])].some(name=>name&&playerNameKey(name)===playerNameKey(filters.account!)))return false;
 if(filters.teammate&&!clip.teammates?.some(player=>playerNameKey(player.name)===playerNameKey(filters.teammate!)))return false;
 if(filters.weapon&&!clip.weapons.includes(filters.weapon))return false;
 if(filters.hero&&(filters.hero==='unknown'?!!clip.hero:clip.hero?.id!==filters.hero))return false;
 if(filters.rank&&(filters.rank==='unknown'?!!clip.rank:clip.rank?.tier!==filters.rank))return false;
 if(filters.rankDivision&&clip.rank?.division!==filters.rankDivision)return false;
 return true;
}
