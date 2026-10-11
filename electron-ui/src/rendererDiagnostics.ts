export function initializeRendererDiagnostics(){
 if(!window.apex)return;
 const send=(type:'error'|'action',message:string,stack?:string)=>void window.apex.reportDiagnostic({type,message:message.slice(0,2000),stack:stack?.slice(0,8000)}).catch(()=>{});
 window.addEventListener('error',event=>send('error',event.message,event.error instanceof Error?event.error.stack:undefined));
 window.addEventListener('unhandledrejection',event=>send('error',event.reason instanceof Error?event.reason.message:String(event.reason),event.reason instanceof Error?event.reason.stack:undefined));
 document.addEventListener('click',event=>{const node=event.target instanceof Element?event.target.closest<HTMLElement>('button,[role=option]'):null;if(!node)return;const label=node.getAttribute('role')==='option'?'选择选项':node.getAttribute('aria-label')||node.textContent||'按钮';send('action',label.trim().replace(/\s+/g,' ').slice(0,160));},true);
}
