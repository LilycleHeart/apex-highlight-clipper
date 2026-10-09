import type {Stage} from './shared';
export interface Pose {bodyX:number;bodyY:number;angle:number;breath:number;gazeX:number;gazeY:number;focus:number;smile:number;blink:number;leftX:number;leftY:number;rightX:number;rightY:number;film:number;filmX:number;filmY:number;filmW:number;filmH:number;filmOffset:number;handles:number;handleL:number;handleR:number;source:number;stack:number;stackX:number;stackY:number;stackW:number;stackH:number;stackBack:number;leftStack:number;card:number;cardX:number;cardY:number;cardAngle:number;cardScale:number;tag:number;tagX:number;tagY:number;bookmark:number;stamp:number}
const tau=Math.PI*2,clamp=(v:number)=>Math.max(0,Math.min(1,v));const ease=(v:number)=>{v=clamp(v);return v*v*(3-2*v);};
const base=():Pose=>({bodyX:0,bodyY:0,angle:0,breath:0,gazeX:0,gazeY:0,focus:0,smile:0,blink:1,leftX:51,leftY:103,rightX:149,rightY:103,film:0,filmX:43,filmY:111,filmW:114,filmH:17,filmOffset:0,handles:0,handleL:68,handleR:132,source:0,stack:0,stackX:116,stackY:112,stackW:48,stackH:24,stackBack:1,leftStack:0,card:0,cardX:143,cardY:102,cardAngle:0,cardScale:1,tag:0,tagX:132,tagY:117,bookmark:0,stamp:0});
function blinkAt(t:number){const p=((t%23)+23)%23;for(const at of[2.13,7.86,13.49,21.02]){const d=Math.abs(p-at);if(d<.085)return .08+.92*ease(d/.085);}return 1;}
function bar(t:number){const p=((t%3.6)+3.6)%3.6/3.6;if(p<.78){const q=p/.78*3,step=Math.min(2,Math.floor(q)),local=q-step;return(step+ease(local))/3;}return 1-ease((p-.78)/.22);}
export function coreStage(stage:Stage){if(['coarse','sample','smart','pipeline','fallback'].includes(stage))return'coarse';if(stage==='numeric')return'fine';if(stage==='outcomes')return'lifecycle';if(stage==='audit'||stage==='combat_outcomes')return'verify';return stage;}
export function poseAt(stage:Stage,t:number):Pose{
 const f=base(),core=coreStage(stage);f.blink=blinkAt(t);
 if(core==='idle'||core==='stopped'||core==='cache'){f.breath=.008*Math.sin(t*tau/5);f.bodyY=.25*Math.sin(t*tau/5);if(stage==='stopped'||stage==='cache'){f.breath*=.5;f.bodyY*=.5;}return f;}
 if(core==='importing'||core==='probe'){
  const p=((t%2.8)+2.8)%2.8/2.8,q=ease(clamp((p-.08)/.6)),reset=ease((p-.85)/.15);f.stack=1;f.stackX=82;f.stackY=117;f.stackW=45;f.stackH=22;f.card=ease(p/.12)*(1-ease(clamp((p-.75)/.15)));f.cardX=150-46*q+46*reset;f.cardY=103+17*q-17*reset;f.rightX=f.cardX+17;f.rightY=f.cardY+10;f.leftX=83;f.leftY=128;f.gazeX=3-3*ease(p/.6)+3*reset;f.gazeY=2;f.bodyY=.75*Math.sin(p*Math.PI);if(core==='probe'){f.cardX=108;f.cardY=119;f.rightX=125;f.rightY=127;f.card=1;f.stack=0;f.leftX=91;f.leftY=127;f.gazeX=1.2*Math.sin(t*tau/2.8);}return f;
 }
 if(core==='coarse'){
  const p=((t%4)+4)%4/4;const push=p<.72?ease(p/.72):1-ease((p-.72)/.28);const handPhase=((t-.1)%4+4)%4/4,handPush=handPhase<.72?ease(handPhase/.72):1-ease((handPhase-.72)/.28);
  f.focus=.65;f.gazeX=-3+6*push;f.gazeY=3;f.film=1;f.filmX=43+7*handPush;f.filmOffset=-11*handPush;f.leftX=f.filmX+8;f.leftY=119;f.rightX=f.filmX+103;f.rightY=119;f.bodyX=.5*Math.sin((t-.2)*tau/4);f.angle=.7*Math.sin((t-.2)*tau/4);return f;
 }
 if(core==='bisect'){
  const travel=bar(t-.1);f.focus=1;f.gazeX=2.5*Math.sin(t*tau/1.2);f.gazeY=3;f.film=1;f.handles=1;f.handleL=68+24*travel;f.handleR=132-24*travel;f.leftX=f.handleL;f.rightX=f.handleR;f.leftY=f.rightY=118;f.angle=.4*Math.sin((t-.2)*tau/3.6);return f;
 }
 if(core==='fine'){
  const q=.5-.5*Math.cos(t*tau/4);f.card=1;f.cardX=100;f.cardY=125-6*q;f.cardScale=1+.06*q;f.leftX=f.cardX-19*f.cardScale;f.rightX=f.cardX+19*f.cardScale;f.leftY=f.rightY=f.cardY+5*f.cardScale;f.gazeY=3;f.angle=4+Math.sin((t-.2)*tau/4);return f;
 }
 if(core==='lifecycle'){
  const q=.5-.5*Math.cos(t*tau/4.2);f.card=1;f.cardX=77;f.cardY=123;f.leftX=60;f.leftY=128;f.film=1;f.filmX=95;f.filmY=118;f.filmW=54+15*q;f.filmOffset=-9*q;f.rightX=f.filmX+f.filmW-7;f.rightY=125;f.gazeX=1+3*q;f.gazeY=3;f.bodyX=.5*q;return f;
 }
 if(core==='weapons'){
  const p=((t%3.6)+3.6)%3.6/3.6,q=.5-.5*Math.cos(t*tau/3.6);f.card=1;f.cardX=93;f.cardY=123;f.tag=1;f.tagX=135-17*q;f.tagY=115;f.rightX=f.tagX+10;f.rightY=f.tagY+6;f.leftX=74;f.leftY=128;f.gazeX=2*Math.sin(t*tau/1.8);f.gazeY=3;f.angle=p>.7?.7*Math.sin((p-.7)/.3*Math.PI):0;return f;
 }
 if(core==='export'){
  const p=((t%4.2)+4.2)%4.2/4.2;f.focus=.8;f.source=1;f.stack=1;f.card=1;
  if(p<.28){const q=ease(p/.28);f.cardX=55+44*q;f.cardY=118-13*q;f.leftX=f.cardX-17;f.leftY=f.cardY+10;f.rightX=149;f.rightY=103;f.cardAngle=-6*(1-q);f.card=ease(p/.08);}
  else if(p<.48){const q=ease((p-.28)/.2);f.cardX=99+15*q;f.cardY=105;f.leftX=f.cardX-17;f.leftY=115;f.rightX=149+(f.cardX+17-149)*q;f.rightY=103+12*q;}
  else if(p<.74){const q=ease((p-.48)/.26);f.cardX=114+29*q;f.cardY=105+19*q;f.rightX=f.cardX+17;f.rightY=f.cardY+10;f.leftX=97+(51-97)*q;f.leftY=115-12*q;f.cardAngle=4*Math.sin(q*Math.PI);}
  else{const q=ease((p-.74)/.26),reset=ease((p-.88)/.12);f.cardX=143;f.cardY=124;f.card=1-ease((p-.74)/.12);f.leftX=51-13*reset;f.leftY=103+25*reset;f.rightX=160-11*q;f.rightY=134-31*q;}
  // 视线领先手部约100ms，身体再晚100ms跟随；卡片位置与抓握端绑定。
  const look=clamp((p+.024)/.74);f.gazeX=-3+6*look-6*ease((p-.85)/.15);f.gazeY=3;f.bodyX=.7*Math.sin((t-.2)*tau/4.2);f.angle=1.1*Math.sin((t-.2)*tau/4.2);return f;
 }
 if(core==='completed'){
  const lift=ease((t-.1)/.45);f.stack=1;f.stackX=72;f.stackY=112-11*lift;f.stackW=55;f.stackH=32;f.leftX=77;f.leftY=f.stackY+18;f.rightX=123;f.rightY=f.stackY+18;f.smile=ease((t-.25)/.35);f.stamp=f.smile;f.focus=0;f.blink=1;f.gazeY=1;
  f.bodyY=t<1?.8*Math.sin(clamp((t-.4)/.6)*Math.PI):0;f.angle=t<1?1.5*Math.sin(clamp((t-.4)/.6)*Math.PI):0;return f;
 }
 if(core==='verify'){
  const p=((t%4)+4)%4/4;f.stack=1;f.stackX=126;f.stackY=113;f.stackW=44;f.stackH=25;f.stackBack=0;f.leftStack=1;f.card=1;
  if(p<.32){const q=ease(p/.32);f.cardX=146-46*q;f.cardY=122-3*q;f.rightX=f.cardX+17;f.rightY=f.cardY+10;f.leftX=51;f.leftY=103;f.card=ease(p/.08);}
  else if(p<.5){f.cardX=100;f.cardY=119;f.rightX=117;f.rightY=129;f.leftX=83;f.leftY=129;f.angle=.7*Math.sin((p-.32)/.18*Math.PI);}
  else if(p<.8){const q=ease((p-.5)/.3);f.cardX=100-45*q;f.cardY=119+5*q;f.leftX=f.cardX-17;f.leftY=f.cardY+10;f.rightX=117+32*q;f.rightY=129-26*q;}
  else{f.cardX=55;f.cardY=124;f.card=1-ease((p-.8)/.1);const q=ease((p-.8)/.2),reset=ease((p-.9)/.1);f.leftX=38+13*q;f.leftY=134-31*q;f.rightX=149+14*reset;f.rightY=103+29*reset;}
  f.gazeX=3-6*clamp(p/.8)+6*ease((p-.84)/.16);f.gazeY=3;return f;
 }
 if(core==='stopping'){
  const q=ease(t/.55),release=ease((t-.55)/.35);f.film=1;f.filmY=117;f.bookmark=q;f.leftX=51+7*q;f.leftY=119;f.rightX=(149-47*q)*(1-release)+149*release;f.rightY=119;f.gazeY=2*(1-release);f.blink=1;return f;
 }
 if(core==='error'){
  f.card=1;f.cardX=83;f.cardY=127;f.leftX=66;f.leftY=134;f.gazeX=-1;f.gazeY=2;f.angle=-2+.25*Math.sin(t*tau/5);return f;
 }
 return f;
}
export function staticPose(stage:Stage){const p=poseAt(stage,stage==='bisect'?1.75:stage==='export'?2.45:stage==='completed'?1:1.3);p.blink=1;p.breath=0;return p;}
export function blendPose(a:Pose,b:Pose,t:number,elapsed:number):Pose{
 const result={...b};const eye=ease(Math.min(1,t*1.35)),hand=ease(clamp((elapsed-90)/460)),body=ease(clamp((elapsed-160)/390));
 for(const key of Object.keys(b) as (keyof Pose)[]){const blend=['gazeX','gazeY','focus','smile','blink'].includes(key)?eye:['bodyX','bodyY','angle','breath'].includes(key)?body:hand;result[key]=a[key]+(b[key]-a[key])*blend;}return result;
}
export function handContour(x:number,y:number,gx:number,gy:number){
 const dx=gx-x,dy=gy-y,length=Math.max(.001,Math.hypot(dx,dy)),radius=6;
 // 左右手身份决定弯曲侧，法线随手掌位置连续变化，不按阈值突然翻转。
 const side=x<100?1:-1,nx=-dy/length*side,ny=dx/length*side;
 // 限制曲率：弯曲量至多长度的12%，不会把等厚偏移轮廓卷回自身。
 const bend=Math.min(5,length*.12),cx=(x+gx)/2+nx*bend,cy=(y+gy)/2+ny*bend;
 const outer:number[][]=[],inner:number[][]=[];let tangent=0;
 for(let i=0;i<=16;i++){const t=i/16,u=1-t,px=u*u*x+2*u*t*cx+t*t*gx,py=u*u*y+2*u*t*cy+t*t*gy;
  const tx=2*(u*(cx-x)+t*(gx-cx)),ty=2*(u*(cy-y)+t*(gy-cy)),norm=Math.max(.001,Math.hypot(tx,ty));const ox=-ty/norm*radius,oy=tx/norm*radius;
  outer.push([px+ox,py+oy]);inner.push([px-ox,py-oy]);if(i===16)tangent=Math.atan2(ty,tx);
 }
 const cap:number[][]=[];for(let i=1;i<12;i++){const angle=tangent+Math.PI/2-i*Math.PI/12;cap.push([gx+radius*Math.cos(angle),gy+radius*Math.sin(angle)]);}
 const coord=(p:number[])=>`${p[0].toFixed(2)} ${p[1].toFixed(2)}`;
 const outline='M'+outer.map(coord).join('L')+`A6 6 0 0 0 ${coord(inner[16])}`+inner.slice(0,16).reverse().map(p=>'L'+coord(p)).join('');
 return{fill:outline+'Z',outline,points:[...outer,...cap,...inner.slice().reverse()],outer,inner};
}
export function handPath(x:number,y:number,gx:number,gy:number){return handContour(x,y,gx,gy).fill;}
export function oval(cx:number,cy:number,rx:number,ry:number){const k=.55228475;return`M${cx-rx} ${cy} C${cx-rx} ${cy-k*ry} ${cx-k*rx} ${cy-ry} ${cx} ${cy-ry} C${cx+k*rx} ${cy-ry} ${cx+rx} ${cy-k*ry} ${cx+rx} ${cy} C${cx+rx} ${cy+k*ry} ${cx+k*rx} ${cy+ry} ${cx} ${cy+ry} C${cx-k*rx} ${cy+ry} ${cx-rx} ${cy+k*ry} ${cx-rx} ${cy}Z`;}
