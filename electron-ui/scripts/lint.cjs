/* TS7由项目编译器检查类型；将同一源码转JS后用ESLint检查运行时逻辑规则。 */
const fs=require('node:fs/promises');const path=require('node:path');
(async()=>{const{ESLint}=await import('eslint');const root=path.resolve(__dirname,'..'),files=[];
 async function walk(dir){for(const e of await fs.readdir(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())await walk(p);else if(/\.(js|cjs|mjs)$/.test(e.name))files.push(p);}}
 for(const dir of ['output/lint-renderer','output/lint-electron','scripts'])await walk(path.join(root,dir));
 const lint=new ESLint({overrideConfigFile:true,overrideConfig:{languageOptions:{ecmaVersion:2022,sourceType:'module'},rules:{'no-unreachable':'error','no-debugger':'error','no-dupe-args':'error','no-dupe-else-if':'error','no-constant-binary-expression':'error','valid-typeof':'error'}}});let errors=0;
 for(const file of files){const code=await fs.readFile(file,'utf8');const reports=await lint.lintText(code,{filePath:file.replace(/\.(tsx?|cjs|mjs)$/,'.js')});for(const report of reports)for(const message of report.messages){if(message.severity===2)errors++;console.error(path.relative(root,file)+': '+message.message+' ['+message.ruleId+']');}}
 if(errors)process.exitCode=1;else console.log('ESLint runtime checks passed: '+files.length+' product files');
})().catch(e=>{console.error(e);process.exitCode=1;});
