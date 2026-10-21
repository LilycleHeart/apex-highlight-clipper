import './performance-settings.css';
import {useEffect,useState} from 'react';
import type {Options} from './shared';
import {performanceLimits,resolvePerformance,selectPerformancePreset,type PerformanceOptions,type PerformancePreset,type PerformanceRuntime} from './performanceOptions';
import StyledSelect from './StyledSelect';
import FluidChoices from './FluidChoices';
import InfoTip from './InfoTip';

const labels={low:'省资源',balanced:'均衡',high:'高性能',custom:'自定义'};
const descriptions={low:'单路处理并保留更多空闲资源。',balanced:'按处理器和可用内存选择适中的并行量。',high:'直接按硬件预算启动并行处理，再比较实际吞吐调整并发；资源紧张时收缩。',custom:'手动设置上限；实际运行仍受处理器、内存和显存安全预算约束。'};
const policyMessages:Record<string,string>={bounded_down_probe:'正在比较较低并发的实际处理速度',throughput_regression_rollback:'吞吐下降，已退回参考并发',vram_pressure_or_unknown:'显存余量不足或监控未知，已保守收缩',ram_telemetry_unavailable:'内存监控未知，已保守收缩'};
function ResourceNumber({name,label,unit,value,onChange}:{name:keyof typeof performanceLimits;label:string;unit:string;value:number;onChange:(value:number)=>void}){
 const [draft,setDraft]=useState(String(value)),[min,max]=performanceLimits[name];
 useEffect(()=>setDraft(String(value)),[value]);
 function commit(){const number=draft.trim()?Number(draft):value;const next=Number.isFinite(number)?Math.min(max,Math.max(min,Math.round(number))):value;setDraft(String(next));if(next!==value)onChange(next);}
 return <label><span className="setting-caption">{label}</span><div className="number-input"><input aria-label={label} type="number" min={min} max={max} step={1} value={draft} onChange={event=>setDraft(event.target.value)} onBlur={commit} onKeyDown={event=>{if(event.key==='Enter')event.currentTarget.blur();}}/><span>{unit}</span></div></label>;
}
export default function PerformanceSettings({options,onChange,dmlAvailable,cudaAvailable=false,logicalCores,busy,reduced,runtime}:{options:Options;onChange:(patch:PerformanceOptions)=>void;dmlAvailable:boolean;cudaAvailable?:boolean;logicalCores:number;busy:boolean;reduced:boolean;runtime?:PerformanceRuntime|null}){
 const unavailable=options.backend==='dml'&&!dmlAvailable||options.backend==='cuda'&&!cudaAvailable;
 const effective=resolvePerformance({...options,backend:unavailable?'cpu':options.backend},dmlAvailable,logicalCores,cudaAvailable),customMode=options.performance_preset==='custom';
 function custom(key:keyof PerformanceOptions,value:unknown){onChange({...options,performance_preset:'custom',[key]:value});}
 const gib=(value:number|null|undefined)=>value===null||value===undefined?'未知':`${(value/1024**3).toFixed(1)} GiB`;
 return <section className="performance-settings" aria-label="性能设置">
  <div className="performance-preset-field"><span className="setting-caption">性能档位<InfoTip label="性能档位说明" text="这里控制成片 HUD / 战果识别的准备队列和资源预算。高性能以实际吞吐为准，不保证CPU和GPU同时满载；解码线程保持保守，避免嵌套线程争用。"/></span>
   <FluidChoices className="performance-presets" label="性能档位" value={options.performance_preset} reduced={reduced} onChange={value=>onChange(selectPerformancePreset(options,value))} options={(Object.keys(labels) as PerformancePreset[]).map(value=>({value,label:labels[value],content:labels[value]}))}/>
  </div>
  <div className="algorithm-summary"><span>{busy?'下次任务生效':labels[options.performance_preset]}</span><b>{unavailable?'所选设备不可用':effective.backend==='cuda'?'CUDA':effective.backend==='dml'?'DirectML':'CPU'} · {customMode?`手动上限 ${options.cpu_workers} 路`:options.performance_preset==='high'?'自适应吞吐':'自动预算'}</b></div>
  <p className="performance-description">{descriptions[options.performance_preset]}</p>
  <label>识别设备<StyledSelect label="识别设备" value={options.backend} onChange={backend=>onChange({...options,backend})} options={[{value:'auto',label:'自动'},{value:'dml',label:'GPU · DirectML',disabled:!dmlAvailable},{value:'cuda',label:'GPU · CUDA',disabled:!cudaAvailable},{value:'cpu',label:'CPU'}]}/></label>
  {customMode&&<><div className="number-fields">{([{key:'cpu_workers',label:'同时处理片段上限',unit:'路'},{key:'decode_threads',label:'解码线程',unit:'/ 片段'},{key:'frame_cache_mb',label:'帧缓存上限',unit:'MiB / 片段'}] as const).map(field=><ResourceNumber key={field.key} name={field.key} label={field.label} unit={field.unit} value={options[field.key]} onChange={value=>custom(field.key,value)}/>)}</div>
   <label><span className="setting-caption">GPU 节奏<InfoTip label="GPU节奏说明" text="控制推理批量与间歇，不是GPU使用率目标。不会减少识别范围或降低阈值。"/></span><StyledSelect label="GPU 节奏" disabled={effective.backend==='cpu'} value={options.gpu_load} onChange={value=>custom('gpu_load',value)} options={[{value:'low',label:'低占用'},{value:'balanced',label:'均衡'},{value:'fast',label:'全速'}]}/></label></>}
  {runtime&&<div className="performance-runtime" role="status"><b>最近任务：并行目标 {runtime.target??runtime.budget?.initial_workers??'—'} 路 / 硬件预算 {runtime.budget?.max_workers??'—'} 路</b><span>{policyMessages[runtime.reason??'']??''}</span><span>启动时可用内存 {gib(runtime.resources?.ram_available)} · 显存 {gib(runtime.resources?.gpu_available)}</span>{runtime.budget?.reasons?.length?<span>部分资源信息不可用或余量不足，已保守限制；不会把未知当作空闲。</span>:null}</div>}
 </section>;
}
