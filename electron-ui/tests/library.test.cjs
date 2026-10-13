const{test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');
const{discoverTasks,mergeLibrary,LibraryStore}=require('../dist-electron/electron/library');

test('名称按实际优势拼写归一，保留不同账号和不同中文队友',()=>{
 const accountNames=['[YURI] Liliumcordis','[YURI]Liliumcordis','[YURI] Liliumcordis','[YURI] Liliumcordis','[YURI] Liiumcordis','[YURI] Liliumcordis','[YURI] LilycleHeart','Katahane'];
 const clips=accountNames.map((accountName,i)=>({path:path.resolve(`name-${i}.mp4`),source:`source-${i}`,accountName,teammates:[{name:i%2?'neko':'NEKO',confidence:.95},{name:i%2?'落生烟':'落生烬',confidence:.95}]}));
 const results=mergeLibrary([{source:'fixture',clips}])[0].clips;
 assert.ok(results.slice(0,6).every(clip=>clip.accountName==='[YURI] Liliumcordis'));
 assert.equal(results[6].accountName,'[YURI] LilycleHeart');assert.equal(results[7].accountName,'Katahane');
 assert.ok(results[4].accountAliases.includes('[YURI] Liiumcordis'));
 assert.equal(new Set(results.map(clip=>clip.teammates[0].name)).size,1);
 assert.deepEqual(new Set(results.map(clip=>clip.teammates[1].name)),new Set(['落生烟','落生烬']));
 assert.equal(clips[4].accountName,'[YURI] Liiumcordis');
});
test('启动发现已知根的多个历史任务，不重复登记，不扫描缓存',async()=>{const root=await fs.mkdtemp(path.join(os.tmpdir(),'ahc-library-'));try{for(const dir of ['task-a','group/task-b','validation/ignored']){await fs.mkdir(path.join(root,dir),{recursive:true});await fs.writeFile(path.join(root,dir,'task.json'),'{}');}const tasks=await discoverTasks([root,root],[path.join(root,'task-a/task.json')]);assert.equal(tasks.length,2);assert.equal((await fs.readFile(path.join(root,'task-a/task.json'),'utf8')),'{}');const store=new LibraryStore(path.join(root,'index.json'));await store.remember(tasks[0]);const restored=new LibraryStore(path.join(root,'index.json'));await restored.load();assert.equal((await restored.discover([root])).length,2);}finally{await fs.rm(root,{recursive:true,force:true});}});
test('跨任务引用同一个Windows路径只展示一次，不丢追溯字段',()=>{const clip={path:path.resolve('clip.mp4'),taskPath:'task-a',kills:null};const results=mergeLibrary([{source:'one',clips:[clip]},{source:'two',clips:[{...clip,path:clip.path.toUpperCase(),taskPath:'task-b'}]}]);assert.equal(results.length,1);assert.equal(results[0].clips[0].taskPath,'task-a');assert.equal(results[0].clips[0].kills,null);});

test('忽略持久化，登记和目录发现均跳过，手动选择可以重新登记',async()=>{const root=await fs.mkdtemp(path.join(os.tmpdir(),'ahc-ignore-'));try{const bad=path.join(root,'broken/task.json'),good=path.join(root,'valid/task.json'),pointer=path.join(root,'pointer.json');for(const file of [bad,good]){await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,file===bad?'broken':'{}');}const store=new LibraryStore(path.join(root,'index.json'));await store.remember(bad);await store.ignore([bad]);const restored=new LibraryStore(path.join(root,'index.json'));await restored.load();assert.equal(restored.isIgnored(bad.toUpperCase()),true);assert.deepEqual(await restored.discover([root]),[good]);const read=[];await restored.recoverLastTask([root],pointer,async file=>{read.push(file);return{path:file,finished:true};});assert.deepEqual(read,[good]);assert.equal(await fs.readFile(bad,'utf8'),'broken');await restored.remember(bad);assert.equal(restored.isIgnored(bad),true);await restored.remember(bad,true);assert.equal(restored.isIgnored(bad),false);}finally{await fs.rm(root,{recursive:true,force:true});}});
