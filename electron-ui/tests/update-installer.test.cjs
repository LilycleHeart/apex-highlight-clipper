const{test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),{createHash}=require('node:crypto');
const{installerAsset}=require('../dist-electron/electron/updates'),{downloadInstaller,installationPaths,pruneLegacyLauncher}=require('../dist-electron/electron/updateInstaller');
const bytes=Buffer.from('verified update fixture'),sha=createHash('sha256').update(bytes).digest('hex');
const asset={version:'1.0.2',name:'Apex-Clipper-1.0.2-Setup-x64.exe',url:'https://github.com/LilycleHeart/apex-highlight-clipper/releases/download/v1.0.2/Apex-Clipper-1.0.2-Setup-x64.exe',bytes:bytes.length,sha256:sha};
test('新旧安装布局确定同一升级目录，兼容入口仅在与启动器相同且目录无其他文件时清理',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'apex-layout-')),app=path.join(root,'app'),legacy=path.join(app,'Apex Highlight Clipper.exe'),launcher=path.join(root,'Apex Highlight Clipper.exe');
 try{
  assert.equal(installationPaths(legacy).target,root);
  const current=installationPaths(path.join(root,'resources/desktop/Apex Highlight Clipper.exe'));
  assert.equal(current.target,root);assert.equal(current.helper,path.join(root,'resources/scripts/update-install.ps1'));
  await fs.mkdir(app);await fs.writeFile(launcher,bytes);await fs.writeFile(legacy,'original desktop executable');
  await pruneLegacyLauncher(root);assert.equal(await fs.readFile(legacy,'utf8'),'original desktop executable');
  await fs.writeFile(legacy,bytes);await fs.writeFile(path.join(app,'user.txt'),'keep');await pruneLegacyLauncher(root);assert.deepEqual(await fs.readFile(legacy),bytes);
  await fs.unlink(path.join(app,'user.txt'));await pruneLegacyLauncher(root);await assert.rejects(fs.stat(app),{code:'ENOENT'});
 }finally{await fs.unlink(launcher);await fs.rmdir(root);}
});
test('仅接受本仓库已上传且有SHA256的同版本安装包',()=>{
 const release={tag_name:'v1.0.2',assets:[{name:asset.name,browser_download_url:asset.url,state:'uploaded',size:bytes.length,digest:'sha256:'+sha}]};assert.deepEqual(installerAsset(release),asset);assert.equal(installerAsset({...release,assets:[{...release.assets[0],browser_download_url:'https://evil.example/setup.exe'}]}),undefined);assert.equal(installerAsset({...release,assets:[{...release.assets[0],digest:null}]}),undefined);
});
test('流式下载、校验和缓存复用；错误安装包清除，重叠下载被锁阻止',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'apex-update-'));let calls=0;const fetcher=async()=>{calls++;return new Response(new ReadableStream({start(controller){controller.enqueue(bytes.subarray(0,8));controller.enqueue(bytes.subarray(8));controller.close();}}));};
 try{const progress=[];const file=await downloadInstaller(asset,root,fetcher,p=>progress.push(p));assert.deepEqual(await fs.readFile(file),bytes);assert.equal(progress.at(-1),100);await downloadInstaller(asset,root,fetcher,()=>{});assert.equal(calls,1);
 await assert.rejects(()=>downloadInstaller({...asset,sha256:'0'.repeat(64)},root,fetcher,()=>{}),/校验/);assert.equal((await fs.readdir(root)).length,0);
 let release;const blocked=new Promise(resolve=>release=resolve);const pending=downloadInstaller(asset,root,async()=>{await blocked;return new Response(bytes);},()=>{});while(!(await fs.readdir(root)).includes('download.lock'))await new Promise(resolve=>setTimeout(resolve,5));await assert.rejects(()=>downloadInstaller(asset,root,fetcher,()=>{}),/另一个/);release();await pending;
 await fs.writeFile(path.join(root,'download.lock'),'');const old=new Date(Date.now()-3600000);await fs.utimes(path.join(root,'download.lock'),old,old);await downloadInstaller(asset,root,fetcher,()=>{});assert.deepEqual(await fs.readFile(file),bytes);
 }finally{for(const name of await fs.readdir(root))await fs.unlink(path.join(root,name));await fs.rmdir(root);}
});
test('配置镜像后安装包从镜像地址下载，校验仍对比官方地址',async()=>{const root=await fs.mkdtemp(path.join(os.tmpdir(),'ahc-mirror-'));const bytes=Buffer.from('installer-bytes');const sha=createHash('sha256').update(bytes).digest('hex');const asset={version:'1.0.2',name:'Apex-Clipper-1.0.2-Setup-x64.exe',url:'https://github.com/LilycleHeart/apex-highlight-clipper/releases/download/v1.0.2/Apex-Clipper-1.0.2-Setup-x64.exe',bytes:bytes.length,sha256:sha};const seen=[];const fetcher=async url=>{seen.push(url);return new Response(bytes);};const file=await downloadInstaller(asset,root,fetcher,()=>{},undefined,'https://gh-proxy.com/');assert.deepEqual(await fs.readFile(file),bytes);assert.equal(seen[0],'https://gh-proxy.com/'+asset.url);await fs.rm(root,{recursive:true,force:true});});
