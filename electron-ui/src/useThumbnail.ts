import {useEffect,useRef,useState,type RefObject} from 'react';
export default function useThumbnail(file:string,initial:string|undefined,cover:RefObject<HTMLDivElement|null>){
 const [url,setUrl]=useState(initial),[error,setError]=useState('');const retry=useRef<()=>void>(()=>{});
 useEffect(()=>{let live=true,requested=false;setUrl(initial);setError('');const element=cover.current;if(!element)return;
  const load=()=>{if(requested)return;requested=true;void window.apex.thumbnailURL(file).then(value=>{if(live)setUrl(value);}).catch(error=>{if(live)setError(error instanceof Error?error.message:'封面暂不可用，可直接播放片段');});};retry.current=()=>{setUrl(undefined);load();};
  const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){if(!initial)load();observer.disconnect();}},{root:element.closest('.library-scroll'),rootMargin:'180px'});observer.observe(element);return()=>{live=false;observer.disconnect();};
 },[file,initial,cover]);
 return {url,error,retry:()=>retry.current()};
}
