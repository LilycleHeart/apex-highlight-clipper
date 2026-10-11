export interface PlayerAudioPreferences {volume:number;muted:boolean;lastAudibleVolume:number}
export const defaultPlayerAudio:PlayerAudioPreferences={volume:1,muted:false,lastAudibleVolume:1};
export function normalizePlayerAudio(value:Partial<PlayerAudioPreferences>|null|undefined):PlayerAudioPreferences{
 const volume=typeof value?.volume==='number'&&Number.isFinite(value.volume)?Math.max(0,Math.min(1,value.volume)):1;
 const lastAudibleVolume=typeof value?.lastAudibleVolume==='number'&&Number.isFinite(value.lastAudibleVolume)&&value.lastAudibleVolume>0?Math.min(1,value.lastAudibleVolume):volume||1;
 return {volume,muted:value?.muted===true||volume===0,lastAudibleVolume};
}
