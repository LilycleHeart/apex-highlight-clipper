import type {Clip} from './shared';
import {recordingTime} from './clipStats';
export type LibrarySort='damage'|'kills'|'recent'|'recorded-newest'|'recorded-oldest';
export function compareObserved(a:number|null|undefined,b:number|null|undefined,descending=true){
 const knownA=typeof a==='number'&&Number.isFinite(a)&&a>=0,knownB=typeof b==='number'&&Number.isFinite(b)&&b>=0;
 if(!knownA||!knownB)return knownA?-1:knownB?1:0;
 return (a!-b!)*(descending?-1:1);
}
const timestamp=(value:string|null|undefined)=>{const number=value?Date.parse(value):NaN;return Number.isFinite(number)?number:null;};
export function compareLibraryClips(a:Clip,b:Clip,sort:LibrarySort,descending=true,aSource?:string,bSource?:string){
 if(sort==='damage'||sort==='kills')return compareObserved(a[sort],b[sort],descending);
 if(sort==='recent')return compareObserved(timestamp(a.exportedAt),timestamp(b.exportedAt));
 const first=timestamp(a.recordedAt||recordingTime(a.source||aSource||a.name)),second=timestamp(b.recordedAt||recordingTime(b.source||bSource||b.name));
 return compareObserved(first,second,sort==='recorded-newest')||(first!==null&&second!==null?(a.start-b.start)*(sort==='recorded-newest'?-1:1):0);
}
