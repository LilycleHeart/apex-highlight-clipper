import {useCallback,useEffect,useId,useLayoutEffect,useMemo,useRef,useState,type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';
import {CalendarDays,ChevronDown,ChevronLeft,ChevronRight,X} from 'lucide-react';
import {dateFilterLabel} from './libraryFilters';
import {useMotionPresence} from './surfaceMotion';

type Mode='days'|'months'|'years';
const pad=(value:number)=>String(value).padStart(2,'0');
const monthKey=(year:number,month:number)=>`${year}-${pad(month+1)}`;
export default function DatePicker({value,onChange,dates,hasUnknown}:{value:string;onChange:(value:string)=>void;dates:{date:string;count:number}[];hasUnknown:boolean}){
 const today=new Date(),todayKey=`${today.getFullYear()}-${pad(today.getMonth()+1)}-${pad(today.getDate())}`;
 const [open,setOpen]=useState(false),[mode,setMode]=useState<Mode>('days'),[year,setYear]=useState(today.getFullYear()),[month,setMonth]=useState(today.getMonth()),[yearPage,setYearPage]=useState(Math.floor(today.getFullYear()/12)*12);
 const [position,setPosition]=useState({left:8,top:44,width:328,maxHeight:460});
 const trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null),id=useId(),present=useMotionPresence(open,panel);
 const counts=useMemo(()=>new Map(dates.map(entry=>[entry.date,entry.count])),[dates]);
 const available=[...counts.keys()].sort(),first=available[0]||todayKey,last=available.at(-1)||todayKey;
 const sum=(prefix:string)=>dates.reduce((total,entry)=>total+(entry.date.startsWith(prefix)?entry.count:0),0);
 const prefix=monthKey(year,month),monthTotal=sum(prefix),yearTotal=sum(String(year));
 const offset=(new Date(Date.UTC(year,month,1)).getUTCDay()+6)%7;
 const days=Array.from({length:42},(_,index)=>{const date=new Date(Date.UTC(year,month,index-offset+1)),key=date.toISOString().slice(0,10);return{key,day:date.getUTCDate(),current:date.getUTCMonth()===month,count:counts.get(key)||0};});
 const close=useCallback((focus=false)=>{setOpen(false);if(focus)trigger.current?.focus();},[]);
 const place=useCallback(()=>{
  const rect=trigger.current?.getBoundingClientRect();if(!rect)return;
  const width=Math.min(328,innerWidth-16),maxHeight=Math.min(470,innerHeight-56),top=Math.max(44,Math.min(rect.bottom+6,innerHeight-maxHeight-12));
  setPosition({left:Math.max(8,Math.min(rect.left,innerWidth-width-8)),top,width,maxHeight});
 },[]);
 function show(){
  const selected=available.filter(date=>value&&date.startsWith(value)).at(-1)||last;
  const parts=(/^\d{4}(?:-\d{2}(?:-\d{2})?)?$/.test(value)?value:selected).split('-').map(Number);
  const nextYear=parts[0],nextMonth=(parts[1]||Number(selected.slice(5,7)))-1;
  setYear(nextYear);setMonth(nextMonth);setYearPage(Math.floor(nextYear/12)*12);setMode('days');setOpen(true);
 }
 function choose(next:string){onChange(next);close(true);}
 function navigate(direction:number){
  if(mode==='years'){setYearPage(page=>page+direction*12);return;}
  if(mode==='months'){setYear(current=>current+direction);return;}
  const next=new Date(Date.UTC(year,month+direction,1));setYear(next.getUTCFullYear());setMonth(next.getUTCMonth());
 }
 const navigationValue=mode==='years'?yearPage:mode==='months'?year:year*12+month;
 const min=mode==='years'?Math.floor(Number(first.slice(0,4))/12)*12:mode==='months'?Number(first.slice(0,4)):Number(first.slice(0,4))*12+Number(first.slice(5,7))-1;
 const max=mode==='years'?Math.floor(Number(last.slice(0,4))/12)*12:mode==='months'?Number(last.slice(0,4)):Number(last.slice(0,4))*12+Number(last.slice(5,7))-1;
 useLayoutEffect(()=>{if(open)place();},[open,place]);
 useEffect(()=>{
  if(!open)return;
  const outside=(event:PointerEvent)=>{if(!panel.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))close();};
  const scroll=(event:Event)=>{if(!panel.current?.contains(event.target as Node))place();};
  const focus=(event:FocusEvent)=>{if(!panel.current?.contains(event.target as Node)&&!trigger.current?.contains(event.target as Node))close();};
  document.addEventListener('pointerdown',outside);document.addEventListener('focusin',focus);document.addEventListener('scroll',scroll,true);window.addEventListener('resize',place);
  return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',focus);document.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',place);};
 },[open,close,place]);
 useEffect(()=>{
  if(!open)return;
  const grid=panel.current?.querySelector('.calendar-grid');
  (grid?.querySelector<HTMLButtonElement>('[aria-pressed=true]:not(:disabled)')||grid?.querySelector<HTMLButtonElement>('[data-calendar-choice]:not(:disabled)')||panel.current?.querySelector<HTMLButtonElement>('.calendar-reset'))?.focus({preventScroll:true});
 },[open,mode,year,month,yearPage]);
 function keyDown(event:KeyboardEvent){
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
  if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
  const buttons=[...panel.current?.querySelectorAll<HTMLButtonElement>('[data-calendar-choice]:not(:disabled)')||[]];
  event.preventDefault();if(event.key==='Home'||event.key==='End'){(event.key==='Home'?buttons[0]:buttons.at(-1))?.focus();return;}
  const rect=(event.target as HTMLElement).closest('button')?.getBoundingClientRect();if(!rect)return;
  const horizontal=['ArrowLeft','ArrowRight'].includes(event.key),sign=['ArrowRight','ArrowDown'].includes(event.key)?1:-1;
  buttons.map(button=>{const box=button.getBoundingClientRect(),dx=box.x+box.width/2-rect.x-rect.width/2,dy=box.y+box.height/2-rect.y-rect.height/2;return{button,along:(horizontal?dx:dy)*sign,across:Math.abs(horizontal?dy:dx)};}).filter(candidate=>candidate.along>2).sort((a,b)=>a.along+a.across*3-b.along-b.across*3)[0]?.button.focus();
 }
 return <><button type="button" ref={trigger} data-fixed-ink className="styled-select date-picker-trigger" role="combobox" aria-label="录制日期筛选" aria-haspopup="dialog" aria-controls={open?id:undefined} aria-expanded={open} onClick={()=>open?close():show()} onKeyDown={event=>{if(event.key==='ArrowDown'){event.preventDefault();show();}}}><span className="date-picker-value"><CalendarDays size={17}/><span>{dateFilterLabel(value)}</span></span><ChevronDown size={15}/></button>
  {present&&createPortal(<div ref={panel} id={id} className="calendar-panel" role="dialog" aria-label="选择录制日期" data-motion-surface aria-hidden={!open} inert={!open} style={position} onKeyDown={keyDown}>
   <div className="calendar-heading"><div><b>录制日期</b><span><i/>有录像的日期</span></div><button type="button" className="icon-button" aria-label="关闭日历" onClick={()=>close(true)}><X size={15}/></button></div>
   <div className="calendar-navigation"><button type="button" className="icon-button" aria-label={mode==='days'?'上个月':mode==='months'?'上一年':'前十二年'} disabled={navigationValue<=min} onClick={()=>navigate(-1)}><ChevronLeft size={17}/></button><div>{mode==='years'?<b>{yearPage} — {yearPage+11}</b>:<><button type="button" aria-label="选择年份" onClick={()=>{setYearPage(Math.floor(year/12)*12);setMode('years');}}>{year}年<ChevronDown size={12}/></button><button type="button" aria-label="选择月份" onClick={()=>setMode(mode==='months'?'days':'months')}>{month+1}月<ChevronDown size={12}/></button></>}</div><button type="button" className="icon-button" aria-label={mode==='days'?'下个月':mode==='months'?'下一年':'后十二年'} disabled={navigationValue>=max} onClick={()=>navigate(1)}><ChevronRight size={17}/></button></div>
   {mode==='days'&&<div className="calendar-weekdays" aria-hidden="true">{['一','二','三','四','五','六','日'].map(day=><span key={day}>{day}</span>)}</div>}
   <div className={`calendar-grid calendar-${mode}`} role="group" aria-label={mode==='days'?'按日选择':mode==='months'?'按月浏览':'按年浏览'}>
    {mode==='days'?days.map(day=><button type="button" key={day.key} data-calendar-choice={day.key} disabled={!day.count} className={day.current?'':'calendar-adjacent'} aria-label={`${dateFilterLabel(day.key)}，${day.count}段录像`} aria-pressed={value===day.key} aria-current={day.key===todayKey?'date':undefined} data-in-range={day.count>0&&!!value&&day.key.startsWith(value)} onClick={()=>choose(day.key)} title={`${day.count} 段录像`}><span>{day.day}</span>{day.count>0&&<i/>}</button>):mode==='months'?Array.from({length:12},(_,index)=>{const count=sum(monthKey(year,index));return <button type="button" key={index} data-calendar-choice={monthKey(year,index)} disabled={!count} aria-pressed={value===monthKey(year,index)} onClick={()=>{setMonth(index);setMode('days');}}><span>{index+1}月</span><small>{count} 段</small></button>;}):Array.from({length:12},(_,index)=>{const next=yearPage+index,count=sum(String(next));return <button type="button" key={next} data-calendar-choice={String(next)} disabled={!count} aria-pressed={value===String(next)} onClick={()=>{setYear(next);setMode('months');}}><span>{next}</span><small>{count} 段</small></button>;})}
   </div>
   <div className="calendar-period-actions"><button type="button" disabled={!yearTotal} onClick={()=>choose(String(year))}>筛选 {year} 年<span>{yearTotal} 段</span></button><button type="button" disabled={!monthTotal} onClick={()=>choose(prefix)}>筛选 {month+1} 月<span>{monthTotal} 段</span></button></div>
   <div className="calendar-footer"><button type="button" className="calendar-reset" onClick={()=>choose('')}>全部日期</button>{hasUnknown&&<button type="button" onClick={()=>choose('unknown')}>日期未识别</button>}</div>
  </div>,document.body)}
 </>;
}
