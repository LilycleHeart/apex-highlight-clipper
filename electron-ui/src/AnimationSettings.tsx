import {useEffect,useState} from 'react';
import {MIN_ANIMATION_FPS,MAX_ANIMATION_FPS,normalizeFrameRate,type AnimationPreferences} from './animationPreferences';

function FrameRate({label,value,onChange}:{label:string;value:number;onChange:(value:number)=>void}){
 const [draft,setDraft]=useState(String(value));
 useEffect(()=>setDraft(String(value)),[value]);
 const commit=()=>{const next=normalizeFrameRate(draft.trim()?Number(draft):value,value);setDraft(String(next));onChange(next);};
 return <label>{label}<div className="number-input"><input aria-label={label} type="number" min={MIN_ANIMATION_FPS} max={MAX_ANIMATION_FPS} step={1} value={draft} onChange={e=>{const raw=e.target.value;setDraft(raw);const next=Number(raw);if(raw&&Number.isInteger(next)&&next>=MIN_ANIMATION_FPS&&next<=MAX_ANIMATION_FPS)onChange(next);}} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/><span>FPS</span></div></label>;
}
export default function AnimationSettings({value,onChange}:{value:AnimationPreferences;onChange:(patch:Partial<AnimationPreferences>)=>void}){
 return <section className="animation-settings" aria-label="动画帧率"><h3>动画帧率</h3><div className="number-fields"><FrameRate label="人物帧率" value={value.mascotFps} onChange={mascotFps=>onChange({mascotFps})}/><FrameRate label="背景帧率" value={value.backgroundFps} onChange={backgroundFps=>onChange({backgroundFps})}/></div><p>1–240 FPS，数值越低越省资源。人物动作时长和背景移动速度保持不变。</p></section>;
}
