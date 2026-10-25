const{test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');
const{discoverTasks,mergeLibrary,LibraryStore}=require('../dist-electron/electron/library');

test('两个同形昵称同时出现时保留两个人',()=>{
 const clips=Array.from({length:8},(_,i)=>({path:path.resolve(`distinct-${i}.mp4`),source:`source-${i}`,accountName:'Liliumcordis',teammates:[{name:'Liliumcordis',confidence:.95}]}));
 clips[0].teammates.push({name:'Liiumcordis',confidence:.95});
 assert.deepEqual(mergeLibrary([{source:'fixture',clips}])[0].clips[0].teammates.map(value=>value.name),['Liliumcordis','Liiumcordis']);
});

test('名称按实际优势拼写归一，保留不同账号和不同中文队友',()=>{
 const accountNames=['[YURI] Liliumcordis','[YURI]Liliumcordis','[YURI] Liliumcordis','[YURI] Liliumcordis','[YURI] Liiumcordis','[YURI] Liliumcordis','[YURI] LilycleHeart','Katahane'];
 const clips=accountNames.map((accountName,i)=>({path:path.resolve(`name-${i}.mp4`),source:`source-${i}`,accountName,teammates:[{name:i%2?'[BAD]neko':'[BA]NEKO',confidence:.95},{name:i%2?'落生烟':'落生烬',confidence:.95}]}));
 const results=mergeLibrary([{source:'fixture',clips}])[0].clips;
 assert.ok(results.slice(0,6).every(clip=>clip.accountName==='Liliumcordis'));
 assert.equal(results[6].accountName,'LilycleHeart');assert.equal(results[7].accountName,'Katahane');
 assert.ok(results[4].accountAliases.includes('Liiumcordis'));
 assert.equal(new Set(results.map(clip=>clip.teammates[0].name)).size,1);
 assert.equal(results[0].teammates[0].name,'NEKO');
 assert.deepEqual(new Set(results.map(clip=>clip.teammates[1].name)),new Set(['落生烟','落生烬']));
 assert.equal(clips[4].accountName,'[YURI] Liiumcordis');
});
test('启动发现已知根的多个历史任务，不重复登记，不扫描缓存',async()=>{const root=await fs.mkdtemp(path.join(os.tmpdir(),'ahc-library-'));try{for(const dir of ['task-a','group/task-b','validation/ignored']){await fs.mkdir(path.join(root,dir),{recursive:true});await fs.writeFile(path.join(root,dir,'task.json'),'{}');}const tasks=await discoverTasks([root,root],[path.join(root,'task-a/task.json')]);assert.equal(tasks.length,2);assert.equal((await fs.readFile(path.join(root,'task-a/task.json'),'utf8')),'{}');const store=new LibraryStore(path.join(root,'index.json'));await store.remember(tasks[0]);const restored=new LibraryStore(path.join(root,'index.json'));await restored.load();assert.equal((await restored.discover([root])).length,2);}finally{await fs.rm(root,{recursive:true,force:true});}});
test('跨任务引用同一个Windows路径只展示一次，不丢追溯字段',()=>{const clip={path:path.resolve('clip.mp4'),taskPath:'task-a',kills:null};const results=mergeLibrary([{source:'one',clips:[clip]},{source:'two',clips:[{...clip,path:clip.path.toUpperCase(),taskPath:'task-b'}]}]);assert.equal(results.length,1);assert.equal(results[0].clips[0].taskPath,'task-a');assert.equal(results[0].clips[0].kills,null);});

test('忽略持久化，登记和目录发现均跳过，手动选择可以重新登记',async()=>{const root=await fs.mkdtemp(path.join(os.tmpdir(),'ahc-ignore-'));try{const bad=path.join(root,'broken/task.json'),good=path.join(root,'valid/task.json'),pointer=path.join(root,'pointer.json');for(const file of [bad,good]){await fs.mkdir(path.dirname(file),{recursive:true});await fs.writeFile(file,file===bad?'broken':'{}');}const store=new LibraryStore(path.join(root,'index.json'));await store.remember(bad);await store.ignore([bad]);const restored=new LibraryStore(path.join(root,'index.json'));await restored.load();assert.equal(restored.isIgnored(bad.toUpperCase()),true);assert.deepEqual(await restored.discover([root]),[good]);const read=[];await restored.recoverLastTask([root],pointer,async file=>{read.push(file);return{path:file,finished:true};});assert.deepEqual(read,[good]);assert.equal(await fs.readFile(bad,'utf8'),'broken');await restored.remember(bad);assert.equal(restored.isIgnored(bad),true);await restored.remember(bad,true);assert.equal(restored.isIgnored(bad),false);}finally{await fs.rm(root,{recursive:true,force:true});}});

test('扫描输出目录不限层级，跳过缓存与系统目录',async()=>{const{scanLibraryRoots}=require('../dist-electron/electron/library');const root=await fs.mkdtemp(path.join(os.tmpdir(),'ahc-scan-'));try{for(const file of ['a/b/c/d/e/深层.mp4','分类/高光/clip.mkv','validation/app-cache/x.mp4','node_modules/y.mp4','.hidden/z.mp4','任务/task.json','任务/readme.txt']){await fs.mkdir(path.dirname(path.join(root,file)),{recursive:true});await fs.writeFile(path.join(root,file),'x');}const scan=await scanLibraryRoots([root,root]);assert.deepEqual(scan.videos.map(video=>path.relative(root,video.path).replaceAll('\\','/')).sort(),['a/b/c/d/e/深层.mp4','分类/高光/clip.mkv']);assert.equal(scan.tasks.length,1);assert.equal(scan.truncated,false);}finally{await fs.rm(root,{recursive:true,force:true});}});

test('只认领一对一的同一文件：大小加时间、大小加文件名、唯一大小需带时长',()=>{const{matchMovedClips}=require('../dist-electron/electron/library');
 const video=(file,size,mtimeMs)=>({path:path.resolve(file),size,mtimeMs});
 const moves=matchMovedClips([
  {recorded:path.resolve('old/a.mp4'),size:100,mtimeMs:1000},
  {recorded:path.resolve('old/b.mp4'),size:200,mtimeMs:5000},
  {recorded:path.resolve('old/c.mp4'),size:300,duration:12},
  {recorded:path.resolve('old/d.mp4'),size:400},
  {recorded:path.resolve('old/e.mp4'),size:500,mtimeMs:1},{recorded:path.resolve('old/f.mp4'),size:500,mtimeMs:1},
 ],[video('new/a-renamed.mp4',100,1500),video('new/sub/b.mp4',200,99999),video('new/other.mp4',200,99999),video('new/x.mp4',300,7),video('new/y.mp4',400,7),video('new/e.mp4',500,1)]);
 assert.deepEqual(moves.map(move=>[path.basename(move.from),path.basename(move.to),move.basis]),[['a.mp4','a-renamed.mp4','size_mtime'],['b.mp4','b.mp4','size_name'],['c.mp4','x.mp4','size_unique']]);
 assert.equal(moves[2].duration,12);
});

test('确认过的移动成片可以不在原视频目录，未登记的仍拒绝',()=>{const{isRecordedVideo}=require('../dist-electron/electron/taskStorage');
 const old=path.resolve('out/任务'),moved=path.resolve('elsewhere/整理/clip.mp4'),stray=path.resolve('elsewhere/other.mp4');
 const task={version:2},item={video_directory:old,record:{outputs:[moved,path.join(old,'b.mp4')],relocated_outputs:[moved]}};
 assert.equal(isRecordedVideo(task,item,moved),true);assert.equal(isRecordedVideo(task,item,path.join(old,'b.mp4')),true);
 assert.equal(isRecordedVideo(task,item,stray),false);assert.equal(isRecordedVideo(task,{...item,record:{outputs:[moved]}},moved),false);
});
