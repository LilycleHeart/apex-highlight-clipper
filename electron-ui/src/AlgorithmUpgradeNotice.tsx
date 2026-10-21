import {useState} from 'react';
import {RefreshCw,X} from 'lucide-react';
import InfoTip from './InfoTip';
import SettingsToggle from './SettingsToggle';
import HudRecoveryNotice from './HudRecoveryNotice';
import {algorithmNoticeKey,algorithmUpgradeSummary,selectAlgorithmUpgrade,type ClipAlgorithmStatus,type RecognitionRecoveryJob,type UpgradeSelection} from './algorithmStatus';
import useRecognitionNoticeAction from './useRecognitionNoticeAction';
import './recognition-recovery.css';

export interface AlgorithmUpgradeNoticeProps {
 clips:readonly ClipAlgorithmStatus[];unfinishedJob?:RecognitionRecoveryJob|null;
 /** Busy includes any recognition job, even one unrelated to this selection. */
 busy?:boolean;disabled?:boolean;
 onStart:(selection:UpgradeSelection[],options:{includeUnknown:boolean;mode:'upgrade'})=>void|Promise<void>;
 onResume:(id:string)=>void|Promise<void>;onCancel?:(id:string)=>void|Promise<void>;
 onDismissRecovery?:(id:string)=>void;
}
export default function AlgorithmUpgradeNotice({clips,unfinishedJob,busy=false,disabled=false,onStart,onResume,onCancel,onDismissRecovery}:AlgorithmUpgradeNoticeProps){
 const [includeUnknown,setIncludeUnknown]=useState(false),summary=algorithmUpgradeSummary(clips),selection=selectAlgorithmUpgrade(clips,includeUnknown);
 const [ignored,setIgnored]=useState<string[]>(()=>{try{const saved:unknown=JSON.parse(localStorage.getItem('ahc-ignored-algorithm-notices')||'[]');return Array.isArray(saved)?saved.filter((key):key is string=>typeof key==='string'):[];}catch{return[];}}),noticeKey=algorithmNoticeKey(clips),dismissed=ignored.includes(noticeKey);
 function ignore(){const next=[...ignored.filter(key=>key!==noticeKey),noticeKey].slice(-16);setIgnored(next);try{localStorage.setItem('ahc-ignored-algorithm-notices',JSON.stringify(next));}catch{/* Still dismiss for this session. */}}
 const labels=new Map(clips.flatMap(clip=>clip.fields.map(field=>[field.field,field.label||field.field] as const)));
 const selectedLabels=[...new Set(selection.flatMap(clip=>clip.fields))].map(field=>labels.get(field)||field);
 const action=useRecognitionNoticeAction(JSON.stringify([selection,unfinishedJob?.id,unfinishedJob?.status]));
 const unfinished=unfinishedJob&&unfinishedJob.status!=='completed'?unfinishedJob:null;
 // Unknown history requires a separate opt-in and is never called outdated.
 if(!summary.oldCount&&!summary.unknownCount&&!unfinished)return null;
 if(unfinished?.compatible||unfinished?.status==='running')return <HudRecoveryNotice job={unfinished} disabled={disabled||busy&&unfinished.status!=='running'} onResume={onResume} onCancel={onCancel} onDismiss={onDismissRecovery}/>;
 return <div className="recognition-notices">
  {unfinished&&<HudRecoveryNotice job={unfinished} disabled={disabled||busy} onResume={onResume} onCancel={onCancel} onDismiss={onDismissRecovery}/>}
  {!dismissed&&(summary.oldCount>0||summary.unknownCount>0)&&<section className="recognition-notice algorithm-upgrade-notice" aria-label="算法更新提示" aria-busy={action.pending}>
   <span className="recognition-notice-symbol"><RefreshCw size={19}/></span>
   <div className="recognition-notice-copy"><div className="recognition-notice-heading"><b>{summary.oldCount?`${summary.oldCount} 段可更新识别算法`:`${summary.unknownCount} 段未记录算法版本`}</b><InfoTip label="算法更新说明" text={`本次 ${selection.length} 段，字段：${selectedLabels.join('、')}。只重算版本过期${includeUnknown?'或版本未知':''}的字段，当前字段跳过；应用版本和性能设置变化不会触发此提示。${summary.unknownCount?'历史未记录版本的结果单独计数，可选择一起识别。':''}新结果成功保存前保留原结果。`}/></div>
    <span className="recognition-notice-detail">{selectedLabels.join('、')}{summary.unknownCount>0?` · 另有 ${summary.unknownCount} 段版本未知`:''}</span>
    {summary.unknownCount>0&&<SettingsToggle label="包含版本未知片段" checked={includeUnknown} disabled={disabled||busy||action.pending} onChange={setIncludeUnknown}/>}
   </div>
   <div className="recognition-notice-actions"><button type="button" className="secondary" disabled={disabled||busy||action.pending||!selection.length} onClick={()=>void action.run(()=>onStart(selection,{includeUnknown,mode:'upgrade'}))}>{action.pending?'正在创建任务…':'更新识别'}</button><button type="button" className="recognition-dismiss" disabled={action.pending} onClick={ignore} title="忽略本次算法更新提示，仍可手动重新识别"><X size={14}/>忽略</button>{includeUnknown&&<small>共 {selection.length} 段</small>}</div>
   {action.error&&<span className="recognition-notice-error" role="alert">{action.error}</span>}
  </section>}
 </div>;
}
