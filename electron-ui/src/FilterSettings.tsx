import type {Options} from './shared';
import {useState,useEffect,useId} from 'react';
import SettingsToggle from './SettingsToggle';
import MotionDisclosure from './MotionDisclosure';
import FluidChoices from './FluidChoices';
export default function FilterSettings({options,update,disabled=false}:{options:Options;update:(key:keyof Options,value:unknown)=>void;disabled?:boolean}){
 const reduced=document.documentElement.dataset.reduced==='true';
 const [expanded,setExpanded]=useState(false),detailsId=useId();
 useEffect(()=>{if(!options.filter_enabled)setExpanded(false);},[options.filter_enabled]);
 const fields=([{key:'min_kills',title:'最低击杀',max:60,unit:'杀'},{key:'min_duration',title:'最短片段',max:86400,unit:'秒'},{key:'min_damage',title:'最低伤害',max:20000,unit:'伤害'},{key:'min_assists',title:'最低助攻',max:99,unit:'助攻'}] as const);
 const field=(f:typeof fields[number])=>{const value=options[f.key],invalid=!Number.isInteger(value)||value<0||value>f.max;return <label key={f.key}>{f.title}<div className="number-input"><input aria-label={f.title} aria-invalid={invalid} type="number" min={0} max={f.max} step="1" disabled={!options.filter_enabled} value={Number.isFinite(value)?value:''} onChange={e=>update(f.key,e.target.valueAsNumber)} onBlur={()=>update(f.key,Math.min(f.max,Math.max(0,Math.trunc(Number.isFinite(value)?value:0))))}/><span>{f.unit}</span></div>{invalid&&<span className="field-error">请输入0–{f.max}的整数</span>}</label>;};
 return <section className="filter-settings" aria-label="处理保留阈值"><h3>处理时保留</h3>
  <SettingsToggle label="按战绩过滤" disabled={disabled} description={options.filter_enabled?"点击三角按钮配置保留条件，0表示不限，等于阈值也达标。确定低于条件的片段不导出；无法确认的数值留待核验，不删除已有片段。原录像回收由独立开关控制。":undefined} checked={options.filter_enabled} onChange={value=>{setExpanded(false);update('filter_enabled',value);}} disclosure={options.filter_enabled?{expanded,label:'过滤选项',controls:detailsId,onToggle:()=>setExpanded(value=>!value)}:undefined}/>
  <MotionDisclosure open={options.filter_enabled&&expanded} id={detailsId} className="home-options-reveal"><div className="home-options-details"><FluidChoices className="retention-mode" label="过滤保留条件" value={options.filter_mode} reduced={reduced} disabled={!options.filter_enabled} onChange={value=>update('filter_mode',value)} options={[{value:'all',label:'全部条件',content:'全部条件'},{value:'any',label:'任一条件',content:'任一条件'}]}/>
  <div className="number-fields">{fields.map(field)}</div></div></MotionDisclosure>
 </section>;
}
