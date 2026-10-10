const{test}=require('node:test');const assert=require('node:assert/strict');
const{clipStatistics}=require('../dist-electron/src/clipStats');
test('读取实际 HUD 增量和已确认提示，助攻提示下限不伪装成全段统计',()=>{
 const clip={segment:{start:10,end:40,requested_start:12,requested_end:35},summary:{kills:0,damage:145,weapons:['死敌']}};
 const e={kind:'assist',time:20,ownership:'self',text:'助攻 消灭 玩家'};
 const data=clipStatistics(clip,[{start:12,end:35,rank:{tier:'diamond',name:'钻石',division:'II'},own_result_filter:{events:[e,e,{kind:'knock',time:50,ownership:'self'},{kind:'knock',time:24,ownership:'enemy'}]}}]);
 assert.equal(data.kills,0);assert.equal(data.damage,145);assert.equal(data.assists,1);assert.equal(data.knockdowns,null);assert.equal(data.outcomeCountsPartial,true);assert.equal(data.evidence.length,1);assert.equal(data.rank.division,'II');
});
test('旧成片没有战果与段位数据时保持未知，不将未识别写成0',()=>{
 const data=clipStatistics({segment:{start:0,end:10},summary:{kills:null,damage:null,weapons:['未知枪']}});
 assert.equal(data.assists,null);assert.equal(data.knockdowns,null);assert.equal(data.rank,null);assert.equal(data.kills,null);
});
test('跨段合并遇到不同段位，不展示其中一个当作整段段位',()=>{
 const data=clipStatistics({segment:{start:0,end:20}},[{start:0,end:10,rank:{tier:'gold',division:'II'}},{start:10,end:20,rank:{tier:'diamond',division:'II'}}]);assert.equal(data.rank,null);
});
test('完整统计显示真实2助攻、3击杀，字段的不确定性互不传染',()=>{
 const value=clipStatistics({segment:{start:0,end:10},summary:{statistics_version:'v4',kills:3,assists:2,knockdowns:null,statistics_partial:{kills:false,assists:false,knockdowns:true,damage:true}},recognition:{outcome_evidence:[]}});
 assert.equal(value.assists,2);assert.equal(value.kills,3);assert.equal(value.knockdowns,null);assert.equal(value.statisticsPartial.assists,false);
});
