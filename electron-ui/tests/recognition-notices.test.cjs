const {test}=require('node:test');
const assert=require('node:assert/strict');
const {algorithmNoticeKey}=require('../dist-electron/src/algorithmStatus');

test('忽略签名不随片段顺序、进度或旧结果的保存时间变化',()=>{
 const fields=[{field:'hero',status:'old',currentVersion:'v2',currentSignature:'hero-v2'},{field:'rank',status:'old',currentVersion:'v3',currentSignature:'rank-v3'}];
 const before=algorithmNoticeKey([{file:'a',fields},{file:'b',fields}]);
 const after=algorithmNoticeKey([{file:'b',fields:[...fields].reverse().map(field=>({...field,status:'current',updatedAt:'later'}))}]);
 assert.equal(before,after);
});
test('同一版本号的模型或规则签名更新仍能重新提示',()=>{
 const clip=signature=>[{file:'a',fields:[{field:'hero',status:'old',currentVersion:'v2',currentSignature:signature}]}];
 assert.notEqual(algorithmNoticeKey(clip('model-a')),algorithmNoticeKey(clip('model-b')));
});
