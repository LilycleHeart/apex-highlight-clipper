const{test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');const{shareFiles,qqShareUrl}=require('../dist-electron/electron/qqShare');
test('QQ分享完整编码加号百分号与中文，整批验证后只打开一次会话选择',{skip:process.platform!=='win32'},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'apex-share-'));
 try{
  const files=[path.join(root,'死敌+猎兽 100% & 1.mp4'),path.join(root,"片段 '2.mp4")];await Promise.all(files.map(file=>fs.writeFile(file,'fixture')));const allowed=new Set(files.map(file=>file.toLowerCase())),opened=[];
  assert.deepEqual(await shareFiles([...files,files[0]],allowed,async uri=>{opened.push(uri);}),{status:'opened',count:2,command:'QQ好友'});assert.equal(opened.length,1);
  const uri=new URL(opened[0]),payload=JSON.parse(uri.searchParams.get('actionParams'));assert.equal(uri.searchParams.get('subCmd'),'friendSelector');assert.equal(uri.searchParams.get('action'),'share');assert.deepEqual(payload,{sourceType:'shareToQQ',msgItems:files.map(file=>({type:'file',path:file.replaceAll('\\','/')}))});assert.ok(opened[0].includes('%2B')&&opened[0].includes('%25'));assert.equal(payload.isShareToMyPhoneDirect,undefined);
  await fs.unlink(files[1]);await assert.rejects(shareFiles(files,allowed,async uri=>opened.push(uri)),/已移动或无法读取/);assert.equal(opened.length,1);
  await assert.rejects(shareFiles([files[0]],allowed,async()=>{throw Error('QQ unavailable');}),/无法打开 QQ/);
  assert.throws(()=>qqShareUrl(['D:/'+('长路径'.repeat(4000))+'.mp4']),/路径过长/);
 }finally{if(path.dirname(path.resolve(root))!==path.resolve(os.tmpdir())||!path.basename(root).startsWith('apex-share-'))throw Error('Unexpected cleanup target');await fs.rm(root,{recursive:true,force:true});}
});
