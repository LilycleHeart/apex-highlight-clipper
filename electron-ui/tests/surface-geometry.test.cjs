const{test}=require('node:test');const assert=require('node:assert/strict');
const{sampleSpring,tabGeometry,drawerGeometry,edgeGeometry,PRESS}=require('../dist-electron/src/surfaceGeometry');
test('冻结导航弹簧不归一化尾值、保留4.59879%超调并精确停在500ms',()=>{
 assert.equal(sampleSpring(0,1,0),0);assert.equal(sampleSpring(0,1,.5),1);
 const peak=Math.max(...Array.from({length:501},(_,i)=>sampleSpring(0,1,i/1000)));
 assert.ok(Math.abs(peak-1.0459879)<.00001);assert.equal(sampleSpring(1,0,.5),0);
});
test('中途反向从渲染值开始，零初速度，无跳变',()=>{const x=sampleSpring(0,1,.12);assert.equal(sampleSpring(x,0,0),x);assert.equal(sampleSpring(x,0,.5),0);assert.ok(Math.abs(sampleSpring(x,0,.00001)-x)<.000001);});
test('36px版附着凹角使用双二次曲线，终点重叠1px，固定上角',()=>{const g=tabGeometry(1);assert.equal(g.bottom,37);assert.equal(g.top,6);assert.equal(g.height,31);assert.equal(g.opacity,1);assert.equal((g.path.match(/Q/g)||[]).length,4);assert.equal(tabGeometry(1.04).opacity,1);});
test('按钮按压150ms、drawer收缩端点、边界中段曲率',()=>{assert.equal(sampleSpring(0,1,.15,PRESS),1);assert.notEqual(edgeGeometry(400,300,.5),edgeGeometry(400,300,1));assert.ok(drawerGeometry(420,820,0).startsWith('M420 0H420'));assert.ok(drawerGeometry(420,820,1).includes('Q0 0'));});
