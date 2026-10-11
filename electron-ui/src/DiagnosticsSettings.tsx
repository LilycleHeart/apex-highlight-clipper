import {useEffect,useState} from 'react';
import {Archive,FolderOpen,ExternalLink} from 'lucide-react';

export default function DiagnosticsSettings({onError}:{onError:(message:string)=>void}){
 const [info,setInfo]=useState<{directory:string;available:boolean;message?:string}|null>(null),[pending,setPending]=useState(false),[saved,setSaved]=useState('');
 useEffect(()=>{let live=true;void window.apex.diagnosticsInfo().then(value=>{if(live)setInfo(value);},error=>{if(live)onError(String(error));});return()=>{live=false;};},[]);
 async function exportBundle(){setPending(true);try{const file=await window.apex.exportDiagnostics();if(file)setSaved(file.split(/[\\/]/).pop()||file);}catch(error){onError(String(error).replace(/^Error: /,''));}finally{setPending(false);}}
 return <section className="diagnostics-section" aria-label="诊断与反馈"><h3>诊断与反馈</h3><p>日志自动保存，单文件最多 1 MB，保留最近 7 天，总容量约 20 MB。</p><div className="diagnostics-directory"><span>日志位置</span><code title={info?.directory}>{info?.directory||'正在读取…'}</code></div>{info?.message&&<p className="field-error" role="alert">日志暂时无法保存：{info.message}</p>}<div className="diagnostics-actions"><button className="secondary" disabled={pending||!info?.available} onClick={()=>void exportBundle()}><Archive size={15}/>{pending?'正在导出…':'导出诊断包'}</button><button className="secondary" disabled={!info?.available} onClick={()=>void window.apex.openDiagnostics().catch(error=>onError(String(error)))}><FolderOpen size={15}/>打开日志目录</button><button className="text-button" onClick={()=>void window.apex.openFeedback().catch(error=>onError(String(error)))}>提交问题<ExternalLink size={13}/></button></div><p>导出 ZIP 后，在反馈页附上 ZIP 并描述复现步骤。诊断包隐藏常见本机路径，不包含录像、封面或完整任务文件。</p>{saved&&<p className="diagnostics-saved" role="status">已保存：{saved}</p>}</section>;
}
