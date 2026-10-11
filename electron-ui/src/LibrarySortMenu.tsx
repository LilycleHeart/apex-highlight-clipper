import StyledSelect from './StyledSelect';
import type {LibrarySort} from './librarySort';
const choices=[{value:'recent',label:'最近整理'},{value:'recorded-newest',label:'录像时间 · 新到旧'},{value:'recorded-oldest',label:'录像时间 · 旧到新'},{value:'damage',label:'伤害 ↓'},{value:'kills',label:'击杀 ↓'}] as const;
export default function LibrarySortMenu({value,onChange}:{value:LibrarySort;onChange:(value:LibrarySort)=>void}){
 return <StyledSelect value={value} onChange={onChange} options={choices} label="片段排序"/>;
}
