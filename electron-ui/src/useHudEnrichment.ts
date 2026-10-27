import {useCallback,useEffect,useRef,useState} from 'react';
import type {HudEnrichmentField,HudEnrichmentMode,HudEnrichmentResult} from './shared';
import {hudFields} from './HudSettings';

export interface HudProgress {unit?:'step'|'field';completed:number;total:number;current:number;file:string;message:string;framesDone:number;framesTotal:number;fields:HudEnrichmentField[];backend:string;failures:number}
export interface HudJob {id:number;kind:'batch'|'single';files:string[];fields:HudEnrichmentField[];mode:HudEnrichmentMode;running:boolean;status:'running'|'completed'|'review'|'failed'|'stopped';progress:HudProgress;error:string}
export const emptyHudProgress:HudProgress={completed:0,total:0,current:0,file:'',message:'',framesDone:0,framesTotal:0,fields:[],backend:'',failures:0};
const errorText=(error:unknown)=>String(error).replace(/^Error:\s*/,'').replace(/^Error invoking remote method '[^']+':\s*(?:Error:\s*)?/,'');

/** The app owns this session; page unmounts must not end its event subscription. */
export default function useHudEnrichment(action:(files:string[],fields:HudEnrichmentField[],mode:HudEnrichmentMode)=>Promise<HudEnrichmentResult>){
 const [job,setJob]=useState<HudJob|null>(null),[panelOpen,setPanelOpen]=useState(false),[fields,setFields]=useState<HudEnrichmentField[]>([...hudFields.map(field=>field.key),'statistics' as HudEnrichmentField]),[scope,setScope]=useState<'visible'|'selected'>('visible'),[mode,setMode]=useState<HudEnrichmentMode>('missing');
 const active=useRef<number|null>(null),sequence=useRef(0),handler=useRef(action);handler.current=action;
 useEffect(()=>window.apex?.onEvent(event=>{
  const id=active.current;if(id===null||!event.type.startsWith('hud-info-'))return;
  setJob(previous=>{
   if(!previous||previous.id!==id||!previous.running)return previous;
   const progress={...previous.progress};
   if(event.type==='hud-info-checkpoint'){
    const counts=(event as unknown as {fields?:Record<string,number>}).fields;
    if(counts&&!Array.isArray(counts)&&['done','pending','inflight','failed'].every(key=>Number.isFinite(counts[key])&&counts[key]>=0)){
     progress.unit='field';progress.completed=counts.done;progress.total=counts.done+counts.pending+counts.inflight+counts.failed;
    }
    return{...previous,progress};
   }
   const total=progress.unit==='field'?progress.total:event.total??progress.total,index=Math.max(0,Math.min(total,event.index??0));progress.total=total;
   if(event.type==='hud-info-start')progress.message=event.message||progress.message;
   else if(event.type==='hud-info-progress'){if(progress.unit!=='field')progress.completed=Math.max(progress.completed,index);if(event.file)progress.file=event.file;}
   else if(event.type==='hud-info-activity'){
    const changedFile=event.file!==undefined&&event.file!==progress.file;progress.current=index||progress.current;
    if(event.file!==undefined)progress.file=event.file;
    if(event.message!==undefined)progress.message=event.message;
    if(event.fields!==undefined)progress.fields=event.fields;
    progress.framesDone=event.frames_done??(changedFile?0:progress.framesDone);progress.framesTotal=event.frames_total??(changedFile?0:progress.framesTotal);
    if(event.backend!==undefined)progress.backend=event.backend;
   }else if(event.type==='hud-info-error'){progress.failures=event.failures??progress.failures+1;progress.message=event.message||'部分片段需要重试';}
   return{...previous,progress};
  });
 }),[]);
 const run=useCallback(async(files:string[],requested:HudEnrichmentField[],requestedMode:HudEnrichmentMode,kind:HudJob['kind']='batch',execute?:()=>Promise<HudEnrichmentResult>)=>{
  if(active.current!==null)throw new Error('已有信息识别任务正在处理，请先等待完成或停止');
  if(!files.length||!requested.length)throw new Error('请选择片段及需要识别的信息');
  const id=++sequence.current;active.current=id;
  setJob({id,kind,files:[...files],fields:[...requested],mode:requestedMode,running:true,status:'running',progress:{...emptyHudProgress,total:files.length,fields:[...requested],message:requestedMode==='refresh'?'准备重新识别':'准备补充识别'},error:''});
  if(kind==='batch')setPanelOpen(true);
  try{
   const result=await(execute?execute():handler.current(files,requested,requestedMode));
   setJob(previous=>{
    if(!previous||previous.id!==id)return previous;
    const error=result.errors.length?`${result.errors.length} 组片段需要重试：${result.errors[0].message.split('\n')[0]}`:result.unconfirmed?`${result.unconfirmed} 个片段仍有未确认信息，请核验相关读数。`:'';
    return{...previous,running:false,status:error?'review':'completed',error,progress:{...previous.progress,completed:result.errors.length?previous.progress.completed:previous.progress.total,message:result.errors.length?'部分片段需要重试':result.unconfirmed?'识别完成，部分信息尚未确认':'识别完成'}};
   });return result;
  }catch(error){
   const text=errorText(error),stopped=/停止|中止/.test(text);
   setJob(previous=>previous?.id===id?{...previous,running:false,status:stopped?'stopped':'failed',error:text,progress:{...previous.progress,message:stopped?'识别已停止，已读取的信息保留':'识别未完成，可重试'}}:previous);throw error;
  }finally{if(active.current===id)active.current=null;}
 },[]);
 return{job,running:!!job?.running,progress:job?.progress||emptyHudProgress,panelOpen,setPanelOpen,fields,setFields,scope,setScope,mode,setMode,run};
}
export type HudEnrichmentSession=ReturnType<typeof useHudEnrichment>;
