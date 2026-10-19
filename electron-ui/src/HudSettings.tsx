import type {HudField,HudEnrichmentField,Options} from './shared';
import {useState,useEffect,useId} from 'react';
import SettingsToggle from './SettingsToggle';
import MotionDisclosure from './MotionDisclosure';
export const hudFields:{key:HudField;label:string}[]=[{key:'account',label:'本人账号'},{key:'weapons',label:'武器'},{key:'teammates',label:'队友'},{key:'hero',label:'英雄'},{key:'rank',label:'模式/段位'}];
export const enrichmentFields:{key:HudEnrichmentField;label:string}[]=[...hudFields,{key:'statistics',label:'战绩数字'},{key:'opponents',label:'敌人姓名'},{key:'event_weapons',label:'战果相关武器'}];
export function HudFieldPicker<T extends string=HudField>({value,onChange,disabled=false,items=hudFields as unknown as {key:T;label:string}[]}:{value:T[];onChange:(value:T[])=>void;disabled?:boolean;items?:{key:T;label:string}[]}){
 return <div className="hud-field-picker">{items.map(field=><label key={field.key}><input type="checkbox" disabled={disabled} checked={value.includes(field.key)} onChange={e=>onChange(e.target.checked?[...value,field.key]:value.filter(key=>key!==field.key))}/>{field.label}</label>)}</div>;
}
export default function HudSettings({options,update,disabled=false}:{options:Options;update:(key:keyof Options,value:unknown)=>void;disabled?:boolean}){
 const [expanded,setExpanded]=useState(false),detailsId=useId();
 useEffect(()=>{if(!options.hud_info_enabled)setExpanded(false);},[options.hud_info_enabled]);
 return <section className="hud-settings" aria-label="可选HUD信息"><h3>HUD 信息补充</h3><SettingsToggle label="整理时补充 HUD 信息" disabled={disabled} description={options.hud_info_enabled?"交战识别与导出独立完成；点击三角按钮选择信息，也可之后在片段库补齐。":undefined} checked={options.hud_info_enabled} onChange={value=>{setExpanded(false);update('hud_info_enabled',value);}} disclosure={options.hud_info_enabled?{expanded,label:'HUD 选项',controls:detailsId,onToggle:()=>setExpanded(value=>!value)}:undefined}/><MotionDisclosure open={options.hud_info_enabled&&expanded} id={detailsId} className="home-options-reveal"><div className="home-options-details"><HudFieldPicker value={options.hud_info_fields} onChange={fields=>update('hud_info_fields',fields)}/></div></MotionDisclosure></section>;
}
