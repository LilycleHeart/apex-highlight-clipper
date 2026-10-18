// Current EA class roster; columns follow the in-game selection screen.
// https://www.ea.com/games/apex-legends/apex-legends/game-objects/characters-hub
// Within a class, keep the familiar release order instead of sorting names.
export const legendRoles=[
 {id:'assault',name:'突击',color:'#e78579',legends:[
  {id:'bangalore',name:'班加罗尔'},{id:'revenant',name:'亡灵'},{id:'fuse',name:'暴雷'},
  {id:'mad-maggie',name:'疯玛吉'},{id:'ballistic',name:'弹道'},
 ]},
 {id:'skirmisher',name:'游击',color:'#b3a0e4',legends:[
  {id:'pathfinder',name:'探路者'},{id:'wraith',name:'恶灵'},{id:'octane',name:'动力小子'},
  {id:'horizon',name:'地平线'},{id:'ash',name:'艾许'},{id:'alter',name:'变幻'},{id:'axle',name:'艾克赛尔'},
 ]},
 {id:'recon',name:'侦察',color:'#89bae5',legends:[
  {id:'bloodhound',name:'寻血猎犬'},{id:'crypto',name:'密客'},{id:'valkyrie',name:'瓦尔基里'},
  {id:'seer',name:'希尔'},{id:'vantage',name:'万蒂奇'},{id:'sparrow',name:'Sparrow'},
 ]},
 {id:'support',name:'支援',color:'#81c7be',legends:[
  {id:'gibraltar',name:'直布罗陀'},{id:'lifeline',name:'命脉'},{id:'mirage',name:'幻象'},
  {id:'loba',name:'罗芭'},{id:'newcastle',name:'纽卡斯尔'},{id:'conduit',name:'导管'},
 ]},
 {id:'controller',name:'控制',color:'#d9bf79',legends:[
  {id:'caustic',name:'侵蚀'},{id:'wattson',name:'沃特森'},
  {id:'rampart',name:'兰伯特'},{id:'catalyst',name:'催化姬'},
 ]},
];
export const legendFor=(id:string)=>legendRoles.flatMap(role=>role.legends).find(legend=>legend.id===id);
