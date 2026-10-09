import type {Stage} from './shared';
type Drop={x:number;y:number;r:number;alpha:number};
export interface Form {x:number;y:number;r:number;triangle:number;square:number;angle:number;ring:number;dent:number;neck:number;drops:Drop[]}
const tau=Math.PI*2;const clamp=(v:number,a=0,b=1)=>Math.max(a,Math.min(b,v));const ease=(v:number)=>{v=clamp(v);return v*v*(3-2*v);};
// 数值积分得到的等面积半径表；横轴为两体中心距 0..66（步长2）。
// 每项的 smooth-union 实际轮廓约为 π×32²，避免融合时线性缩半造成体量塌缩。
const fusionRadii=[32.0078,31.3047,30.6172,30.0234,29.4141,28.8516,28.1797,27.6641,27.0234,26.5547,26.0078,25.4922,25.0234,24.5391,24.1797,23.7109,23.3516,23.0078,22.7422,22.4609,22.2109,22.0859,22.0078,21.9297,21.8359,21.8672,21.9297,22.0078,22.2109,22.4453,22.5547,22.6172,22.6328,22.6328];
function fusionRadius(distance:number){const index=clamp(distance/2,0,33),a=Math.floor(index),b=Math.min(33,a+1);return fusionRadii[a]+(fusionRadii[b]-fusionRadii[a])*(index-a);}
const base=():Form=>({x:100,y:80,r:32,triangle:0,square:0,angle:0,ring:0,dent:0,neck:22,drops:Array.from({length:3},()=>({x:100,y:80,r:0,alpha:1}))});
function at(f:Form,i:number,distance:number,angle:number,radius=9){f.drops[i]={x:f.x+distance*Math.cos(angle),y:f.y+distance*Math.sin(angle),r:radius,alpha:1};}
export function stageForm(stage:Stage,t:number):Form{
 const f=base();
 switch(stage){
  case 'idle':case 'stopped':case 'cache':f.r*=1+(stage==='stopped'?.0075:stage==='cache'?.006:.015)*Math.sin(t*tau/4.8);break;
  case 'importing':case 'probe':{
   const p=(t%2.8)/2.8;const distance=p<.68?57-39*ease(p/.68):18+39*ease((p-.68)/.32);at(f,0,distance,0,10);f.r+=.7*Math.sin(p*Math.PI);break;}
  case 'coarse':case 'smart':case 'sample':case 'pipeline':case 'fallback':{
   for(let i=0;i<3;i++){const p=((t/4.2-i/3)%1+1)%1;const travel=Math.sin(Math.PI*p)**2;at(f,i,24+30*travel,-Math.PI/2+i*tau/3,9);}break;}
  case 'bisect':{
   const p=(t%3.6)/3.6;let distance:number,merge:number;
   if(p<.46){const q=p/.46;const step=Math.floor(q*3),local=q*3-step;distance=33-15*(step+ease(local))/3;merge=0;}
   else if(p<.7){const q=ease((p-.46)/.24);distance=18*(1-q);merge=q;}
   else if(p<.8){distance=0;merge=1;}
   else{const q=ease((p-.8)/.2);distance=33*q;merge=1-q;}
   f.r=0;f.neck=22*Math.min(1,distance*2/36);const radius=fusionRadius(distance*2);at(f,0,distance,Math.PI,radius);at(f,1,distance,0,radius);break;}
  case 'fine':case 'numeric':f.triangle=1;f.r=41+.45*Math.sin(t*tau/3.8);f.angle=12*Math.PI/180*Math.sin(t*tau/3.8);break;
  case 'lifecycle':case 'outcomes':{f.neck=42;const p=(t%4)/4;at(f,0,34+13*Math.sin(Math.PI*p)**2,0,11);break;}
  case 'weapons':{f.square=1;f.r=30.5;for(let i=0;i<2;i++){const p=((t/3.6+i*.5)%1+1)%1;at(f,i,20+35*Math.sin(Math.PI*p)**2,i*Math.PI,9);}break;}
  case 'export':{
   f.x=83;f.r=28;for(let i=0;i<2;i++){const p=((t-i*1.9)%3.8+3.8)%3.8;const q=ease(p/2.5);f.drops[i]={x:105+q*(40+i*21),y:80,r:9,alpha:p<.3?ease(p/.3):p>2.8?1-ease((p-2.8)/1):1};}break;}
  case 'audit':case 'verify':{
   const p=(t%4.2)/4.2;const form=p<.72?ease(p/.72):1-ease((p-.72)/.28);f.ring=19*form;f.r=Math.sqrt(32*32+f.ring*f.ring);
   for(let i=0;i<3;i++){const q=((p-i*.18)%1+1)%1;at(f,i,29+27*(1-ease(q/.36)),-Math.PI/2+i*tau/3,8);}break;}
  case 'stopping':break;
  case 'completed':{if(t>.55&&t<.9)f.r+=.65*Math.sin((t-.55)/.35*Math.PI);break;}
  case 'error':f.dent=7+.15*Math.sin(t*tau/5);f.r+=.1*Math.sin(t*tau/5);break;
 }
 return f;
}
export function staticForm(stage:Stage):Form{const f=stageForm(stage,stage==='verify'||stage==='audit'?2.6:stage==='export'?2.6:1.35);if(stage==='bisect'){f.r=0;at(f,0,25,Math.PI,23);at(f,1,25,0,23);}return f;}
export function blendForms(a:Form,b:Form,t:number):Form{
 const result={...b,drops:b.drops.map((d,i)=>({x:a.drops[i].x+(d.x-a.drops[i].x)*t,y:a.drops[i].y+(d.y-a.drops[i].y)*t,r:Math.sqrt(a.drops[i].r**2*(1-t)+d.r**2*t),alpha:a.drops[i].alpha+(d.alpha-a.drops[i].alpha)*t}))};
 for(const k of ['x','y','triangle','square','angle','ring','dent','neck'] as const)result[k]=a[k]+(b[k]-a[k])*t;result.r=Math.sqrt(a.r*a.r*(1-t)+b.r*b.r*t);return result;
}
function smoothUnion(a:number,b:number,k:number){if(k<.0001)return Math.min(a,b);const h=clamp(.5+.5*(b-a)/k);return b+(a-b)*h-k*h*(1-h);}
function field(f:Form){const c=Math.cos(f.angle),s=Math.sin(f.angle);return(x:number,y:number)=>{
 const dx=x-f.x,dy=y-f.y,px=dx*c+dy*s,py=-dx*s+dy*c,radius=Math.hypot(px,py);let value=f.r>.05?radius-f.r:1e5;
 if(f.square){const qx=Math.abs(px)-(f.r-7),qy=Math.abs(py)-(f.r-7);const square=Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0)-5;value=value*(1-f.square)+square*f.square;}
 if(f.triangle){let tx=Math.abs(px)-(f.r-8),ty=-py+(f.r-8)/Math.sqrt(3);if(tx+Math.sqrt(3)*ty>0){const a=tx;tx=(tx-Math.sqrt(3)*ty)/2;ty=(-Math.sqrt(3)*a-ty)/2;}tx-=clamp(tx,-2*(f.r-8),0);const tri=-Math.hypot(tx,ty)*Math.sign(ty)-6;value=value*(1-f.triangle)+tri*f.triangle;}
 if(f.ring>0)value=Math.max(value,f.ring-radius);if(f.dent>0)value=Math.max(value,f.dent-Math.hypot(px-29,py+12));
 for(const d of f.drops)if(d.r>.05&&(d.alpha>=.999||!detached(f,d)))value=smoothUnion(value,Math.hypot(x-d.x,y-d.y)-d.r,f.neck);return value;
};}
/** 200×160 局部场，2px 网格。只输出一条合并轮廓，无 SVG blur 或滤镜。 */
export function fluidPath(f:Form):string{
 const step=2,cols=101,rows=81,distance=field(f),values=new Float32Array(cols*rows);for(let y=0;y<rows;y++)for(let x=0;x<cols;x++)values[y*cols+x]=distance(x*step,y*step);
 const segments:[number[],number[]][]=[];
 for(let y=0;y<rows-1;y++)for(let x=0;x<cols-1;x++){
  const v0=values[y*cols+x],v1=values[y*cols+x+1],v2=values[(y+1)*cols+x+1],v3=values[(y+1)*cols+x];const mask=(v0<0?1:0)|(v1<0?2:0)|(v2<0?4:0)|(v3<0?8:0);if(mask===0||mask===15)continue;
  const p=[[x*step,y*step],[(x+1)*step,y*step],[(x+1)*step,(y+1)*step],[x*step,(y+1)*step]],v=[v0,v1,v2,v3],crossings:number[][]=[];
  for(let e=0;e<4;e++){const j=(e+1)%4;if((v[e]<0)!==(v[j]<0)){const t=v[e]/(v[e]-v[j]);crossings.push([p[e][0]+(p[j][0]-p[e][0])*t,p[e][1]+(p[j][1]-p[e][1])*t]);}}
  if(crossings.length===2)segments.push([crossings[0],crossings[1]]);else if(crossings.length===4){if((v0+v1+v2+v3)/4<0)segments.push([crossings[0],crossings[3]],[crossings[1],crossings[2]]);else segments.push([crossings[0],crossings[1]],[crossings[2],crossings[3]]);}
 }
 const key=(p:number[])=>`${p[0].toFixed(3)},${p[1].toFixed(3)}`,links=new Map<string,{i:number;end:number}[]>();segments.forEach((segment,i)=>segment.forEach((p,end)=>{const k=key(p);links.set(k,[...(links.get(k)||[]),{i,end}]);}));const used=new Set<number>(),paths:string[]=[];
 segments.forEach((segment,i)=>{if(used.has(i))return;used.add(i);const points=[segment[0],segment[1]];let last=segment[1];for(let n=0;n<1000;n++){const next=links.get(key(last))?.find(e=>!used.has(e.i));if(!next)break;used.add(next.i);last=segments[next.i][1-next.end];points.push(last);}paths.push('M'+points.map(p=>`${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join('L')+'Z');});return paths.join('');
}
function detached(f:Form,d:Drop){return Math.hypot(d.x-f.x,d.y-f.y)>f.r+d.r+f.neck/4+1;}
export function fadePaths(f:Form){return f.drops.map(d=>({alpha:d.alpha<.999&&detached(f,d)?d.alpha:0,path:d.alpha<.999&&d.r>.05&&detached(f,d)?`M ${d.x-d.r} ${d.y} a ${d.r} ${d.r} 0 1 0 ${d.r*2} 0 a ${d.r} ${d.r} 0 1 0 ${-d.r*2} 0 Z`:''}));}
