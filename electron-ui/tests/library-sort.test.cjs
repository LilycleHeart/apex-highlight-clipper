const {test}=require('node:test');const assert=require('node:assert/strict');const{compareObserved}=require('../dist-electron/src/librarySort');
test('伤害/击杀按观察值排序，未知始终置后且不冒充零',()=>{const values=[null,0,200,undefined,100,NaN];assert.deepEqual([...values].sort((a,b)=>compareObserved(a,b)).slice(0,3),[200,100,0]);assert.deepEqual([...values].sort((a,b)=>compareObserved(a,b,false)).slice(0,3),[0,100,200]);assert.equal(compareObserved(null,undefined),0);});
test('零、已确认下限与同值保持正确次序，不改原对象或计数',()=>{const rows=[{id:'lower',kills:1,partial:true},{id:'zero',kills:0},{id:'exact',kills:2},{id:'same',kills:1}];const ordered=[...rows].sort((a,b)=>compareObserved(a.kills,b.kills));assert.deepEqual(ordered.map(r=>r.id),['exact','lower','same','zero']);assert.equal(rows[0].partial,true);assert.equal(rows[0].kills,1);assert.equal(rows[0].id,'lower');});

const{groupRecordingDays,recordingDay}=require('../dist-electron/src/clipTimeline');
const{compareLibraryClips}=require('../dist-electron/src/librarySort');
const{matchesLibraryMetadata,detailFilterPatch,dateFilterLabel}=require('../dist-electron/src/libraryFilters');
test('详情筛选匹配本人账号别名、队友、英雄及段位，不串同名原录像',()=>{
 const clip={name:'clip',source:'Replay.mp4',recordedAt:'2026-10-12T12:30:00',weapons:['R301'],accountName:'Alpha',accountAliases:['OldAlpha'],teammates:[{name:'[TAG] Teammate'}],hero:{id:'loba'},rank:{tier:'diamond',division:'II'}};
 const matches=filters=>matchesLibraryMetadata(clip,'D:/one/Replay.mp4',filters);
 assert.equal(matches({account:'OldAlpha',teammate:'Teammate',hero:'loba',rank:'diamond',weapon:'R301'}),true);
 assert.equal(matches({teammate:'Other'}),false);assert.equal(matches({rank:'platinum'}),false);
 assert.equal(matches({rank:'diamond',rankDivision:'II'}),true);assert.equal(matches({rank:'diamond',rankDivision:'I'}),false);
 assert.equal(matches({source:'D:/one/Replay.mp4'}),true);assert.equal(matches({source:'D:/two/Replay.mp4'}),false);
 assert.deepEqual(detailFilterPatch({field:'rank',value:'diamond',label:'钻石'}),{rank:'diamond',rankDivision:''});
});
test('年月日筛选按各自范围匹配，未识别日期保持独立',()=>{
 const clip={name:'clip',recordedAt:'2026-10-12T12:30:00',weapons:[]};
 for(const date of ['2026','2026-10','2026-10-12'])assert.equal(matchesLibraryMetadata(clip,'unknown',{date}),true);
 for(const date of ['2025','2026-11','2026-10-13','20260','unknown'])assert.equal(matchesLibraryMetadata(clip,'unknown',{date}),false);
 assert.equal(matchesLibraryMetadata({name:'clip',weapons:[]},'unknown',{date:'unknown'}),true);
 assert.equal(dateFilterLabel('2026'),'2026年');assert.equal(dateFilterLabel('2026-10'),'2026年10月');assert.equal(dateFilterLabel('2026-10-12'),'2026年10月12日');
});
test('统计排序跨日期按数值优先，方向按钮也控制录像和整理时间',()=>{
 const rows=[{name:'a',damage:100,kills:3,start:0,recordedAt:'2026-10-12T10:00:00',exportedAt:'2026-10-13T12:00:00'},{name:'b',damage:500,kills:1,start:0,recordedAt:'2026-10-10T10:00:00',exportedAt:'2026-10-14T12:00:00'},{name:'c',damage:null,kills:null,start:0}];
 const order=(sort,descending)=>[...rows].sort((a,b)=>compareLibraryClips(a,b,sort,descending)).map(row=>row.name);
 assert.deepEqual(order('damage',true),['b','a','c']);assert.deepEqual(order('damage',false),['a','b','c']);assert.deepEqual(order('kills',true),['a','b','c']);
 assert.deepEqual(order('recorded',true),['a','b','c']);assert.deepEqual(order('recorded',false),['b','a','c']);assert.deepEqual(order('recent',true),['b','a','c']);assert.deepEqual(order('recent',false),['a','b','c']);
});
test('日期分组不重复，最近整理保留组顺序，时间排序与未知日期正确',()=>{const item=(day,id)=>({clip:{path:id,recordedAt:day,name:id}}),items=[item('2026-10-10T09:00','a'),item('2026-10-11T09:00','b'),item('2026-10-10T08:00','c'),item(null,'unknown')];const groups=groupRecordingDays(items);assert.deepEqual(groups.map(g=>[g.day,g.items.length]),[['2026-10-10',2],['2026-10-11',1],['',1]]);assert.deepEqual(groupRecordingDays(items,'recorded-newest').map(g=>g.day),['2026-10-11','2026-10-10','']);assert.deepEqual(groupRecordingDays(items,'recorded-oldest').map(g=>g.day),['2026-10-10','2026-10-11','']);assert.equal(recordingDay({name:'Apex Legends_10-08-2026_18-40-10-170.mp4'}),'2026-10-08');assert.equal(recordingDay({recordedAt:'2026-02-30',name:'unknown'}),'');});
