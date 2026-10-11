import type {Options} from './shared';
import {useState,useEffect,useId} from 'react';
import SettingsToggle from './SettingsToggle';
import MotionDisclosure from './MotionDisclosure';
import FluidChoices from './FluidChoices';
import InfoTip from './InfoTip';
export default function FilterSettings({options,update}:{options:Options;update:(key:keyof Options,value:unknown)=>void}){
 const reduced=document.documentElement.dataset.reduced==='true';
 const [expanded,setExpanded]=useState(false),detailsId=useId();
 useEffect(()=>{if(!options.filter_enabled)setExpanded(false);},[options.filter_enabled]);
 const fields=([{key:'min_kills',title:'最低击杀',max:60,unit:'杀'},{key:'min_duration',title:'最短片段',max:86400,unit:'秒'},{key:'min_damage',title:'最低伤害',max:20000,unit:'伤害'},{key:'min_assists',title:'最低助攻',max:99,unit:'助攻'}] as const);
 const field=(f:typeof fields[number])=>{const value=options[f.key],invalid=!Number.isInteger(value)||value<0||value>f.max;return <label key={f.key}>{f.title}<div className="number-input"><input aria-label={f.title} aria-invalid={invalid} type="number" min={0} max={f.max} step="1" disabled={!options.filter_enabled} value={Number.isFinite(value)?value:''} onChange={e=>update(f.key,e.target.valueAsNumber)} onBlur={()=>update(f.key,Math.min(f.max,Math.max(0,Math.trunc(Number.isFinite(value)?value:0))))}/><span>{f.unit}</span></div>{invalid&&<span className="field-error">请输入0–{f.max}的整数</span>}</label>;};
 return <section className="filter-settings" aria-label="处理保留阈值"><div className="heading-with-info"><h3>处理时保留</h3><InfoTip label="处理保留阈值说明" text="默认关闭。0表示不限，等于阈值也达标。时长按实际关键帧对齐区间计算。不能确定的未知值或下界留待核验；不会删除原录像或已有片段，续接沿用冻结参数。"/></div>
  <SettingsToggle label="按战绩过滤" description="开启后点击三角按钮配置保留条件。确定低于所设条件的片段不导出。" checked={options.filter_enabled} onChange={value=>{setExpanded(false);update('filter_enabled',value);}} disclosure={options.filter_enabled?{expanded,label:'过滤选项',controls:detailsId,onToggle:()=>setExpanded(value=>!value)}:undefined}/>
  <MotionDisclosure open={options.filter_enabled&&expanded} id={detailsId} className="home-options-reveal"><div className="home-options-details"><FluidChoices className="retention-mode" label="过滤保留条件" value={options.filter_mode} reduced={reduced} disabled={!options.filter_enabled} onChange={value=>update('filter_mode',value)} options={[{value:'all',label:'全部条件',content:'全部条件'},{value:'any',label:'任一条件',content:'任一条件'}]}/>
  <div className="number-fields">{fields.map(field)}</div></div></MotionDisclosure>
 </section>;
}
