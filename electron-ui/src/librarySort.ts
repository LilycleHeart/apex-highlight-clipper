import type {Clip} from './shared';
import {recordingTime} from './clipStats';
export type LibrarySort='damage'|'kills'|'assists'|'knockdowns'|'round-damage'|'round-kills'|'recent'|'recorded'|'recorded-newest'|'recorded-oldest';
export const metricSortLabels={damage:'片段伤害',kills:'片段击杀',assists:'片段助攻',knockdowns:'片段击倒','round-damage':'全局伤害','round-kills':'全局击杀'} as const;
export function libraryMetric(clip:Clip,sort:LibrarySort):number|null|undefined{
 if(sort==='round-damage')return clip.roundTotals?.damage;
 if(sort==='round-kills')return clip.roundTotals?.kills;
 if(sort==='damage'||sort==='kills'||sort==='assists'||sort==='knockdowns')return clip[sort];
 return null;
}
export function compareObserved(a:number|null|undefined,b:number|null|undefined,descending=true){
 const knownA=typeof a==='number'&&Number.isFinite(a)&&a>=0,knownB=typeof b==='number'&&Number.isFinite(b)&&b>=0;
 if(!knownA||!knownB)return knownA?-1:knownB?1:0;
 return (a!-b!)*(descending?-1:1);
}
const timestamp=(value:string|null|undefined)=>{const number=value?Date.parse(value):NaN;return Number.isFinite(number)?number:null;};
export function compareLibraryClips(a:Clip,b:Clip,sort:LibrarySort,descending=true,aSource?:string,bSource?:string){
 if(sort in metricSortLabels)return compareObserved(libraryMetric(a,sort),libraryMetric(b,sort),descending);
 if(sort==='recent')return compareObserved(timestamp(a.exportedAt),timestamp(b.exportedAt),descending);
 const first=timestamp(a.recordedAt||recordingTime(a.source||aSource||a.name)),second=timestamp(b.recordedAt||recordingTime(b.source||bSource||b.name));
 const newest=sort==='recorded'?descending:sort==='recorded-newest';
 return compareObserved(first,second,newest)||(first!==null&&second!==null?(a.start-b.start)*(newest?-1:1):0);
}
