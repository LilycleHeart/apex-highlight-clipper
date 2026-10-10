import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {Readable} from 'node:stream';
import {videoExtensions} from './protocol';

/** 仅为已授权的结果片段发放不含文件路径的本地播放地址。 */
export class VideoRegistry{
 private files=new Map<string,string>();private keys=new Map<string,string>();
 constructor(private allowed:(file:string)=>boolean){}
 async url(input:unknown){
  if(typeof input!=='string'||!this.allowed(path.resolve(input)))throw new Error('请先选择本任务已导出的片段');
  const real=await fs.realpath(input);const stat=await fs.stat(real);
  if(!stat.isFile()||!videoExtensions.has(path.extname(real).toLowerCase())||!stat.size)throw new Error('视频不存在或无法读取');
  let key=this.keys.get(real);
  if(!key){key=randomUUID();this.files.set(key,real);this.keys.set(real,key);if(this.files.size>64){const old=this.files.keys().next().value!;this.keys.delete(this.files.get(old)!);this.files.delete(old);}}
  return `apex-media://video/${key}`;
 }
 async respond(request:Request){
  try{
   const url=new URL(request.url);const key=url.pathname.slice(1);
   if(url.hostname!=='video'||!/^[-a-f0-9]{36}$/.test(key)||!this.files.has(key))return new Response('Not found',{status:404});
   if(!['GET','HEAD'].includes(request.method))return new Response('Method not allowed',{status:405});
   const real=this.files.get(key)!;const stat=await fs.stat(real);if(!stat.isFile()||!stat.size)return new Response('Not found',{status:404});
   const range=byteRange(request.headers.get('range'),stat.size);
   if(!range)return new Response(null,{status:416,headers:{'Content-Range':`bytes */${stat.size}`,'Accept-Ranges':'bytes'}});
   const type=({'.mp4':'video/mp4','.m4v':'video/mp4','.mov':'video/quicktime','.mkv':'video/x-matroska','.ts':'video/mp2t'} as Record<string,string>)[path.extname(real).toLowerCase()];
   const headers:Record<string,string>={'Content-Type':type,'Accept-Ranges':'bytes','Content-Length':String(range.end-range.start+1),'Cache-Control':'no-store'};
   if(range.partial)headers['Content-Range']=`bytes ${range.start}-${range.end}/${stat.size}`;
   if(request.method==='HEAD')return new Response(null,{status:range.partial?206:200,headers});
   const handle=await fs.open(real,'r');const stream=handle.createReadStream({start:range.start,end:range.end,highWaterMark:64*1024,autoClose:true});
   const abort=()=>stream.destroy();request.signal.addEventListener('abort',abort,{once:true});stream.once('close',()=>request.signal.removeEventListener('abort',abort));
   if(request.signal.aborted)stream.destroy();
   return new Response(Readable.toWeb(stream) as ReadableStream<Uint8Array>,{status:range.partial?206:200,headers});
  }catch{return new Response('Video unavailable',{status:404});}
 }
}

export function byteRange(value:string|null,size:number):{start:number;end:number;partial:boolean}|null{
 if(!Number.isSafeInteger(size)||size<=0)return null;
 if(!value)return{start:0,end:size-1,partial:false};
 const match=value.match(/^bytes=(\d*)-(\d*)$/);if(!match||!match[1]&&!match[2])return null;
 if(!match[1]){const suffix=Number(match[2]);return Number.isSafeInteger(suffix)&&suffix>0?{start:Math.max(0,size-suffix),end:size-1,partial:true}:null;}
 const start=Number(match[1]),end=match[2]?Number(match[2]):size-1;
 return Number.isSafeInteger(start)&&Number.isSafeInteger(end)&&start>=0&&start<size&&end>=start?{start,end:Math.min(size-1,end),partial:true}:null;
}
