const{test}=require('node:test');const assert=require('node:assert/strict');
const{clipStatistics}=require('../dist-electron/src/clipStats');
const{applyStatisticsCorrection,cleanTargetName,importedStatisticsPartial}=require('../dist-electron/src/clipStats');

test('片尾遮挡的已有数字保留下限，不把较早末值冒充当前本局总数',()=>{
 const clip={segment:{start:0,end:20},summary:{damage:196,statistics_partial:{damage:false}}};
 const endpoint={native_view_version:'self-hud-view-v3',native_numeric_method:'numeric-three-model-v3',baseline:{damage:2088},last_hud:{damage:2284,kills:5},baseline_frames:[.1,.2].map(native_time=>({native_time,native_verified:true,damage:2088})),end_frames:[16.5,16.6].map(native_time=>({native_time,native_verified:true,damage:2284,kills:5}))};
 endpoint.end_frames.push({native_time:16.7,native_verified:true,kills:5});
 const fix={start:0,end:20,counts:{damage:196},partial:{damage:false},native_repaired_fields:['damage'],endpoint};
 const corrected=applyStatisticsCorrection(clip,fix,'fixture');
 assert.equal(corrected.summary.damage,196);assert.equal(corrected.summary.statistics_partial.damage,true);
 assert.equal(fix.partial.damage,false);assert.equal(clip.summary.statistics_partial.damage,false);
 assert.deepEqual(clipStatistics(corrected).roundTotals,{kills:5,damage:null});
});

test('敌人昵称的词间空格和末尾省略号保留',()=>{
 assert.equal(cleanTargetName('KNOCKED DOWN ALPHA BETA... +150'),'ALPHA BETA...');
 assert.equal(cleanTargetName('PLAYER.'),'PLAYER.');
});

test('方块字形必须有两张不同原生画面的识别证据，不能放行 OCR 占位符',()=>{
 const {outcomeTarget}=require('../dist-electron/src/clipStats');
 const event={target_text:'□测试',target_confidence:.97,text_confidence:.4,target_method:'two_frame_native_name_consensus',native_name_status:'confirmed',target_shape_evidence:[1,1.04].map(time=>({time,score:.9,box:[2,18,9,9]}))};
 assert.equal(outcomeTarget(event),'□测试');assert.equal(cleanTargetName('□测试'),undefined);
 assert.equal(outcomeTarget({...event,target_shape_evidence:[]}),undefined);
 assert.equal(outcomeTarget({...event,target_shape_evidence:[event.target_shape_evidence[0],event.target_shape_evidence[0]]}),undefined);
 assert.equal(outcomeTarget({...event,native_name_status:'unconfirmed'}),undefined);
});

test('首帧未知仍可展示双帧确认的本局末值，旧观战末值不能混入',()=>{
 const clip={segment:{start:0,end:20},summary:{damage:2076},recognition:{statistics:{endpoint:{last_hud:{damage:1088,kills:5}}}}};
 assert.equal(clipStatistics(clip).roundTotals,undefined);
 const endpoint={native_view_version:'self-hud-view-v3',native_numeric_method:'numeric-three-model-v3',baseline:{damage:null},last_hud:{damage:868,kills:1},end_frames:[16,16.1].map(native_time=>({native_time,native_verified:true,damage:868,kills:1}))};
 const fix={start:0,end:20,repair_fields:['statistics'],counter_verification_pending:['damage'],counts:{damage:2076},partial:{damage:true},endpoint};
 const corrected=applyStatisticsCorrection(clip,fix,'v13');assert.equal(corrected.summary.damage,null);assert.equal(clip.summary.damage,2076);assert.equal(fix.counts.damage,2076);
 assert.deepEqual(clipStatistics(corrected).roundTotals,{damage:868,kills:1});
 const contradicted=structuredClone(corrected);contradicted.recognition.statistics.endpoint.last_hud.damage=1088;
 assert.deepEqual(clipStatistics(contradicted).roundTotals,{damage:null,kills:1});
 // 原片已删：复核沿用导出时的完整统计，只显示为已确认下限
 const kept=applyStatisticsCorrection(clip,{...fix,source_lower_bound_fields:['damage']},'v13');
 assert.equal(kept.summary.damage,2076);assert.equal(kept.summary.statistics_partial.damage,true);
});

test('非空旧数值仅能由匹配区间且两端双帧原生证据的修复覆盖',()=>{
 const clip={segment:{start:0,end:20},summary:{damage:2076,assists:94,statistics_partial:{damage:false,assists:false}}};
 const fix={start:0,end:20,counts:{damage:196,assists:4},partial:{damage:false,assists:false},native_repaired_fields:['damage'],endpoint:{native_view_version:'self-hud-view-v3',native_numeric_method:'numeric-three-model-v3',baseline:{damage:2088},last_hud:{damage:2284},baseline_frames:[.1,.2].map(native_time=>({native_time,native_verified:true,damage:2088})),end_frames:[16.5,16.6].map(native_time=>({native_time,native_verified:true,damage:2284}))}};
 const corrected=applyStatisticsCorrection(clip,fix,'v9');assert.equal(corrected.summary.damage,196);assert.equal(corrected.summary.assists,94);assert.equal(clip.summary.damage,2076);
 const current=structuredClone(fix);current.endpoint.native_numeric_method='numeric-three-model-v4';
 assert.equal(applyStatisticsCorrection(clip,current,'v4-reader').summary.damage,196);
 current.counter_verification_pending=['damage'];current.endpoint.baseline.damage=null;current.counts.damage=null;current.native_repaired_fields=[];
 assert.equal(applyStatisticsCorrection(clip,current,'v4-reader').summary.damage,null);
 const staleView=structuredClone(fix);delete staleView.endpoint.native_view_version;assert.equal(applyStatisticsCorrection(clip,staleView,'v9').summary.damage,2076);assert.equal(applyStatisticsCorrection({...clip,summary:{}},staleView,'v9').summary.damage,undefined);
 const preview=structuredClone(fix);preview.endpoint.end_frames.forEach(row=>row.native_verified=false);assert.equal(applyStatisticsCorrection(clip,preview,'v9').summary.damage,2076);
 const duplicate=structuredClone(fix);duplicate.endpoint.end_frames.forEach(row=>row.native_time=16.5);assert.equal(applyStatisticsCorrection(clip,duplicate,'v9').summary.damage,2076);
 assert.equal(applyStatisticsCorrection(clip,{...fix,start:1},'v9'),clip);
 assert.equal(applyStatisticsCorrection(clip,{...fix,counts:{damage:197}},'v9').summary.damage,2076);
 const fromExport=structuredClone(fix),identity={path:'C:\\videos\\clip.mp4',size:123,mtime_ms:123456};
 fromExport.endpoint.native_counter_scope='exported_visible_delta';fromExport.endpoint.exported_video_identity=identity;fromExport.endpoint.export_baseline_fields=['damage'];
 assert.equal(applyStatisticsCorrection(clip,fromExport,'v9'),clip);
 assert.equal(applyStatisticsCorrection(clip,fromExport,'v9',{...identity,size:124}),clip);
 assert.equal(applyStatisticsCorrection(clip,fromExport,'v9',identity).summary.damage,196);
 const lower=structuredClone(fix);lower.partial.damage=true;lower.endpoint.unconfirmed_latest={damage:2300};const bound=applyStatisticsCorrection(clip,lower,'v9');assert.equal(bound.summary.damage,196);assert.equal(bound.summary.statistics_partial.damage,true);
});

test('成片开头只有小队数行时按 0 起算，两帧原生证据与片尾读数都齐才显示',()=>{
 const identity={path:'C:\\videos\\clip.mp4',size:123,mtime_ms:123456};
 const zero=[.31,.81].map(native_time=>({native_time,native_verified:true,kills:0,assists:0,damage:0,zero_evidence:{method:'squads-row-zero-v1'}}));
 const endpoint={native_view_version:'self-hud-view-v3',native_numeric_method:'numeric-three-model-v5',native_counter_scope:'exported_visible_delta',exported_video_identity:identity,
  export_baseline_fields:['kills','assists','damage'],baseline:{kills:0,assists:0,damage:0},last_hud:{kills:2,assists:1,damage:384},unconfirmed_latest:{},
  baseline_frames:zero,end_frames:[24.5,24.75].map(native_time=>({native_time,native_verified:true,kills:2,assists:1,damage:384}))};
 const fix={start:0,end:25,counts:{kills:2,assists:1,damage:384},partial:{kills:false,assists:false,damage:false},native_repaired_fields:['kills','assists','damage'],counter_verification_pending:[],endpoint};
 const clip={segment:{start:0,end:25},summary:{kills:2,damage:384,statistics_partial:{kills:true,damage:true}}};
 const shown=applyStatisticsCorrection(clip,fix,'v15',identity);
 assert.equal(shown.summary.damage,384);assert.equal(shown.summary.statistics_partial.damage,false);
 const single=structuredClone(fix);single.endpoint.baseline_frames=zero.slice(0,1);
 assert.equal(applyStatisticsCorrection(clip,single,'v15',identity).summary.statistics_partial.damage,true);
});

test('导入片段按记录的 partial 显示下限，旧记录没有时保持原样',()=>{
 assert.deepEqual(importedStatisticsPartial({partial:{kills:true,assists:false,knockdowns:true,damage:false}}),{kills:true,assists:false,knockdowns:true,damage:false});
 assert.equal(importedStatisticsPartial({partial:{kills:true}}),undefined);
 assert.equal(importedStatisticsPartial(undefined),undefined);
});

test('原生复核姓名使用新置信度，纯数字账号与动作同形字不会被界面丢弃',()=>{
 const event={kind:'knock',time:2,ownership:'self',target_text:'3213124124325',text_confidence:.4,target_confidence:.95,target_method:'two_frame_native_name_consensus',native_name_status:'confirmed'};
 const value=clipStatistics({segment:{start:0,end:10},summary:{statistics_version:'v9'},recognition:{outcome_evidence:[event]}});
 assert.equal(value.evidence[0].target,'3213124124325');assert.equal(cleanTargetName('撃倒 撃田+150'),'撃田');assert.equal(cleanTargetName('123'),undefined);
});

test('仅更新敌人姓名不改变原有计数或统计完整性',()=>{
 const event={kind:'knock',time:2,ownership:'self',target_text:'old',confirmed:true,text:'擊倒 old'};
 const clip={segment:{start:0,end:10},summary:{damage:2076},recognition:{outcome_evidence:[event]}};
 const fix={start:0,end:10,repair_fields:['opponents'],counts:{damage:196},partial:{damage:false},events:[{...event,target_text:'new',target_confidence:.98,native_name_status:'confirmed',target_method:'two_frame_native_name_consensus'}]};
 const result=applyStatisticsCorrection(clip,fix,'v9');assert.equal(result.summary.damage,2076);assert.equal(result.summary.statistics_version,undefined);assert.equal(result.recognition.outcome_evidence[0].target_text,'new');
});

test('原生重读未确认的姓名保留战果与原始文字，不继续展示旧拼写',()=>{
 const event={kind:'knock',time:2,ownership:'self',target_text:'old_wrong',confirmed:true,text:'擊倒 old_wrong',text_confidence:.99};
 const clip={segment:{start:0,end:10},summary:{damage:100},recognition:{outcome_evidence:[event]}};
 const fix={start:0,end:10,repair_fields:['opponents'],events:[{...event,native_name_status:'unconfirmed',native_name_version:'target-name-v8'}]};
 const corrected=applyStatisticsCorrection(clip,fix,'v10'),display=clipStatistics(corrected);
 assert.equal(display.evidence.length,1);assert.equal(display.evidence[0].target,undefined);assert.equal(display.evidence[0].time,2);assert.equal(display.damage,100);assert.equal(corrected.recognition.outcome_evidence[0].target_text,'old_wrong');
});

test('同一帧的两行战果分别更新姓名，旧候选不能盖回原生复核结果',()=>{
 const events=[0,1].map(i=>({kind:'knock',time:2,ownership:'self',text:'擊倒 '+i,target_text:'old'+i,confirmed:true,prefix_box:[100,200+i*30,150,220+i*30]}));
 const clip={segment:{start:0,end:10},summary:{damage:30},recognition:{outcome_evidence:events}};
 const fix={start:0,end:10,repair_fields:['opponents'],events:events.map((e,i)=>({...e,target_text:'new'+i,native_name_status:'confirmed',target_method:'two_frame_native_name_consensus',target_confidence:.99}))};
 const corrected=applyStatisticsCorrection(clip,fix,'v9');const display=clipStatistics(corrected,[{start:0,end:10,own_result_filter:{events}}]);
 assert.deepEqual(display.evidence.map(e=>e.target),['new0','new1']);assert.equal(display.damage,30);
});
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

test('手动重新识别未确认的枪械与段位不回退到旧错误数据',()=>{
 const clip={segment:{start:0,end:10,rank:{tier:'gold'}},summary:{kills:2,damage:123,weapons:['错误旧武器']},recognition:{hud_info:{rank:null,weapons:[],refreshed_fields:['rank','weapons']}}};
 const data=clipStatistics(clip);
 assert.equal(data.rank,null);assert.deepEqual(data.weapons,[]);assert.equal(data.kills,2);assert.equal(data.damage,123);
 delete clip.recognition.hud_info.refreshed_fields;
 const legacy=clipStatistics(clip);assert.equal(legacy.rank.tier,'gold');assert.deepEqual(legacy.weapons,['错误旧武器']);
});
test('跨段合并遇到不同段位，不展示其中一个当作整段段位',()=>{
 const data=clipStatistics({segment:{start:0,end:20}},[{start:0,end:10,rank:{tier:'gold',division:'II'}},{start:10,end:20,rank:{tier:'diamond',division:'II'}}]);assert.equal(data.rank,null);
});
test('完整统计显示真实2助攻、3击杀，字段的不确定性互不传染',()=>{
 const value=clipStatistics({segment:{start:0,end:10},summary:{statistics_version:'v4',kills:3,assists:2,knockdowns:null,statistics_partial:{kills:false,assists:false,knockdowns:true,damage:true}},recognition:{outcome_evidence:[]}});
 assert.equal(value.assists,2);assert.equal(value.kills,3);assert.equal(value.knockdowns,null);assert.equal(value.statisticsPartial.assists,false);
});
test('战果回看贴近实际射击，不重复扣预留时间，同目标延迟击杀保留开火证据',()=>{
 const evidence=[{kind:'knock',time:150,target_text:'LOBA9578',ownership:'self'},{kind:'assist',time:189,target_text:'OTHER',ownership:'self'},{kind:'elimination',time:190,target_text:'LOBA9578',ownership:'self'}];
 const clip={segment:{start:100,end:200},summary:{statistics_version:'fixture',kills:1,damage:1000},recognition:{outcome_evidence:evidence}};
 const data=clipStatistics(clip,[],{parameters:{pre:6},events:[105,110,119,128,139,149,181,185,188].map(time=>({time,kind:'shoot'}))});
 assert.deepEqual(data.evidence.map(e=>e.processStart),[149,185,149]);
 assert.deepEqual(data.evidence.map(e=>e.time),[150,189,190]);assert.equal(data.kills,1);assert.equal(data.damage,1000);
 const old={...clip,recognition:{outcome_evidence:[evidence[0]]}};
 assert.equal(clipStatistics(old,[{start:136,end:155,first_signal:149}]).evidence[0].processStart,149);
 assert.equal(clipStatistics(old).evidence[0].processStart,149);
 assert.equal(clipStatistics({...old,segment:{start:148,end:200}}).evidence[0].processStart,149);
});

test('多个目标的连续交战各自回看过程，不全部跳到整段起点',()=>{
 const evidence=[125,145,165].map((time,i)=>({kind:'elimination',time,target:['ALPHA','BRAVO','CHARLIE'][i],ownership:'self'}));
 const clip={segment:{start:100,end:180},summary:{statistics_version:'fixture'},recognition:{outcome_evidence:evidence}};
 const data=clipStatistics(clip,[],{parameters:{pre:12},events:[110,111,120,121,123,130,131,133,140,141,143,150,151,153,160,161,163].map(time=>({time,kind:'shoot'}))});
 const {clipEvents}=require('../dist-electron/src/eventTimeline');
 assert.deepEqual(data.evidence.map(e=>e.processStart),[120,140,160]);
 assert.deepEqual(clipEvents({start:100,duration:80,evidence:data.evidence}).map(e=>e.seekTime),[18,38,58]);
 const {withProcessStarts}=require('../dist-electron/src/combatPlayback');
 const delayed=withProcessStarts([{kind:'elimination',time:145,target:'B'},{kind:'knock',time:115,target:'B'},{kind:'elimination',time:125,target:'A'}],{start:100,end:180},[],{events:[114,122,140,142].map(time=>({time,kind:'shoot'}))});
 assert.equal(delayed[2].processStart,140);assert.ok(delayed[2].processStart>delayed[1].time);
 assert.equal(delayed[2].processStartBasis,'shoot');
 const missing=withProcessStarts([{kind:'elimination',time:125},{kind:'elimination',time:125.2}],{start:100,end:180});
 assert.ok(missing[1].processStart>missing[0].time);assert.equal(missing[1].processStartBasis,'near_result');
 const late=withProcessStarts([{kind:'elimination',time:125},{kind:'elimination',time:149.5}],{start:100,end:180},[],{events:[{kind:'shoot',time:141.5},{kind:'hit',time:149,before:100,after:150}]});
 assert.equal(late[1].processStart,141.5);assert.equal(late[1].processStartBasis,'shoot');
 assert.equal(clipEvents({start:100,duration:80,evidence:late}).at(-1).seekTime,39.5);
 const close=clipEvents({start:100,duration:30,evidence:[{kind:'elimination',time:101,processStart:100.5,processStartBasis:'shoot'},{kind:'elimination',time:104,processStart:102,processStartBasis:'shoot'}]});
 assert.equal(close[0].seekTime,0);assert.equal(close[1].seekTime,1.001);assert.equal(close[1].processStartBasis,'shoot');
 // Missing firing evidence retains its existing result-near estimate, rather
 // than receiving another two seconds each time the timeline is derived.
 const fallback=clipEvents({start:100,duration:80,evidence:missing});
 assert.equal(fallback[0].seekTime,24);assert.ok(fallback[1].seekTime>fallback[0].clipTime);
});

const completionVersion='native-event-completion-v1';
const completionVideo={path:'C:\\videos\\clip.mp4',size:123,mtime_ms:123456};
function completedCandidate(english=false){
 const kind=english?'assist':'knock',text=english?'ASSIST KNOCKED DOWN ALPHA+100':'擊倒 ALPHA+150';
 const reads=[2,2.16].map(native_pts=>({native_pts,requested_time:native_pts-.005,accepted:true,kind,action:'knock',text,
  box:english?[10,20,300,40]:[10,20,200,40],prefix_confidence:.96,text_confidence:.96,association_target:'alpha',name_accuracy_verified:false,
  own_view:{inactive:false,friend_spectate:false,spectator:false},same_row_fixed_template_score:english?.2:.95,
  prefix_evidence:english?{type:'english_complete_prefix_grammar',ctc_prefix:'ASSIST,KNOCKED DOWN',ctc_prefix_mean_letter_confidence:.94,box:[8,18,150,42],crop_sha256:'ab'.repeat(32)}:
   {type:'same_row_fixed_prefix_template',matches:[{kind,action:'knock',score:.95,box:[10,20,38,40]}]}}));
 return {kind,action:'knock',time:102,confirmed:true,ownership:'self',text:english?'ASSIST KNOCKED DOWN OLD+100':'擊倒 OLD+150',box:[10,20,200,40],target_text:'OLD',text_confidence:.99,
  native_event_version:completionVersion,native_event_original_confirmed:false,native_event_recipe:completionVersion+':'+ '01'.repeat(32),native_event_status:'confirmed',native_event_source:{...completionVideo},native_event_context_bounds:[0,19.9],native_event_evidence:reads,
  native_event_confirmation:english?{type:'english_full_grammar_with_native_prefix_persistence',pts:[2,2.16],pixel_agreement:{score:.97,dx:1,dy:0},min_pixel_persistence:.75,not_an_independent_semantic_vote:true}:{type:'two_native_full_grammar_and_fixed_template_observations',pts:[2,2.16]}};
}
function completionClip(events=[]){
 return {segment:{start:100,end:120},summary:{statistics_version:'prior',kills:3,assists:2,damage:123,knockdowns:0,statistics_partial:{kills:false,assists:false,damage:false,knockdowns:false}},
  recognition:{outcome_evidence:events,hud_info:{account:{name:'SELF'}},statistics:{endpoint:{native_view_version:'self-hud-view-v3',native_numeric_method:'numeric-three-model-v4',last_hud:{kills:3,damage:500},end_frames:[18,18.1].map(native_time=>({native_time,native_verified:true,kills:3,damage:500}))}}}};
}
function completionFix(events,knockdowns=1,partial=false){return {start:100,end:120,repair_fields:['opponents'],event_completion_version:completionVersion,counts:{kills:999,assists:999,damage:999,knockdowns},partial:{knockdowns:partial},events};}

test('新补证事件真实追加并幂等，姓名独立确认且不覆盖HUD数字或端点',()=>{
 const event=completedCandidate(),clip=completionClip(),fix=completionFix([event]);
 const corrected=applyStatisticsCorrection(clip,fix,'completion',completionVideo),data=clipStatistics(corrected);
 assert.equal(data.evidence.length,1);assert.equal(data.evidence[0].time,102);assert.equal(data.evidence[0].target,undefined);assert.equal(data.knockdowns,1);
 assert.deepEqual([data.kills,data.assists,data.damage],[3,2,123]);assert.equal(corrected.summary.statistics_version,'prior');assert.equal(corrected.recognition.statistics,clip.recognition.statistics);assert.equal(corrected.recognition.hud_info,clip.recognition.hud_info);assert.deepEqual(data.roundTotals,{kills:3,damage:500});
 assert.equal(clip.recognition.outcome_evidence.length,0);assert.equal(clip.summary.knockdowns,0);assert.equal(fix.events[0].target_text,'OLD');
 assert.equal(clipStatistics(applyStatisticsCorrection(corrected,fix,'completion',completionVideo)).evidence.length,1);
 const named={...event,target_text:'INDEPENDENT NAME',native_name_status:'confirmed',native_name_version:'target-name-v14',target_method:'two_frame_native_name_consensus',target_confidence:.98,native_name_source:{...completionVideo}};
 assert.equal(clipStatistics(applyStatisticsCorrection(corrected,completionFix([named]),'completion',completionVideo)).evidence[0].target,'INDEPENDENT NAME');
 assert.equal(clipStatistics(applyStatisticsCorrection(corrected,completionFix([{...named,native_name_version:'target-name-v15'}]),'completion',completionVideo)).evidence[0].target,'INDEPENDENT NAME');
 assert.equal(clipStatistics(applyStatisticsCorrection(corrected,completionFix([{...named,native_name_source:{...completionVideo,size:124}}]),'completion',completionVideo)).evidence[0].target,undefined);
 const noClassMetadata=completionFix([event]);delete noClassMetadata.event_completion_version;
 assert.equal(applyStatisticsCorrection(clip,noClassMetadata,'completion',completionVideo).summary.knockdowns,0);
 const wrongDerived=applyStatisticsCorrection(clip,completionFix([event],999),'completion',completionVideo);
 assert.equal(wrongDerived.summary.knockdowns,0);assert.equal(clipStatistics(wrongDerived).evidence.length,1);
 const legacy=completionClip();delete legacy.summary.statistics_version;
 const unknown=applyStatisticsCorrection(legacy,completionFix([event],null,true),'completion',completionVideo);
 assert.equal(clipStatistics(unknown).knockdowns,null);assert.equal(unknown.summary.statistics_partial.knockdowns,true);assert.equal(unknown.summary.assists,2);
 const english=completedCandidate(true),shown=clipStatistics(applyStatisticsCorrection(clip,completionFix([english],0),'completion',completionVideo));
 assert.equal(shown.evidence[0].kind,'assist');assert.equal(shown.evidence[0].target,undefined);
});

test('重复PTS、错误来源及缺乏完整原生分类证据不能追加或改击倒数',()=>{
 const clip=completionClip();
 const mutations=[
  event=>event.native_event_confirmation.pts=[2,2],event=>event.native_event_source.size++,event=>event.native_event_source.path='C:\\videos\\another.mp4',
  event=>event.native_event_original_confirmed=true,event=>event.native_event_recipe='stale',event=>event.native_event_version='unknown',
  event=>event.native_event_evidence[0].accepted=false,event=>event.native_event_evidence[0].own_view.spectator=true,
  event=>delete event.native_event_evidence[0].own_view.inactive,event=>event.native_event_context_bounds=[0,2.1],
  event=>event.native_event_evidence[0].requested_time=1.7,event=>event.native_event_evidence[0].association_target='another',
  event=>event.native_event_evidence[0].prefix_confidence=.60,event=>event.native_event_evidence[0].prefix_evidence.matches[0].box=[80,20,108,40],
  event=>event.native_event_evidence[0].text='Announcer: KNOCKED DOWN ALPHA+150',event=>event.native_event_evidence[0].text='I WAS KNOCKED DOWN ALPHA',
 ];
 for(const mutate of mutations){const event=completedCandidate();mutate(event);assert.equal(applyStatisticsCorrection(clip,completionFix([event]),'completion',completionVideo),clip);}
 assert.equal(applyStatisticsCorrection(clip,completionFix([completedCandidate()]),'completion'),clip);
 assert.equal(applyStatisticsCorrection(clip,completionFix([completedCandidate()]),'completion',{}),clip);
 for(const mutate of [event=>event.native_event_confirmation.pixel_agreement.score=.2,event=>event.native_event_evidence[0].prefix_confidence=.89,event=>event.native_event_evidence[0].prefix_evidence.ctc_prefix='ASSIST ELIMINATED']){
  const event=completedCandidate(true);mutate(event);assert.equal(applyStatisticsCorrection(clip,completionFix([event]),'completion',completionVideo),clip);
 }
});

test('强制失败只撤销同身份自动补证，普通确认和legacy事件保留且旧候选不回灌',()=>{
 const ordinary={kind:'knock',action:'knock',time:104,confirmed:true,ownership:'self',text:'擊倒 STABLE+150',box:[20,20,150,40],target_text:'STABLE',text_confidence:.95};
 const auto=completedCandidate(),base=completionClip([ordinary]),seed=applyStatisticsCorrection(base,completionFix([auto],2),'completion',completionVideo);
 const failed={...structuredClone(auto),confirmed:false,native_event_status:'unconfirmed',native_event_recipe:completionVersion+':'+ '02'.repeat(32),native_event_evidence:[]};delete failed.native_event_confirmation;
 const forgedOrdinary={...failed,...ordinary,confirmed:false,native_event_status:'unconfirmed'};
 const revoked=applyStatisticsCorrection(seed,completionFix([failed,forgedOrdinary],1,true),'completion',completionVideo);
 assert.equal(revoked.recognition.outcome_evidence.find(event=>event.time===102).confirmed,false);assert.deepEqual(revoked.recognition.outcome_evidence.find(event=>event.time===104),ordinary);
 assert.deepEqual(clipStatistics(revoked).evidence.map(event=>event.time),[104]);assert.equal(revoked.summary.knockdowns,1);assert.equal(revoked.summary.statistics_partial.knockdowns,true);
 assert.equal(revoked.recognition.statistics,base.recognition.statistics);assert.deepEqual([revoked.summary.kills,revoked.summary.assists,revoked.summary.damage],[3,2,123]);
 const wrongSource={...failed,native_event_source:{...completionVideo,size:124}};
 assert.equal(applyStatisticsCorrection(seed,completionFix([wrongSource],0),'completion',completionVideo),seed);
 const noSafeContext={...failed,native_event_context_bounds:[5,4]};
 assert.equal(clipStatistics(applyStatisticsCorrection(seed,completionFix([noSafeContext],1,true),'completion',completionVideo)).evidence.length,1);
 assert.equal(applyStatisticsCorrection(base,completionFix([forgedOrdinary],0),'completion',completionVideo),base);
 const mismatched={...failed,text:'擊倒 another'};assert.equal(applyStatisticsCorrection(seed,completionFix([mismatched],0),'completion',completionVideo),seed);
 const legacy={...revoked,summary:{...revoked.summary}};delete legacy.summary.statistics_version;
 const candidates=[{start:100,end:120,own_result_filter:{events:[auto,{kind:'assist',time:106,ownership:'self',text:'助攻，擊倒 LEGACY'},{kind:'knock',time:108,ownership:'self',confirmed:false,text:'擊倒 UNCONFIRMED'}]}}];
 assert.deepEqual(clipStatistics(legacy,candidates).evidence.map(event=>event.time),[104,106]);
});

test('中心本人已确认事件可提高下限，去重且不信任裸修正数字或经验',()=>{
 const event=(kind,time,extra={})=>({kind,action:kind,time,confirmed:true,ownership:'self',text:(kind==='assist'?'助攻，消滅 ':kind==='knock'?'擊倒 ':'已消滅 ')+'TARGET'+time+'+150',...extra});
 const kills=[event('elimination',102),event('elimination',104)],knocks=[event('knock',101),event('knock',103)];
 const assists=[event('assist',106),event('assist',108,{action:'elimination',native_action_status:'confirmed'})];
 const ignored=[event('assist',109,{text:'助攻，擊倒 PLAYER+100',action:'knock'}),event('assist',110,{action:'elimination',native_action_status:'unconfirmed'}),event('elimination',111,{confirmed:false}),event('elimination',112,{confirmed:undefined}),event('elimination',113,{ownership:'other'}),event('elimination',121)];
 const clip={segment:{start:100,end:120},summary:{kills:1,assists:1,knockdowns:1,damage:50,statistics_partial:{kills:true,assists:true,knockdowns:true,damage:true}},recognition:{outcome_evidence:[...kills,kills[0],...knocks,...assists,...ignored]}};
 const fix={start:100,end:120,repair_fields:['statistics'],counts:{kills:999,assists:999,knockdowns:999,damage:999},partial:{kills:false,assists:false,knockdowns:false,damage:false}};
 const changed=applyStatisticsCorrection(clip,fix,'center-v1');
 assert.deepEqual([changed.summary.kills,changed.summary.assists,changed.summary.knockdowns,changed.summary.damage],[2,2,2,50]);
 assert.deepEqual(changed.summary.statistics_partial,{kills:true,assists:true,knockdowns:true,damage:true});assert.match(changed.summary.statistics_basis,/中心/);
 assert.deepEqual([clip.summary.kills,clip.summary.assists,clip.summary.knockdowns],[1,1,1]);assert.equal(fix.counts.damage,999);
 const complete={...clip,summary:{...clip.summary,statistics_partial:{kills:false,assists:false,knockdowns:false,damage:false}}};
 assert.equal(applyStatisticsCorrection(complete,fix,'center-v1'),complete);
 const empty={segment:clip.segment,summary:{kills:null,damage:null},recognition:{outcome_evidence:[]}};
 assert.equal(applyStatisticsCorrection(empty,fix,'center-v1'),empty);
 const namesOnly={...fix,repair_fields:['opponents'],events:[]};assert.equal(applyStatisticsCorrection(clip,namesOnly,'center-v1'),clip);
 const pendingNative={...completedCandidate(),native_event_source:{...completionVideo,size:999}};
 const unverified={...empty,recognition:{outcome_evidence:[pendingNative]}};
 assert.equal(applyStatisticsCorrection(unverified,fix,'center-v1',completionVideo),unverified);
 const inflated={...clip,summary:{...clip.summary,kills:3,assists:3,knockdowns:3},recognition:{...clip.recognition,statistics:{endpoint:{baseline:{kills:null,assists:null},last_hud:{kills:5,assists:5}}}}};
 const recompute={...fix,center_recomputed_fields:['kills','assists','knockdowns']};
 const lowered=applyStatisticsCorrection(inflated,recompute,'center-v2');
 assert.deepEqual([lowered.summary.kills,lowered.summary.assists,lowered.summary.knockdowns],[2,2,2]);assert.equal(lowered.summary.damage,50);
 assert.deepEqual(lowered.summary.statistics_partial,{kills:true,assists:true,knockdowns:true,damage:true});assert.equal(inflated.summary.kills,3);
 assert.equal(applyStatisticsCorrection(inflated,fix,'center-v2'),inflated);
 const revoked={...inflated,recognition:{...inflated.recognition,outcome_evidence:inflated.recognition.outcome_evidence.map(e=>({...e,confirmed:false}))}};
 const cleared=applyStatisticsCorrection(revoked,recompute,'center-v2');
 assert.deepEqual([cleared.summary.kills,cleared.summary.assists,cleared.summary.knockdowns],[null,null,null]);assert.equal(cleared.summary.statistics_partial.kills,true);
 const completeInflated={...inflated,summary:{...inflated.summary,statistics_partial:{kills:false,assists:false,knockdowns:false,damage:true}}};
 assert.equal(applyStatisticsCorrection(completeInflated,recompute,'center-v2'),completeInflated);
 const hudBound={...inflated,recognition:{...inflated.recognition,statistics:{endpoint:{baseline:{kills:0,assists:0},last_hud:{kills:3,assists:3}}}}};
 const protectedHud=applyStatisticsCorrection(hudBound,recompute,'center-v2');
 assert.deepEqual([protectedHud.summary.kills,protectedHud.summary.assists,protectedHud.summary.knockdowns],[3,3,2]);
 const wrongSource={...recompute,endpoint:{native_counter_scope:'exported_visible_delta',exported_video_identity:{...completionVideo,size:999}}};
 assert.equal(applyStatisticsCorrection(inflated,wrongSource,'center-v2',completionVideo),inflated);
 const native={...recompute,native_repaired_fields:['kills'],partial:{kills:true},counts:{kills:3},endpoint:{native_view_version:'self-hud-view-v3',native_numeric_method:'numeric-three-model-v4',baseline:{kills:2},last_hud:{kills:5},baseline_frames:[1,1.1].map(native_time=>({native_time,native_verified:true,kills:2})),end_frames:[10,10.1].map(native_time=>({native_time,native_verified:true,kills:5}))}};
 assert.equal(applyStatisticsCorrection(inflated,native,'center-v2').summary.kills,3);
});

function weaponContextFixture(scope='nearby_firing'){
 const weapon={id:'nemesis',name:'死敌'},row=(actual_pts,ammo=24)=>({actual_pts,slot:0,weapon:{...weapon},confidence:.96,name_view_agreement:2,weapon_icon:Buffer.alloc(336,0xaa).toString('base64'),ammo:{value:ammo,confidence:.99}});
 const event={kind:'knock',action:'knock',time:110,confirmed:true,ownership:'self',text:'擊倒 TARGET+150',prefix_box:[100,200,150,220]};
 const context={version:'event-weapon-context-v1',recipe:'ab'.repeat(32),source:{...completionVideo},event:{kind:'knock',action:'knock',time:110,source_time:10},status:'observed',scope,weapon,kill_attribution:false,label:'伪造的击杀武器归因',evidence:scope==='nearby_firing'?[row(9,24),row(9.5,19),row(10,19),row(10.12,19)]:[row(10),row(10.12)]};
 const clip={segment:{start:100,end:120},output_identity:{path:completionVideo.path,size:completionVideo.size,mtime_ns:completionVideo.mtime_ms*1e6},summary:{statistics_version:'prior',kills:1,damage:50,statistics_partial:{kills:false,damage:false}},recognition:{outcome_evidence:[event],statistics:{unchanged:true}}};
 const fix={start:100,end:120,repair_fields:['event_weapons'],counts:{kills:999,damage:999},events:[{...event,weapon_context:context}]};
 return {clip,fix,event,context};
}

test('v2 武器上下文：0.75 词表分类、图标掩膜同形与战果前持枪可显示，v1 规则不变',()=>{
 const show=(context)=>{const {clip,fix}=weaponContextFixture('held_at_event');fix.events[0].weapon_context=context;return clipStatistics(applyStatisticsCorrection(clip,fix,'weapon-v2',completionVideo),[],{},completionVideo).evidence[0].weaponContext;};
 const base=weaponContextFixture('held_at_event').context;
 const flash=Buffer.alloc(336,0x0f).toString('base64'),mask=Buffer.alloc(336,0x3c).toString('base64');
 const v2={...base,version:'event-weapon-context-v2',evidence:base.evidence.map((row,i)=>({...row,confidence:.75,weapon_icon:i?flash:row.weapon_icon,weapon_icon_mask:mask}))};
 assert.equal(show(v2)?.scope,'held_at_event');
 assert.equal(show({...v2,version:'event-weapon-context-v1'}),undefined);
 assert.equal(show({...v2,evidence:v2.evidence.map(row=>({...row,weapon_icon_mask:undefined}))}),undefined);
 const before={...v2,scope:'held_before_event',evidence:[{...v2.evidence[0],actual_pts:9},{...v2.evidence[1],actual_pts:9.5},{actual_pts:10,slot:0,weapon:null,confidence:.4,name_view_agreement:0}]};
 assert.deepEqual(show(before),{scope:'held_before_event',weapon:'死敌',label:'战果前持枪：死敌'});
 assert.equal(show({...before,version:'event-weapon-context-v1'}),undefined);
 assert.equal(show({...before,evidence:[before.evidence[0],{...before.evidence[1],weapon:{id:'car',name:'CAR'}},before.evidence[2]]}),undefined);
 const hidden=t=>({actual_pts:t,slot:null,highlights:[0,0]}),good=t=>({...v2.evidence[0],actual_pts:t,name_view_agreement:2});
 const near={...v2,scope:'held_near_event',reason:'same_slot_chain_near_event',evidence:[good(5),good(5.5),hidden(9),hidden(10),good(11)]};
 assert.deepEqual(show(near),{scope:'held_near_event',weapon:'死敌',label:'战果前后持枪：死敌'});
 assert.equal(show({...near,evidence:[good(5),good(5.5),{...good(9),slot:1,weapon:{id:'car',name:'CAR'}},hidden(10),good(11)]}),undefined);
 assert.equal(show({...near,evidence:[good(5),{actual_pts:5.2,excluded_view:true},good(5.5),good(11)]}),undefined);
 assert.equal(show({...near,version:'event-weapon-context-v1'}),undefined);
});

test('独立武器修正验证射击或同持枪证据，安全生成标签且不改战绩与事件武器',()=>{
 for(const scope of ['nearby_firing','held_at_event']){
  const {clip,fix}=weaponContextFixture(scope),before=structuredClone(clip),corrected=applyStatisticsCorrection(clip,fix,'weapon-v1',completionVideo);
  assert.deepEqual(corrected.summary,clip.summary);assert.equal(corrected.recognition.statistics,clip.recognition.statistics);assert.deepEqual(clip,before);
  assert.equal(corrected.recognition.outcome_evidence[0].weapon,undefined);
  const shown=clipStatistics(corrected,[],{},completionVideo).evidence[0];
  assert.deepEqual(shown.weaponContext,{scope,weapon:'死敌',label:scope==='nearby_firing'?'战果前射击：死敌':'当时持枪：死敌'});assert.equal(shown.weapon,undefined);
  assert.equal(clipStatistics(corrected).evidence[0].weaponContext,undefined);
  assert.equal(clipStatistics(corrected,[],{},{...completionVideo,size:124}).evidence[0].weaponContext,undefined);
  assert.equal(fix.events[0].weapon_context.label,'伪造的击杀武器归因');
 }
 const {clip,fix}=weaponContextFixture();
 fix.events[0].target_text='UNAUTHORIZED NAME';fix.events[0].native_name_status='confirmed';
 assert.equal(applyStatisticsCorrection(clip,fix,'weapon-v1',completionVideo).recognition.outcome_evidence[0].target_text,undefined);
 const shifted=weaponContextFixture();shifted.clip.metadata={streams:[{codec_type:'video',start_time:'0.02'}]};
 shifted.context.event.source_time+=.02;shifted.context.evidence.forEach(row=>row.actual_pts+=.02);
 assert.equal(clipStatistics(applyStatisticsCorrection(shifted.clip,shifted.fix,'weapon-v1',completionVideo),[],{},completionVideo).evidence[0].weaponContext.scope,'nearby_firing');
});

test('武器上下文拒绝错误来源绑定重复PTS观战换枪与伪造弹药证据',()=>{
 const mutations=[
  c=>c.version='old',c=>c.recipe='stale',c=>c.source.size++,c=>c.source.path='C:\\videos\\other.mp4',c=>c.event.kind='assist',c=>c.event.action='elimination',c=>c.event.time++,c=>c.event.source_time++,
  c=>c.kill_attribution=true,c=>c.status='unknown',c=>c.scope='kill_weapon',c=>c.weapon.name='<script>',
  c=>c.evidence=[c.evidence[0],c.evidence[0]],c=>c.evidence[0].excluded_view=true,c=>c.evidence[0].actual_pts=0,
  c=>c.evidence[0].slot=1,c=>c.evidence[0].confidence=.7,c=>c.evidence[0].name_view_agreement=1,c=>c.evidence[0].weapon_icon=Buffer.alloc(336,0x55).toString('base64'),
  c=>c.evidence.forEach(row=>row.ammo.value=24),c=>c.evidence[1].ammo.value=0,c=>c.evidence[0].ammo.confidence=.5,
 ];
 for(const mutate of mutations){
  const {clip,context}=weaponContextFixture();mutate(context);clip.recognition.outcome_evidence[0].weapon_context=context;
  assert.equal(clipStatistics(clip,[],{},completionVideo).evidence[0].weaponContext,undefined);
 }
 const mismatch=weaponContextFixture();mismatch.fix.events[0].text='擊倒 DIFFERENT+150';
 assert.equal(applyStatisticsCorrection(mismatch.clip,mismatch.fix,'weapon-v1',completionVideo),mismatch.clip);
 const held=weaponContextFixture('held_at_event');held.context.evidence[1].slot=1;held.clip.recognition.outcome_evidence[0].weapon_context=held.context;
 assert.equal(clipStatistics(held.clip,[],{},completionVideo).evidence[0].weaponContext,undefined);
});

test('同来源武器重读未知会撤销旧展示，错误来源不能撤销已确认上下文',()=>{
 const {clip,fix}=weaponContextFixture(),corrected=applyStatisticsCorrection(clip,fix,'weapon-v1',completionVideo);
 const unknown=structuredClone(fix);Object.assign(unknown.events[0].weapon_context,{status:'unknown',scope:'unknown',weapon:null,evidence:[]});
 const cleared=applyStatisticsCorrection(corrected,unknown,'weapon-v2',completionVideo);
 assert.equal(clipStatistics(cleared,[],{},completionVideo).evidence[0].weaponContext,undefined);assert.deepEqual(cleared.summary,clip.summary);
 unknown.events[0].weapon_context.source.size++;
 assert.equal(applyStatisticsCorrection(corrected,unknown,'weapon-v2',completionVideo),corrected);
});
