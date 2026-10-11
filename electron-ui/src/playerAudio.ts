import {normalizePlayerAudio,type PlayerAudioPreferences} from './audioPreferences';
let current=normalizePlayerAudio(undefined);
export function initializePlayerAudio(value:PlayerAudioPreferences|undefined){current=normalizePlayerAudio(value);}
export function readPlayerAudio(){return {...current};}
export function applyPlayerAudio(video:HTMLVideoElement){
 video.volume=current.volume;video.defaultMuted=current.muted;video.muted=current.muted;
}
export function rememberPlayerAudio(value:PlayerAudioPreferences){
 // Update immediately so a following clip cannot race an asynchronous disk write.
 current=normalizePlayerAudio(value);
 return window.apex.savePlayerAudio(current);
}
