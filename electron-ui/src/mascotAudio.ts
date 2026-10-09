let player:HTMLAudioElement|null=null;
let version=0;
export async function playMascotToggle(enabled:boolean){
 const request=++version;
 if(!player){player=document.createElement('audio');player.id='mascot-toggle-audio';player.preload='auto';player.hidden=true;player.volume=.7;document.body.append(player);}
 player.pause();player.src=`${import.meta.env.BASE_URL}mascots/audio/${enabled?'restore':'disappear'}.wav`;player.currentTime=0;player.dataset.action=enabled?'restore':'disappear';try{await player.play();}catch(error){if(request!==version)return;throw error;}
}
