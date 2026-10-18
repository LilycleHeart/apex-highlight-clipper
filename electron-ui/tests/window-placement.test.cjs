const{test}=require('node:test');const assert=require('node:assert/strict');const{restoreWindowPlacement}=require('../dist-electron/electron/windowPlacement');
test('窗口恢复保留正常位置尺寸与最大化，断开显示器或分辨率变小后仍可见',()=>{
 const primary={x:0,y:0,width:1920,height:1040},left={x:-1920,y:0,width:1920,height:1040};
 const saved={x:-1500,y:100,width:1000,height:740,maximized:true};
 assert.deepEqual(restoreWindowPlacement(saved,[primary,left],primary),saved);
 assert.deepEqual(restoreWindowPlacement(saved,[primary],primary),{x:0,y:100,width:1000,height:740,maximized:true});
 const small={x:0,y:0,width:720,height:560};
 assert.deepEqual(restoreWindowPlacement(saved,[small],small),{...small,maximized:true});
 assert.deepEqual(restoreWindowPlacement({x:NaN,y:0,width:1000,height:740},[primary],primary),{x:400,y:110,width:1120,height:820,maximized:false});
});
