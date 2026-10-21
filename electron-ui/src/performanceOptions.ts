export type PerformancePreset='low'|'balanced'|'high'|'custom';
export type RecognitionDevice='auto'|'cpu'|'dml'|'cuda';
export interface PerformanceOptions {performance_preset:PerformancePreset;backend:RecognitionDevice;gpu_load:'low'|'balanced'|'fast';cpu_workers:number;decode_threads:number;frame_cache_mb:number}
export const performancePresets={
 low:{gpu_load:'low',cpu_workers:1,decode_threads:1,frame_cache_mb:32},
 balanced:{gpu_load:'fast',cpu_workers:3,decode_threads:1,frame_cache_mb:64},
 high:{gpu_load:'fast',cpu_workers:3,decode_threads:1,frame_cache_mb:64},
} as const;
export const performanceDefaults:PerformanceOptions={performance_preset:'balanced',backend:'auto',...performancePresets.balanced};
export const performanceLimits={cpu_workers:[1,1024],decode_threads:[1,4],frame_cache_mb:[16,128]} as const;
export interface PerformanceRuntime {target?:number;reason?:string;budget?:{max_workers:number;initial_workers:number;reasons?:string[]};resources?:{logical:number;physical:number|null;ram_available:number|null;gpu_available:number|null;gpu_status:string}}
export function normalizePerformance(value:any={},strict=false):PerformanceOptions{
 const fail=(message:string)=>{if(strict)throw new Error(message);};
 let backend:RecognitionDevice=value.backend??'auto';
 if(!['auto','cpu','dml','cuda'].includes(backend)){fail('识别设备无效');backend='auto';}
 let preset:PerformancePreset=value.performance_preset??'balanced';
 if(!['low','balanced','high','custom'].includes(preset)){fail('性能档位无效');preset='balanced';}
 // Preserve legacy explicit throttle/worker choices as a custom configuration.
 if(value.performance_preset===undefined&&(['cpu_workers','decode_threads','frame_cache_mb'].some(key=>value[key]!==undefined)||value.gpu_load!==undefined&&value.gpu_load!=='fast'))preset='custom';
 const result:PerformanceOptions={...performanceDefaults,backend,performance_preset:preset};
 for(const [key,[min,max]] of Object.entries(performanceLimits) as [keyof typeof performanceLimits,readonly[number,number]][]){
  const raw=value[key];if(raw!==undefined){if(!Number.isInteger(raw)||raw<min||raw>max)fail(`${key} 参数超出范围`);else result[key]=raw;}
 }
 if(value.gpu_load!==undefined){if(!['low','balanced','fast'].includes(value.gpu_load))fail('GPU 节奏无效');else result.gpu_load=value.gpu_load;}
 return preset==='custom'?result:{...result,...performancePresets[preset]};
}
export function selectPerformancePreset(value:PerformanceOptions,preset:PerformancePreset):PerformanceOptions{
 return preset==='custom'?{...value,performance_preset:preset}:{...value,performance_preset:preset,...performancePresets[preset]};
}
export function resolvePerformance(value:PerformanceOptions,dmlAvailable:boolean,logicalCores:number,cudaAvailable=false){
 const settings=normalizePerformance(value,true);
 const backend=settings.backend==='auto'?(dmlAvailable?'dml':'cpu'):settings.backend;
 if(backend==='dml'&&!dmlAvailable)throw new Error('DirectML 运行环境不可用，请选择自动或 CPU');
 if(backend==='cuda'&&!cudaAvailable)throw new Error('CUDA 运行环境未通过实际推理检查，请选择自动或 CPU');
 const logical=Math.max(1,Number.isFinite(logicalCores)?logicalCores:1);
 // CPU has two ORT threads per worker; leave room for decode and template matching.
 return {...settings,backend,cpu_workers:Math.min(settings.cpu_workers,backend==='cpu'?Math.max(1,Math.floor(logical/2)):logical)};
}
