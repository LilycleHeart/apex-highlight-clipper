const path=require('node:path');const fs=require('node:fs');const root=path.resolve(__dirname,'..');const out=path.resolve(root,process.env.APEX_PACKAGE_OUT||'release');const target=path.join(out,'Apex Highlight Clipper-win32-x64');
const{spawnSync}=require('node:child_process');
if(path.dirname(out)!==root||!/^release(?:-[a-z0-9-]+)?$/i.test(path.basename(out)))throw new Error('打包目录必须是工程下的release或release-*目录');
if(!target.startsWith(root+path.sep)||path.relative(out,target).startsWith('..'))throw new Error('打包目录超出工程');
if(fs.existsSync(target))throw new Error('打包目录已经存在；请指定新的APEX_PACKAGE_OUT，保留已有运行程序。');
function state(status){fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'.apex-build.json'),JSON.stringify({schema:1,owner:'apex-auto-clipper',kind:'electron',status,pid:process.pid,updated:new Date().toISOString()}));}
function cleanup(){const result=spawnSync('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(root,'../scripts/cleanup-generated.ps1'),'-Apply'],{windowsHide:true,stdio:'inherit'});if(result.status!==0)console.error('构建产物清理失败，请检查cleanup-generated.ps1输出');}
state('building');
import('@electron/packager').then(async({packager})=>{const paths=await packager({dir:root,name:'Apex Highlight Clipper',icon:path.join(root,'public/brand/cat-clapperboard.ico'),platform:'win32',arch:'x64',out,overwrite:false,asar:true,prune:false,ignore:[/^\/(src|electron|tests|output|release(?:-[^/]+)?|node_modules|public|[.]playwright[^/]*)($|\/)/,/^\/scripts($|\/)/,/^\/package-lock[.]json$/,/.*[.]tsx?$/]});state('succeeded');console.log(paths.join('\n'));cleanup();}).catch(error=>{console.error(error);process.exitCode=1;state('failed');cleanup();});
