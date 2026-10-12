const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {ProcessingTimes,historicProcessingSeconds}=require('../dist-electron/electron/processingTimes');
const {eventReducer,initial,processingClock}=require('../dist-electron/src/state');

test('processing time excludes pause and cache skips, survives restart, and is separate per task/source',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'apex-processing-time-'));let now=0;const ledger=path.join(root,'times.json'),events=[];
 const clock=new ProcessingTimes(ledger,(source,seconds)=>events.push({source,seconds}),error=>{throw error;},()=>now);
 try{
  await clock.load();clock.begin('task-a','source-a');now=6500;clock.tick();assert.equal(clock.seconds('task-a','source-a'),6.5);
  clock.finish();now=100000;assert.equal(clock.seconds('task-a','source-a'),6.5);
  clock.begin('task-a','source-a');now+=2000;assert.equal(clock.finish(),8.5);await clock.flush();
  const restored=new ProcessingTimes(ledger,()=>{},()=>{},()=>now);await restored.load();assert.equal(restored.seconds('task-a','source-a'),8.5);
  restored.begin('task-a','source-a');now+=1000;assert.equal(restored.finish(true),8.5);
  assert.equal(restored.seconds('task-b','source-a'),undefined);assert.equal(restored.seconds('task-a','source-b'),undefined);await restored.flush();
  assert.ok(events.length>=3);assert.equal(historicProcessingSeconds({record:{stage_seconds:{probe:1,scan:4,bad:null}}}),5);
 }finally{clock.finish();await clock.flush();await fs.rm(root,{recursive:true,force:true});}
});

test('queue timing updates only its file without changing progress and result keeps the final value',()=>{
 let model={...initial,progress:40,files:[{path:'source-a',status:'running'},{path:'source-b',status:'pending'}]};
 model=eventReducer(model,{type:'file-timing',source:'source-a',processing_seconds:3});assert.equal(model.progress,40);assert.equal(model.files[0].processingSeconds,3);assert.equal(model.files[1].processingSeconds,undefined);
 model=eventReducer(model,{type:'result',source:'source-a',processing_seconds:4.5,result:{source:'source-a',clips:[]}});assert.equal(model.files[0].status,'complete');assert.equal(model.files[0].processingSeconds,4.5);
 assert.equal(processingClock(3661),'1小时1分01秒');assert.equal(processingClock(undefined),'—');
});
