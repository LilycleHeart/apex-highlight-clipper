import type {FileItem,Result,Stage,State,WorkerEvent,FilterSummary} from './shared';
export interface Model {state:State;stage:Stage;files:FileItem[];results:Result[];progress:number|null;message:string;logs:string[];index:number;total:number;task:string;directory:string;preview:{url:string;time:number;stage:Stage}|null;cached:boolean;legacyRule:boolean;rule:string;filterSummary:FilterSummary|null;samplingWarning:string}
export const initial:Model={state:'empty',stage:'idle',files:[],results:[],progress:null,message:'',logs:[],index:0,total:0,task:'',directory:'',preview:null,cached:false,legacyRule:false,rule:'',filterSummary:null,samplingWarning:''};
export function eventReducer(model:Model,e:WorkerEvent):Model{
 const log=e.message?[...model.logs,e.message].slice(-180):model.logs;let m={...model,logs:log};
 if(e.type==='run')return{...m,state:'running',task:e.task_path||model.task,directory:e.directory||'',message:e.message||'',legacyRule:!!e.legacy_rule,rule:e.result_filter_rule||'',samplingWarning:e.sampling_warning||''};
 if(e.type==='file')return{...m,state:'running',index:e.index||0,total:e.total||0,progress:0,preview:null,cached:false,files:m.files.map(f=>f.path===e.source?{...f,status:'running'}:f)};
 if(e.type==='stage')return{...m,stage:e.stage&&Object.hasOwn(stageCopy,e.stage)?e.stage:'unknown',message:e.message||'',progress:e.progress??null,cached:!!e.cached};
 if(e.type==='progress'||e.type==='log')return{...m,progress:Math.max(m.progress??0,e.progress??m.progress??0)};
 if(e.type==='preview'&&e.imageUrl){const active=m.files.find(f=>f.status==='running');if(active&&e.source&&active.path.toLowerCase()!==e.source.toLowerCase())return m;return{...m,preview:{url:e.imageUrl,time:e.timestamp_seconds||0,stage:e.stage&&Object.hasOwn(stageCopy,e.stage)?e.stage:m.stage}};}
 if(e.type==='result'&&e.result)return{...m,results:[...m.results.filter(r=>r.source!==e.result!.source),e.result],files:m.files.map(f=>f.path===e.source?{...f,status:'complete'}:f),progress:100};
 if(e.type==='error')return{...m,stage:'error',message:e.message||'处理失败',files:m.files.map(f=>f.path===e.source||f.status==='running'?{...f,status:'error',error:e.message}:f),results:e.source?[...m.results.filter(r=>r.source!==e.source),{source:e.source,status:'error',outputs:[],directory:'',clips:[],error:e.message}]:m.results};
 if(e.type==='done'){const allFailed=!!e.failures&&m.total>0&&e.failures>=m.total;return{...m,state:allFailed?'failed':e.failures?'completed_with_errors':'completed',stage:e.failures?'error':'completed',progress:100,filterSummary:e.result_filter_version==='own-center-result-v4'?e.result_filter_summary||null:null,message:allFailed?'这批录像处理失败，请查看具体原因':e.failures?`${e.failures} 个录像处理失败，其余结果已保存`:'本批交战片段已整理完成'};}
 if(e.type==='stopped')return{...m,state:'stopped',stage:'stopped',message:e.message||'进度已保存',files:m.files.map(f=>f.status==='running'?{...f,status:'stopped'}:f)};
 if(e.type==='fatal')return{...m,state:'failed',stage:'error',message:e.message||'任务启动失败'};
 if(e.type==='close-request')return{...m,state:'stopping',stage:'stopping',message:e.message||''};
 if(e.type==='metadata')return{...model,files:model.files.map(f=>f.path===e.source?{...f,...e} as unknown as FileItem:f)};
 return m;
}
export const isBusy=(state:State)=>['starting','running','stopping'].includes(state);
export function appendUnique(existing:FileItem[],incoming:FileItem[]){const keys=new Set(existing.map(f=>f.path.toLowerCase()));return incoming.filter(f=>{const p=f.path.toLowerCase();if(keys.has(p))return false;keys.add(p);return true;});}
export function clock(value:number){const s=Math.max(0,Math.floor(value));return `${Math.floor(s/60)}分${String(s%60).padStart(2,'0')}秒`;}
export function resultSummary(model:Model){if(model.legacyRule)return null;if(model.filterSummary)return model.filterSummary;const values=model.results.filter(r=>r.result_filter_version==='own-center-result-v4'&&r.result_filter_summary).map(r=>r.result_filter_summary!);if(!values.length)return null;return values.reduce((a,v)=>({kept:a.kept+v.kept,rejected:a.rejected+v.rejected,review:a.review+v.review,rule:v.rule}),{kept:0,rejected:0,review:0,rule:''});}
export const stageCopy:Record<Stage,[string,string]>={
 combat_outcomes:['确认有效交战','检查本人的击倒、助攻与消灭提示。'],unknown:['正在处理当前阶段','正在完成这一步。'],idle:['让交战留下来','把录像交给我，空档留在过去。'],importing:['收到，正在收拢录像','文件已加入队列，可以继续添加。'],probe:['查看录像的小卡片','正在确认时长、画面与音轨信息。'],
 coarse:['寻找交战的蛛丝马迹','沿着关键帧，观察计数与玩家状态变化。'],bisect:['追踪交战边界','收拢伤害变化的区间，寻找起止位置。'],fine:['看清这段交战','正在读取弹药、伤害与击杀的细节。'],audit:['把前后计分对一遍','核对累计伤害与击杀，检查是否需要补查。'],fallback:['再完整检查一遍','不确定区域正在完整采样，已有断点继续保留。'],smart:['寻找交战片段','智能识别正在分析录像。'],sample:['收集检查画面','画面分块提交，已完成的部分可以续接。'],numeric:['读取交战计数','正在识别弹药、伤害与击杀。'],pipeline:['边采样，边检查','只读取已提交画面，队列保持有界。'],cache:['翻开已有的记录','复用完成的识别，画面保持在已有检查点。'],
 lifecycle:['倒地之后，还要再看一眼','确认倒地与恢复，不在交战中途收尾。'],weapons:['认出真正开过火的枪','正在核对实际使用的枪械名称。'],outcomes:['关注队友的最后一段交战','确认友方延续和结束画面。'],export:['把交战分别装好','视频与音轨原样复制，每场交战独立输出。'],verify:['逐项检查成片','正在校验视频及全部音轨的压缩数据。'],stopping:['收好工具，保存书签','等待后台提交断点，保存完成后可续接。'],stopped:['休息一下，进度记住了','继续时沿用原队列和剪辑参数。'],completed:['交战片段，整理好了','每一场都有自己的视频。'],error:['这里需要看一下','查看下面的具体提示，其他已完成结果仍然保留。']};
