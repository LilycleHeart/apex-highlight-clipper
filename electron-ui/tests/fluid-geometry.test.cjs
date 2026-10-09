const {test}=require('node:test');const assert=require('node:assert/strict');
const {stageForm,fluidPath,blendForms}=require('../dist-electron/src/fluidGeometry');
function area(p){let a=0;for(const contour of p.split('M').filter(Boolean)){const points=contour.replace(/Z/g,'').split('L').map(s=>s.trim().split(' ').map(Number));let s=0;for(let i=0;i<points.length;i++){const x=points[i],y=points[(i+1)%points.length];s+=x[0]*y[1]-y[0]*x[1];}a+=Math.abs(s)/2;}return a;}
function inverseEase(v){let a=0,b=1;for(let i=0;i<30;i++){const m=(a+b)/2;if(m*m*(3-2*m)<v)a=m;else b=m;}return(a+b)/2;}
test('融合中段面积保持在圆体的 95%–105%',()=>{const reference=area(fluidPath(stageForm('completed',1)));for(const merge of [0,.25,.5,.75,1]){const t=1.656+.864*inverseEase(merge);const actual=area(fluidPath(stageForm('bisect',t)));assert.ok(actual/reference>.95&&actual/reference<1.05,`${merge}: ${actual/reference}`);}});
test('圆角三角形有效面积在圆体 90%–110%',()=>{const reference=area(fluidPath(stageForm('completed',1)));for(let t=0;t<3.8;t+=.2){const ratio=area(fluidPath(stageForm('fine',t)))/reference;assert.ok(ratio>.9&&ratio<1.1,String(ratio));}});
test('阶段轮廓全部在固定画布边界内',()=>{for(const stage of ['idle','stopped','cache','importing','probe','coarse','bisect','fine','lifecycle','weapons','export','verify','stopping','completed','error'])for(let t=0;t<5;t+=.15){const d=fluidPath(stageForm(stage,t));assert.ok(!d.includes('NaN'));for(const m of d.matchAll(/(?:M|L)([\d.]+) ([\d.]+)/g)){const x=+m[1],y=+m[2];assert.ok(x>=16&&x<=184&&y>=16&&y<=144,`${stage} ${t} ${x} ${y}`);}}});
test('二分与扫描周期闭合，没有模板跳切',()=>{for(const [s,p]of[['bisect',3.6],['coarse',4.2]]){const a=stageForm(s,0),b=stageForm(s,p-1e-6);assert.ok(Math.abs(area(fluidPath(a))-area(fluidPath(b)))<2);}});
test('零端点混合精确保留当前形态',()=>{const a=stageForm('coarse',1.35),b=stageForm('completed',0);assert.deepEqual(blendForms(a,b,0),a);});
module.exports={area,inverseEase};
