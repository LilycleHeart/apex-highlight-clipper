import StyledSelect from './StyledSelect';
import {ArrowDownWideNarrow,ArrowUpNarrowWide} from 'lucide-react';
import type {LibrarySort} from './librarySort';
const choices=[{value:'recent',label:'最近整理'},{value:'recorded',label:'录像时间'},{value:'damage',label:'伤害'},{value:'kills',label:'击杀'}] as const;
export default function LibrarySortMenu({value,descending,onChange,onDirectionChange}:{value:LibrarySort;descending:boolean;onChange:(value:LibrarySort)=>void;onDirectionChange:()=>void}){
 return <div className="library-sort"><StyledSelect value={value.startsWith('recorded-')?'recorded':value} onChange={onChange} options={choices} label="片段排序"/><button type="button" className="sort-direction" aria-label={`排序方向：${descending?'降序':'升序'}`} title={`切换为${descending?'升序':'降序'}`} onClick={onDirectionChange}>{descending?<ArrowDownWideNarrow size={18}/>:<ArrowUpNarrowWide size={18}/>}</button></div>;
}
