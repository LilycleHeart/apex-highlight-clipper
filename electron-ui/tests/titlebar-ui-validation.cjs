const{_electron}=require('playwright-core');const fs=require('node:fs/promises');const path=require('node:path');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'output/playwright/v3-titlebar');
(async()=>{await fs.mkdir(out,{recursive:true});const app=await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),args:[root],env:{...process.env,APEX_UI_TEST_HOME:path.join(out,'preferences'),APEX_PROJECT_ROOT:path.resolve(root,'..')}});try{
 const page=await app.firstWindow();await page.getByRole('tab',{name:'开始',exact:true}).waitFor();await page.getByRole('button',{name:'剪辑设置',exact:true}).waitFor({state:'visible'});
 await page.screenshot({path:path.join(out,'start.png')});await page.getByRole('tab',{name:'整理片段',exact:true}).click();
 await page.waitForTimeout(110);const mid=await page.locator('#tab-clips path').getAttribute('d');await page.screenshot({path:path.join(out,'middle.png')});
 await page.getByRole('tab',{name:'开始',exact:true}).click();await page.waitForTimeout(600);assert.equal(await page.locator('#tab-clips path').getAttribute('opacity'),'0');assert.equal(await page.locator('#tab-start path').getAttribute('opacity'),'1');assert.ok(mid.includes('Q'));
 await page.getByRole('tab',{name:'统计数据',exact:true}).click();await page.waitForTimeout(80);await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.send('worker-event',{type:'visibility',hidden:true}));await page.waitForTimeout(40);const before=await page.locator('#tab-statistics path').getAttribute('d');await page.waitForTimeout(600);assert.equal(await page.locator('#tab-statistics path').getAttribute('d'),before);
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.send('worker-event',{type:'visibility',hidden:false}));await page.waitForTimeout(600);assert.equal(await page.locator('#tab-statistics path').getAttribute('opacity'),'1');
 await page.screenshot({path:path.join(out,'end.png')});console.log('Titlebar: middle/reversal/visibility/native overlay PASS');
}finally{await app.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
