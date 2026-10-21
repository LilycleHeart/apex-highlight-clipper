const {test}=require('node:test');const assert=require('node:assert/strict');
const {defaults}=require('../dist-electron/src/shared');
const {safeOptions}=require('../dist-electron/electron/protocol');
const {normalizePerformance,resolvePerformance,selectPerformancePreset,performancePresets,performanceDefaults}=require('../dist-electron/src/performanceOptions');

test('presets persist, roundtrip, reset and keep recognition rules',()=>{
 for(const preset of ['low','balanced','high']){
  const result=safeOptions({...defaults,...selectPerformancePreset(defaults,preset)});
  for(const [key,value] of Object.entries(performancePresets[preset]))assert.equal(result[key],value);
  assert.deepEqual(safeOptions(JSON.parse(JSON.stringify(result))),result);
  assert.equal(result.fps,defaults.fps);assert.equal(result.gap,defaults.gap);
 }
 assert.deepEqual(normalizePerformance({}),performanceDefaults);
 assert.deepEqual(normalizePerformance({backend:'invalid',performance_preset:'invalid',cpu_workers:0,decode_threads:999,frame_cache_mb:NaN,gpu_load:'bad'}),performanceDefaults);
});
test('custom settings and legacy throttle survive; invalid IPC values are rejected',()=>{
 const options={...defaults,performance_preset:'custom',backend:'cpu',cpu_workers:2,decode_threads:4,frame_cache_mb:16,gpu_load:'balanced'};
 assert.deepEqual(safeOptions(JSON.parse(JSON.stringify(options))),options);
 assert.equal(normalizePerformance({backend:'dml',gpu_load:'low'}).performance_preset,'custom');
 assert.equal(normalizePerformance({backend:'dml',gpu_load:'low'}).gpu_load,'low');
 for(const [key,values] of Object.entries({cpu_workers:[0,1025,1.5,true],decode_threads:[0,5,NaN],frame_cache_mb:[15,129,'64']}))for(const value of values)assert.throws(()=>safeOptions({...options,[key]:value}));
});
test('launch snapshot resolves auto, caps by CPU budget and ignores later preference changes',()=>{
 const options={...defaults};const active=resolvePerformance(options,true,16);
 assert.equal(active.backend,'dml');assert.equal(active.cpu_workers,3);
 Object.assign(options,selectPerformancePreset(options,'low'),{backend:'cpu'});
 assert.equal(active.backend,'dml');assert.equal(active.cpu_workers,3);assert.equal(active.frame_cache_mb,64);
 assert.equal(resolvePerformance(defaults,false,16).backend,'cpu');assert.equal(resolvePerformance(defaults,false,16).cpu_workers,3);
 assert.equal(resolvePerformance(defaults,true,4).cpu_workers,3);
 assert.throws(()=>resolvePerformance({...defaults,backend:'dml'},false,16));
});
test('CUDA selection requires healthy runtime and never changes automatic device policy',()=>{
 const selected={...defaults,backend:'cuda',performance_preset:'custom',cpu_workers:16};
 assert.equal(safeOptions(selected).backend,'cuda');
 assert.equal(normalizePerformance(JSON.parse(JSON.stringify(selected)),true).backend,'cuda');
 assert.throws(()=>resolvePerformance(selected,true,16,false),/CUDA/);
 const active=resolvePerformance(selected,false,16,true);
 assert.equal(active.backend,'cuda');assert.equal(active.cpu_workers,16);
 assert.equal(resolvePerformance(defaults,true,16,true).backend,'dml');
 assert.equal(resolvePerformance(defaults,false,16,true).backend,'cpu');
});
