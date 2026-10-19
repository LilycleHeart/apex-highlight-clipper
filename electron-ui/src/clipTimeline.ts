import type {Clip} from './shared';
import {libraryMetric,metricSortLabels,type LibrarySort} from './librarySort';
import {recordingTime} from './clipStats';

export function recordingDay(clip:Clip,source?:string){
 const value=clip.recordedAt||recordingTime(clip.source||source||clip.name),match=value?.match(/^(\d{4})-(\d{2})-(\d{2})/);if(!match)return'';
 const [year,month,day]=match.slice(1).map(Number),date=new Date(Date.UTC(year,month-1,day));return date.getUTCFullYear()===year&&date.getUTCMonth()===month-1&&date.getUTCDate()===day?match[0]:'';
}
export function dayLabel(day:string){if(!day)return'日期待确认';const [year,month,date]=day.split('-').map(Number);return`${year}年${month}月${date}日`;}
export function groupRecordingDays<T extends {clip:Clip;result?:{source:string}}>(items:T[],sort:LibrarySort='recent'){
 const groups=new Map<string,{day:string;items:T[]}>();for(const item of items){const day=recordingDay(item.clip,item.result?.source);let group=groups.get(day);if(!group){group={day,items:[]};groups.set(day,group);}group.items.push(item);}
 return [...groups.values()].sort((a,b)=>!a.day?(!b.day?0:1):!b.day?-1:sort==='recent'?0:a.day.localeCompare(b.day)*(sort==='recorded-oldest'?1:-1));
}

export interface LibraryGroup {key:string;label:string;day?:string;unknown:boolean}
export function libraryGroup(clip:Clip,source:string|undefined,sort:LibrarySort):LibraryGroup{
 if(!(sort in metricSortLabels)){const day=recordingDay(clip,source);return{key:'date:'+day,label:dayLabel(day),day,unknown:!day};}
 const name=metricSortLabels[sort as keyof typeof metricSortLabels],value=libraryMetric(clip,sort);
 if(typeof value!=='number'||!Number.isFinite(value)||value<0)return{key:sort+':unknown',label:name+' · 待确认',unknown:true};
 if(sort==='damage'||sort==='round-damage'){
  const step=sort==='damage'?100:500,start=Math.floor(value/step)*step;
  return{key:sort+':'+start,label:`${name} · ${start}–${start+step-1}`,unknown:false};
 }
 return{key:sort+':'+value,label:`${name} · ${value}`,unknown:false};
}
/** Keep the chosen sort's group order, with unconfirmed observations last. */
export function groupLibraryClips<T extends {clip:Clip;result?:{source:string}}>(items:T[],sort:LibrarySort){
 const groups=new Map<string,LibraryGroup&{items:T[]}>();for(const item of items){const descriptor=libraryGroup(item.clip,item.result?.source,sort);let group=groups.get(descriptor.key);if(!group){group={...descriptor,items:[]};groups.set(descriptor.key,group);}group.items.push(item);}
 return [...groups.values()].sort((a,b)=>Number(a.unknown)-Number(b.unknown));
}
