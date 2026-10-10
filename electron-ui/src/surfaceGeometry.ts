// 2026-10-09 冻结交接包：同一条轨迹用于导航、边界展开和按压。
export const NAV={duration:.5,decay:13.7755052,omega:14.0538264};
export const PRESS={duration:.15,decay:7.033412493122591/.15,omega:6.2028867749790555/.15};
export const clamp=(x:number)=>Math.max(0,Math.min(1,x));
export const VIEW_HEAD=[.25,1,.5,1] as const,VIEW_TAIL=[.25,.2,.5,1] as const,MENU_EASE=[.2,.9,.25,1] as const;
export function bezierProgress(x:number,curve:readonly number[]){
 x=clamp(x);if(x===0||x===1)return x;const [x1,y1,x2,y2]=curve;let low=0,high=1,t=x;
 for(let i=0;i<18;i++){const u=1-t,px=3*u*u*t*x1+3*u*t*t*x2+t*t*t;if(px>x)high=t;else low=t;t=(low+high)/2;}
 return 3*(1-t)**2*t*y1+3*(1-t)*t*t*y2+t*t*t;
}
export function connectedTabPath(q:number,w=116){q=clamp(q);const h=30*q,b=36,r=Math.min(12,h),foot=14*q;return plate(16,w,b-h,h,r)+corner(16,b,foot,true)+corner(16+w,b,foot,false);}
export function sampleSpring(from:number,to:number,elapsed:number,p=NAV){
 if(elapsed>=p.duration)return to;
 const a=to-from,b=p.decay*a/p.omega;
 return to-Math.exp(-p.decay*elapsed)*(a*Math.cos(p.omega*elapsed)+b*Math.sin(p.omega*elapsed));
}
function plate(x:number,w:number,top:number,h:number,r:number){
 r=Math.min(r,h);const p=2/(2**1.5),bottom=top+h,points=[[x+r,top],[x+w-r,top]];
 for(let i=1;i<=20;i++){const t=i/20*Math.PI/2;points.push([x+w-r+r*Math.sin(t)**p,top+r-r*Math.cos(t)**p]);}
 points.push([x+w,bottom],[x,bottom],[x,top+r]);
 for(let i=1;i<=20;i++){const t=i/20*Math.PI/2;points.push([x+r-r*Math.cos(t)**p,top+r-r*Math.sin(t)**p]);}
 return points.map((a,i)=>(i?'L':'M')+a.join(' ')).join(' ')+'Z';
}
function corner(x:number,b:number,r:number,left:boolean){const s=left?-1:1;return `M${x+s*r} ${b}Q${x+s*.5859375*r} ${b} ${x+s*.29296875*r} ${b-.29296875*r}Q${x} ${b-.5859375*r} ${x} ${b-r}L${x} ${b}Z`;}
export function tabGeometry(q:number,x=0,w=116){const height=15+16*q,bottom=36+q,cb=35+q,scale=30/35;return {top:bottom-height,height,bottom,opacity:clamp(q),path:plate(x,w,bottom-height,height,18*scale)+corner(x,cb,(3+11*q)*scale,true)+corner(x+w,cb,(2+12*q)*scale,false)};}
// 开口边界先铺开，中部随后跟上；只改变背板，内容不参与形变。
export function edgeGeometry(w:number,h:number,q:number,r=24){
 w=Math.max(1,w);h=Math.max(1,h);r=Math.min(r,w/2,h/2);
 const tension=Math.sin(Math.PI*clamp(q)),inset=Math.min(14,w*.025)*tension;
 return `M${r} 0H${w-r}Q${w} 0 ${w} ${r}Q${w-inset*2} ${h*.3} ${w-inset} ${h*.5}Q${w} ${h*.72} ${w} ${h-r}Q${w} ${h} ${w-r} ${h}H${r}Q0 ${h} 0 ${h-r}V${r}Q0 0 ${r} 0Z`;
}
export function drawerGeometry(w:number,h:number,q:number){
 const reveal=w*clamp(q),edge=w-reveal,front=Math.min(28,reveal/2),lag=Math.sin(Math.PI*clamp(q))*Math.min(32,reveal*.12);
 return `M${w} 0H${edge+front}Q${edge} 0 ${edge} ${front}Q${edge+lag} ${h*.33} ${edge+lag*.5} ${h*.5}Q${edge} ${h*.7} ${edge} ${h-front}Q${edge} ${h} ${edge+front} ${h}H${w}Z`;
}
