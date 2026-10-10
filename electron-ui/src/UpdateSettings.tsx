import {ExternalLink,RefreshCw} from 'lucide-react';
import {useState} from 'react';
import type {UpdateInfo} from './shared';

const labels={idle:'尚未检查',checking:'正在检查更新…',available:'发现新版本',up_to_date:'已是最新版',no_release:'暂无正式版本发布',error:'检查失败'};
const date=(value:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value));
export default function UpdateSettings({info,onChange,onError}:{info:UpdateInfo;onChange:(info:UpdateInfo)=>void;onError:(message:string)=>void}){
 const[pending,setPending]=useState(false);
 async function toggle(enabled:boolean){setPending(true);try{onChange(await window.apex.setAutoCheck(enabled));}catch(error){onError(String(error));}finally{setPending(false);}}
 async function check(){try{onChange(await window.apex.checkUpdate());}catch(error){onError(String(error));}}
 return <section className="update-section" aria-label="版本更新">
  <div className="update-heading"><h3>版本更新</h3><span>当前 v{info.currentVersion}</span></div>
  <label className="toggle"><div><b>启动时检查更新</b><span>每 24 小时最多自动检查一次</span></div><input type="checkbox" aria-label="启动时检查更新" checked={info.autoCheck} disabled={pending} onChange={e=>void toggle(e.target.checked)}/></label>
  <div className={`update-status ${info.status}`} role="status"><b>{labels[info.status]}</b>{info.latestVersion&&<span>最新正式版 v{info.latestVersion}</span>}{info.message&&info.status==='error'&&<p>{info.message}</p>}{info.checkedAt&&<small>上次检查 {date(info.checkedAt)}</small>}</div>
  {info.status==='available'&&info.releaseNotes&&<details className="update-notes"><summary>更新内容</summary><p>{info.releaseNotes}</p></details>}
  <div className="update-actions"><button className="secondary" disabled={info.status==='checking'} onClick={()=>void check()}><RefreshCw size={15} className={info.status==='checking'?'update-spinning':''}/>{info.status==='checking'?'检查中…':'检查更新'}</button><button className="text-button" onClick={()=>void window.apex.openRelease().catch(error=>onError(String(error)))}>{info.status==='available'?'查看新版本':'打开发布页'}<ExternalLink size={13}/></button></div>
 </section>;
}
