import {playerNameKey,withoutClanTag} from './libraryNames';
const maximum=2000;
function clean(value:unknown){return typeof value==='string'&&value.length<=128&&!/[\u0000-\u001f\u007f]/.test(value)?withoutClanTag(value):'';}
export const excludedTeammateKey=(name:string)=>playerNameKey(name)||name.normalize('NFKC').trim().toLocaleLowerCase();
/** Personal browsing preferences only; never feed these labels back into OCR. */
export function normalizeTeammateExclusions(raw:unknown):string[]{
 if(!Array.isArray(raw))return[];
 const names=new Map<string,string>();
 for(const item of raw){const name=clean(item);if(name&&!names.has(excludedTeammateKey(name)))names.set(excludedTeammateKey(name),name);if(names.size>=maximum)break;}
 return [...names.values()];
}
export function changeTeammateExclusion(current:string[],raw:unknown,excluded:unknown):string[]{
 const name=clean(raw);if(!name||typeof excluded!=='boolean')throw new Error('非好友标记无效');
 const key=excludedTeammateKey(name),exists=current.some(item=>excludedTeammateKey(item)===key);
 if(excluded){if(exists)return current;if(current.length>=maximum)throw new Error('非好友标记已满，请先恢复不需要排除的名称');return[...current,name];}
 return current.filter(item=>excludedTeammateKey(item)!==key);
}
