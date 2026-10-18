const{test}=require('node:test');const assert=require('node:assert/strict');const{normalizeTeammateExclusions,changeTeammateExclusion,excludedTeammateKey}=require('../dist-electron/src/teammateExclusions');
test('非好友偏好按队友键去重和恢复，过滤损坏设置且不修改输入',()=>{
 assert.deepEqual(normalizeTeammateExclusions(['[ABC] Stranger','STRANGER','伙伴',null,'bad\0name','']),['Stranger','伙伴']);assert.deepEqual(normalizeTeammateExclusions({}),[]);
 const original=['Stranger'],added=changeTeammateExclusion(original,'[TAG] Other',true);assert.deepEqual(original,['Stranger']);assert.deepEqual(added,['Stranger','Other']);assert.equal(changeTeammateExclusion(added,'STRANGER',true),added);assert.deepEqual(changeTeammateExclusion(added,'[TAG] stranger',false),['Other']);assert.equal(excludedTeammateKey('!!!'),'!!!');assert.throws(()=>changeTeammateExclusion([],{},true),/无效/);
});
