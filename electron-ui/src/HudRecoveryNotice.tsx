import InfoTip from './InfoTip';
import {LoaderCircle,Pause,Play,Square,X} from 'lucide-react';
import {recoveryProgress,type RecognitionRecoveryJob} from './algorithmStatus';
import useRecognitionNoticeAction from './useRecognitionNoticeAction';
import './recognition-recovery.css';

export interface HudRecoveryNoticeProps {
 job:RecognitionRecoveryJob;disabled?:boolean;
 onResume:(id:string)=>void|Promise<void>;onCancel?:(id:string)=>void|Promise<void>;
 onDismiss?:(id:string)=>void;
}
export default function HudRecoveryNotice({job,disabled=false,onResume,onCancel,onDismiss}:HudRecoveryNoticeProps){
 const action=useRecognitionNoticeAction(`${job.id}:${job.status}:${job.updatedAt||''}`),progress=recoveryProgress(job);
 if(job.status==='completed')return null;
 const running=job.status==='running';
 return <section className="recognition-notice recognition-recovery" aria-label="重识别任务" aria-busy={running||action.pending}>
  <span className={'recognition-notice-symbol '+(running?'is-running':'')}>{running?<LoaderCircle size={19}/>:<Pause size={18}/>}</span>
  <div className="recognition-notice-copy"><div className="recognition-notice-heading"><b>{running?'正在重新识别':'重识别进度已保留'}</b><InfoTip label="重识别进度说明" text={job.compatible?'每项是一个片段中的一个识别字段，仅已成功保存的项计入完成。继续任务会复用兼容检查点，从未完成的字段接着识别；新结果提交前保留原结果。':job.invalidReason||'素材或算法已变化，原检查点不能继续。已有识别结果仍保留，可发起新一轮识别。'}/></div>
   <span className="recognition-notice-detail">已保存 {progress.completed} / {progress.total} 个字段{running&&progress.inFlight>0?` · 处理中 ${progress.inFlight} 项`:''}{!job.compatible?' · 检查点已失效':''}</span>
   <div className="recognition-progress-line"><progress aria-label="已保存的重识别进度" max={Math.max(1,progress.total)} value={progress.completed}/><span>{progress.total?Math.floor(progress.completed/progress.total*100):0}%</span></div>
  </div>
  <div className="recognition-notice-actions">{running?onCancel&&<button type="button" className="secondary" disabled={disabled||action.pending} onClick={()=>void action.run(()=>onCancel(job.id))}><Square size={13}/>暂停识别</button>:<><button type="button" className="secondary" disabled={disabled||action.pending||!job.compatible} onClick={()=>void action.run(()=>onResume(job.id))}><Play size={13}/>{action.pending?'正在继续…':'继续识别'}</button>{onDismiss&&<button type="button" className="recognition-dismiss" disabled={action.pending} onClick={()=>onDismiss(job.id)} title="隐藏提示，已保存任务仍可展开查看"><X size={14}/>忽略</button>}</>}</div>
  {action.error&&<span className="recognition-notice-error" role="alert">{action.error}</span>}
 </section>;
}
