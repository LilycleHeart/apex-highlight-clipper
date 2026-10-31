import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {FolderPlus,LoaderCircle,Star,X} from 'lucide-react';
import type {ClipCollection} from './shared';

export default function CollectionMenu({files,onClose,onDone}:{files:string[];onClose:()=>void;onDone:(message:string)=>void}){
 const [collections,setCollections]=useState<ClipCollection[]>([]),[name,setName]=useState(''),[sync,setSync]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const panel=useRef<HTMLDivElement>(null);
 useEffect(()=>{void window.apex.listCollections().then(setCollections).catch(()=>setCollections([]));},[]);
 useEffect(()=>{
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose();};
  const outside=(event:PointerEvent)=>{if(panel.current&&!panel.current.contains(event.target as Node))onClose();};
  document.addEventListener('keydown',escape);document.addEventListener('pointerdown',outside,true);
  return()=>{document.removeEventListener('keydown',escape);document.removeEventListener('pointerdown',outside,true);};
 },[onClose]);
 async function add(target:string){
  if(!target.trim()){setError('请填写收藏夹名称');return;}
  setBusy(true);setError('');
  try{
   const result=await window.apex.addToCollection(files,target.trim(),sync);
   window.dispatchEvent(new Event('apex-collections-changed'));
   onDone(result.moved?`已收藏到「${result.collection.name}」，并移动 ${result.moved} 个文件`:`已收藏到「${result.collection.name}」`);
   onClose();
  }catch(reason){setError(String(reason).replace(/^Error:\s*/,''));}
  finally{setBusy(false);}
 }
 return createPortal(<div className="collection-menu-backdrop"><section ref={panel} className="collection-menu" role="dialog" aria-label="添加到收藏夹">
  <header><b>收藏片段</b><button type="button" className="icon-button" aria-label="关闭收藏面板" onClick={onClose}><X size={16}/></button></header>
  <p className="collection-menu-count">共 {files.length} 个片段</p>
  {collections.length>0&&<div className="collection-menu-list">{collections.map(item=><button type="button" key={item.id} className="collection-menu-item" disabled={busy} onClick={()=>void add(item.name)}><Star size={14}/><span>{item.name}</span><small>{item.files.length} 段</small></button>)}</div>}
  <label className="collection-menu-field"><span>新建收藏夹</span><input value={name} placeholder="例如：精彩击杀" disabled={busy} onChange={event=>setName(event.target.value)} onKeyDown={event=>{if(event.key==='Enter')void add(name);}}/></label>
  <label className="collection-menu-check"><input type="checkbox" checked={sync} disabled={busy} onChange={event=>setSync(event.target.checked)}/><span>同时在文件夹里新建同名分类文件夹并移入</span></label>
  {error&&<p className="collection-menu-error" role="alert">{error}</p>}
  <footer><button type="button" className="secondary" disabled={busy} onClick={onClose}>取消</button><button type="button" className="primary" disabled={busy||!name.trim()} onClick={()=>void add(name)}>{busy?<><LoaderCircle size={14} className="loading-spinner"/>正在收藏…</>:<><FolderPlus size={14}/>新建并收藏</>}</button></footer>
 </section></div>,document.fullscreenElement||document.body);
}
