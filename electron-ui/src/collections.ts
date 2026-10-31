import {createContext,useContext} from 'react';
import type {ClipCollection} from './shared';

/** Windows 路径比较：统一分隔符并忽略大小写。 */
export const sameFile=(a:string,b:string)=>a.replace(/\\/g,'/').toLowerCase()===b.replace(/\\/g,'/').toLowerCase();

/** 片段库读到的收藏夹列表，片段卡片用它判断星标是否点亮。 */
export const CollectionsContext=createContext<ClipCollection[]>([]);

export function useClipCollections(file:string){
 return useContext(CollectionsContext).filter(item=>item.files.some(member=>sameFile(member,file)));
}
