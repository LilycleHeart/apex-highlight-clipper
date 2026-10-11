import {Download,ExternalLink,RefreshCw} from 'lucide-react';
import {useState} from 'react';
import type {UpdateInfo} from './shared';
import MotionDetails from './MotionDetails';

const labels={idle:'尚未检查',checking:'正在检查更新…',available:'发现新版本',up_to_date:'已是最新版',no_release:'暂无正式版本发布',error:'检查失败'};
const date=(value:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value));
export default function UpdateSettings({info,onChange,onError,busy=false}:{info:UpdateInfo;onChange:(info:UpdateInfo)=>void;onError:(message:string)=>void;busy?:boolean}){
 const[pending,setPending]=useState(false);
 const installing=info.installState==='downloading'||info.installState==='installing';
 async function install(){setPending(true);try{await window.apex.installUpdate();}catch(error){onError(String(error));}finally{setPending(false);}}
 async function toggle(enabled:boolean){setPending(true);try{onChange(await window.apex.setAutoCheck(enabled));}catch(error){onError(String(error));}finally{setPending(false);}}
 async function check(){try{onChange(await window.apex.checkUpdate());}catch(error){onError(String(error));}}
 return <section className="update-section" aria-label="版本更新">
  <div className="update-heading"><h3>版本更新</h3><span>当前 v{info.currentVersion}</span></div>
  <label className="toggle"><div><b>启动时检查更新</b><span>每 24 小时最多自动检查一次</span></div><input type="checkbox" aria-label="启动时检查更新" checked={info.autoCheck} disabled={pending} onChange={e=>void toggle(e.target.checked)}/></label>
  <div className={`update-status ${info.status}`} role="status"><b>{labels[info.status]}</b>{info.latestVersion&&<span>最新正式版 v{info.latestVersion}</span>}{info.message&&info.status==='error'&&<p>{info.message}</p>}{info.installState==='downloading'&&<><span>正在下载更新 {info.installProgress??0}%</span><progress aria-label="更新下载进度" max="100" value={info.installProgress??0}/></>}{info.installState==='installing'&&<p>即将关闭程序安装更新，完成后自动重新启动。</p>}{info.installState==='error'&&<p>{info.installMessage}</p>}{info.checkedAt&&<small>上次检查 {date(info.checkedAt)}</small>}</div>
  {info.status==='available'&&info.releaseNotes&&<MotionDetails className="update-notes" label="更新内容"><p>{info.releaseNotes}</p></MotionDetails>}
  <div className="update-actions"><button className="secondary" disabled={info.status==='checking'||installing||pending} onClick={()=>void check()}><RefreshCw size={15} className={info.status==='checking'?'update-spinning':''}/>{info.status==='checking'?'检查中…':'检查更新'}</button>{info.status==='available'&&<button className="secondary" disabled={busy||installing||pending} onClick={()=>void install()}><Download size={15}/>{installing?'正在更新…':'下载并安装'}</button>}<button className="text-button" disabled={installing} onClick={()=>void window.apex.openRelease().catch(error=>onError(String(error)))}>发布页<ExternalLink size={13}/></button></div>
 </section>;
}
