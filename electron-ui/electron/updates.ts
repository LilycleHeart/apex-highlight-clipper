import type {UpdateInfo} from '../src/shared';

export const REPOSITORY='LilycleHeart/apex-highlight-clipper';
export const RELEASES_API=`https://api.github.com/repos/${REPOSITORY}/releases?per_page=20`;
export const RELEASES_PAGE=`https://github.com/${REPOSITORY}/releases`;
export const AUTO_CHECK_INTERVAL=24*60*60*1000;
export function versionParts(value:unknown):bigint[]|null{
 if(typeof value!=='string'||value.length>80)return null;
 const match=value.trim().match(/^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+[\da-z.-]+)?$/i);
 return match?match.slice(1,4).map(v=>BigInt(v)):null;
}
export function compareVersions(a:string,b:string){const x=versionParts(a),y=versionParts(b);if(!x||!y)throw new Error('版本格式无效');for(let i=0;i<3;i++){if(x[i]>y[i])return 1;if(x[i]<y[i])return-1;}return 0;}
export function releasePage(tag?:string){return tag&&versionParts(tag)?`${RELEASES_PAGE}/tag/${encodeURIComponent(tag)}`:RELEASES_PAGE;}
export function releaseResult(data:unknown,currentVersion:string):Omit<UpdateInfo,'autoCheck'>{
 if(!Array.isArray(data))throw new Error('更新服务返回了无效数据');
 const releases=data.filter(r=>r&&typeof r==='object'&&r.draft===false&&r.prerelease===false&&versionParts(r.tag_name));
 releases.sort((a,b)=>compareVersions(b.tag_name,a.tag_name));
 if(!releases.length)return{status:'no_release',currentVersion,message:'暂无正式版本发布'};
 const release=releases[0];
 return{status:compareVersions(release.tag_name,currentVersion)>0?'available':'up_to_date',currentVersion,
  latestVersion:release.tag_name.replace(/^v/i,''),releaseTag:release.tag_name,
  releaseName:typeof release.name==='string'?release.name.slice(0,160):release.tag_name,
  releaseNotes:typeof release.body==='string'?release.body.slice(0,4000):'',
  publishedAt:typeof release.published_at==='string'&&!Number.isNaN(Date.parse(release.published_at))?release.published_at:undefined};
}
export function shouldAutoCheck(info:UpdateInfo,now=Date.now()){
 const checked=info.checkedAt?Date.parse(info.checkedAt):NaN;
 return info.autoCheck&&(!Number.isFinite(checked)||checked>now||now-checked>=AUTO_CHECK_INTERVAL);
}
export function restoreUpdateInfo(cache:any,currentVersion:string,autoCheck:boolean):UpdateInfo{
 const idle:UpdateInfo={status:'idle',currentVersion,autoCheck};
 if(!cache||cache.currentVersion!==currentVersion||!['available','up_to_date','no_release','error'].includes(cache.status)||typeof cache.checkedAt!=='string'||!Number.isFinite(Date.parse(cache.checkedAt)))return idle;
 if(['available','up_to_date'].includes(cache.status)&&(!versionParts(cache.latestVersion)||!versionParts(cache.releaseTag)))return idle;
 const str=(value:unknown,max:number)=>typeof value==='string'?value.slice(0,max):undefined;
 return{status:cache.status,currentVersion,autoCheck,checkedAt:cache.checkedAt,
  latestVersion:str(cache.latestVersion,80),releaseTag:str(cache.releaseTag,80),releaseName:str(cache.releaseName,160),releaseNotes:str(cache.releaseNotes,4000),
  message:str(cache.message,240),publishedAt:typeof cache.publishedAt==='string'&&Number.isFinite(Date.parse(cache.publishedAt))?cache.publishedAt:undefined};
}
/** 主进程统一请求；重复点击与启动检查共享一次网络请求。 */
export class UpdateChecker{
 private pending:Promise<UpdateInfo>|null=null;
 constructor(private version:string,private fetcher:(url:string,init:RequestInit)=>Promise<Response>,private read:()=>UpdateInfo,private publish:(info:UpdateInfo)=>void){}
 check(){
  if(this.pending)return this.pending;
  const run=async()=>{
   this.publish({...this.read(),status:'checking',message:undefined});
   let info:Omit<UpdateInfo,'autoCheck'>;
   try{
    const response=await this.fetcher(RELEASES_API,{headers:{Accept:'application/vnd.github+json','User-Agent':`Apex-Highlight-Clipper/${this.version}`},signal:AbortSignal.timeout(15000)});
    if(response.status===403||response.status===429)throw new Error('更新服务暂时限制请求，请稍后重试');
    if(!response.ok)throw new Error('更新服务暂时不可用，请稍后重试');
    const raw=await response.text();if(raw.length>2*1024*1024)throw new Error('更新信息过大，请稍后重试');
    info=releaseResult(JSON.parse(raw),this.version);
   }catch(error){const known=error instanceof Error?error.message:'';info={status:'error',currentVersion:this.version,message:['更新服务暂时限制请求，请稍后重试','更新服务暂时不可用，请稍后重试','更新信息过大，请稍后重试'].includes(known)?known:'无法连接更新服务，请检查网络后重试'};}
   const result={...info,autoCheck:this.read().autoCheck,checkedAt:new Date().toISOString()};
   this.publish(result);return result;
  };
  this.pending=run().finally(()=>{this.pending=null;});return this.pending;
 }
}
