export interface MediaGeometry {width:number;height:number;displayWidth:number;displayHeight:number;rotation:number;sampleAspectRatio:number}
function fraction(value:unknown){if(typeof value!=='string')return 1;const parts=value.split(/[:/]/).map(Number);const ratio=parts[0]/parts[1];return Number.isFinite(ratio)&&ratio>0?ratio:1;}
export function mediaGeometry(metadata:any):MediaGeometry|undefined{
 const stream=metadata?.streams?.find((s:any)=>s.codec_type==='video');if(!stream||!(stream.width>0&&stream.height>0))return;
 const width=Number(stream.width),height=Number(stream.height),sar=fraction(stream.sample_aspect_ratio);
 const raw=Number(stream.side_data_list?.find((d:any)=>Number.isFinite(Number(d.rotation)))?.rotation??stream.tags?.rotate??0),rotation=Number.isFinite(raw)?((raw%360)+360)%360:0;
 const radians=rotation*Math.PI/180,w=width*sar,h=height;
 const displayWidth=Math.abs(w*Math.cos(radians))+Math.abs(h*Math.sin(radians)),displayHeight=Math.abs(w*Math.sin(radians))+Math.abs(h*Math.cos(radians));
 return{width,height,displayWidth,displayHeight,rotation,sampleAspectRatio:sar};
}
export function displayRatio(media:MediaGeometry|undefined){if(!media)return;const r=media.displayWidth/media.displayHeight;return Number.isFinite(r)&&r>0?r:undefined;}
