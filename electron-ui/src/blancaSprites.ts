import type {BlancaAction} from './blancaState';

export type BlancaSpriteAction=BlancaAction|'walk-left'|'walk-right';
type Crop={rect:number[];anchor:number[];scale:number;clip:string;bounds:number[]};
type Atlas={size:number;anchor:number[];sprites:Record<BlancaSpriteAction,{file:string;frames:Crop[]}>};
const base=()=>new URL(`${import.meta.env.BASE_URL}mascots/blanca/playful/`,location.href);
let atlas:Promise<Atlas>|undefined;
const sources=new Map<string,Promise<HTMLImageElement>>(),frames=new Map<string,Promise<string>>();

/** Fixed 35-frame cache; retain at most two decoded source sheets. Original PNGs
 * stay untouched. Vector clips isolate full props across the uneven gutters. */
export function getBlancaSprite(action:BlancaSpriteAction,frame=0):Promise<string>{
 const index=action==='idle'||action.startsWith('walk-')?0:Math.max(0,Math.min(3,Math.floor(frame))),key=`${action}/${index}`,cached=frames.get(key);if(cached)return cached;
 const result=(async()=>{
  atlas??=fetch(new URL('sprites.json',base())).then(response=>{if(!response.ok)throw Error('无法读取角色帧配置');return response.json() as Promise<Atlas>;}).catch(error=>{atlas=undefined;throw error;});
  const config=await atlas,entry=config.sprites[action],crop=entry.frames[index];
  let loading=sources.get(entry.file);
  if(!loading){loading=new Promise<HTMLImageElement>((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(Error('无法读取角色图像'));image.src=new URL(entry.file,base()).href;});sources.set(entry.file,loading);if(sources.size>2)sources.delete(sources.keys().next().value!);}
  const image=await loading,canvas=document.createElement('canvas');canvas.width=canvas.height=config.size;
  const context=canvas.getContext('2d');if(!context)throw Error('无法绘制角色帧');
  context.translate(config.anchor[0],config.anchor[1]);context.scale(crop.scale,crop.scale);context.translate(-crop.anchor[0],-crop.anchor[1]);context.clip(new Path2D(crop.clip));
  const [left,top,right,bottom]=crop.rect;context.drawImage(image,left,top,right-left,bottom-top,left,top,right-left,bottom-top);
  return canvas.toDataURL('image/png');
 })();frames.set(key,result);void result.catch(()=>frames.delete(key));return result;
}
