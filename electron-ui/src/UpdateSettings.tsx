import {Download,ExternalLink,RefreshCw} from 'lucide-react';
import {useState} from 'react';
import type {UpdateInfo} from './shared';
import {GITHUB_MIRRORS} from './shared';
import MotionDetails from './MotionDetails';
import StyledSelect from './StyledSelect';

const labels={idle:'尚未检查',checking:'正在检查更新…',available:'发现新版本',up_to_date:'已是最新版',no_release:'暂无正式版本发布',error:'检查失败'};
const date=(value:string)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value));
const mirrorOptions=[...GITHUB_MIRRORS.map(item=>({value:item.value,label:item.label})),{value:'custom',label:'自定义…'}];
export default function UpdateSettings({info,onChange,onError,busy=false}:{info:UpdateInfo;onChange:(info:UpdateInfo)=>void;onError:(message:string)=>void;busy?:boolean}){
 const[pending,setPending]=useState(false);
 const current=info.mirror||'';
 const builtin=GITHUB_MIRRORS.some(item=>item.value===current&&item.value);
 const[customMode,setCustomMode]=useState(!!current&&!builtin);
 const[custom,setCustom]=useState(builtin?'':current);
 const[testing,setTesting]=useState(false);
 const[testResult,setTestResult]=useState<{ok:boolean;ms:number;message:string}|null>(null);
 const installing=info.installState==='downloading'||info.installState==='installing';
 async function install(){setPending(true);try{await window.apex.installUpdate();}catch(error){onError(String(error));}finally{setPending(false);}}
 async function toggle(enabled:boolean){setPending(true);try{onChange(await window.apex.setAutoCheck(enabled));}catch(error){onError(String(error));}finally{setPending(false);}}
 async function check(){try{onChange(await window.apex.checkUpdate());}catch(error){onError(String(error));}}
 async function saveMirror(value:string){
  setPending(true);setTestResult(null);
  try{onChange(await window.apex.setUpdateMirror(value));}
  catch(error){onError(String(error));}
  finally{setPending(false);}
 }
 async function pick(value:string){
  if(value==='custom'){setCustomMode(true);return;}
  setCustomMode(false);
  await saveMirror(value);
 }
 async function applyCustom(){
  const value=custom.trim();
  if(!value){onError('请填写加速地址，例如 https://gh-proxy.com/');return;}
  await saveMirror(value);
  setCustomMode(false);
 }
 async function test(){
  const value=customMode?custom.trim():current;
  setTesting(true);setTestResult(null);
  try{setTestResult(await window.apex.testUpdateMirror(value));}
  catch(error){onError(String(error));}
  finally{setTesting(false);}
 }
 const selectValue=customMode?'custom':current;
 return <section className="update-section" aria-label="版本更新">
  <div className="update-heading"><h3>版本更新</h3><span>当前 v{info.currentVersion}</span></div>
  <label className="toggle"><div><b>启动时检查更新</b><span>每 24 小时最多自动检查一次</span></div><input type="checkbox" aria-label="启动时检查更新" checked={info.autoCheck} disabled={pending} onChange={e=>void toggle(e.target.checked)}/></label>
  <div className="update-mirror" aria-label="GitHub 加速">
   <div className="update-mirror-head"><b>GitHub 加速</b><span>检查更新和下载安装包时使用；国内网络访问 GitHub 困难时可以选一个镜像</span></div>
   <StyledSelect label="下载加速" value={selectValue} disabled={pending||installing} onChange={value=>void pick(value)} options={mirrorOptions}/>
   {customMode&&<div className="update-mirror-custom">
    <input aria-label="自定义加速地址" placeholder="https://gh-proxy.com/" value={custom} disabled={pending||installing} onChange={event=>setCustom(event.target.value)} onKeyDown={event=>{if(event.key==='Enter')event.preventDefault();}}/>
    <button type="button" className="secondary" disabled={pending||installing} onClick={()=>void applyCustom()}>保存</button>
   </div>}
   <div className="update-mirror-actions">
    <button type="button" className="text-button" disabled={testing||pending||installing} onClick={()=>void test()}>{testing?'正在测试…':'测试加速连通性'}</button>
    {testResult&&<span className={testResult.ok?'update-mirror-ok':'update-mirror-fail'} role="status">{testResult.ok?`连接正常 · ${testResult.ms}ms`:`不可用：${testResult.message}`}</span>}
   </div>
   <small>镜像只改变下载路径，安装包仍会用发布页公布的 SHA-256 校验。检查更新失败时也可以先用系统代理再试。</small>
  </div>
  <div className={`update-status ${info.status}`} role="status"><b>{labels[info.status]}</b>{info.latestVersion&&<span>最新正式版 v{info.latestVersion}</span>}{info.message&&info.status==='error'&&<p>{info.message}</p>}{info.installState==='downloading'&&<><span>正在下载更新 {info.installProgress??0}%</span><progress aria-label="更新下载进度" max="100" value={info.installProgress??0}/></>}{info.installState==='installing'&&<p>即将关闭程序安装更新，完成后自动重新启动。</p>}{info.installState==='error'&&<p>{info.installMessage}</p>}{info.checkedAt&&<small>上次检查 {date(info.checkedAt)}</small>}</div>
  {info.status==='available'&&info.releaseNotes&&<MotionDetails className="update-notes" label="更新内容"><p>{info.releaseNotes}</p></MotionDetails>}
  <div className="update-actions"><button className="secondary" disabled={info.status==='checking'||installing||pending} onClick={()=>void check()}><RefreshCw size={15} className={info.status==='checking'?'update-spinning':''}/>{info.status==='checking'?'检查中…':'检查更新'}</button>{info.status==='available'&&<button className="secondary" disabled={busy||installing||pending} onClick={()=>void install()}><Download size={15}/>{installing?'正在更新…':'下载并安装'}</button>}<button className="text-button" disabled={installing} onClick={()=>void window.apex.openRelease().catch(error=>onError(String(error)))}>发布页<ExternalLink size={13}/></button></div>
 </section>;
}
