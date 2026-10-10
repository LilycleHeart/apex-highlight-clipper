import type {Options} from './shared';
export default function FilterSettings({options,update}:{options:Options;update:(key:keyof Options,value:unknown)=>void}){
 return <section className="filter-settings" aria-label="片段过滤"><h3>片段过滤</h3><label className="toggle"><div><b>按战绩过滤</b><span>单段统计完成后筛选，未达标片段不导出</span></div><input aria-label="按战绩过滤" type="checkbox" checked={options.filter_enabled} onChange={e=>update('filter_enabled',e.target.checked)}/></label>
  <label className="filter-mode">保留条件<select aria-label="过滤保留条件" disabled={!options.filter_enabled} value={options.filter_mode} onChange={e=>update('filter_mode',e.target.value)}><option value="any">任一项达标就保留</option><option value="all">全部设置项达标才保留</option></select></label>
  <div className="number-fields">{([{key:'min_damage',title:'最低伤害',max:20000,unit:'伤害'},{key:'min_kills',title:'最低击杀',max:60,unit:'杀'},{key:'min_assists',title:'最低助攻',max:99,unit:'助攻'}] as const).map(f=><label key={f.key}>{f.title}<div className="number-input"><input aria-label={f.title} type="number" min={0} max={f.max} step={1} disabled={!options.filter_enabled} value={options[f.key]} onChange={e=>update(f.key,e.target.valueAsNumber)} onBlur={()=>update(f.key,Math.min(f.max,Math.max(0,Math.trunc(Number.isFinite(options[f.key])?options[f.key]:0))))}/><span>{f.unit}</span></div></label>)}</div>
  <p className="field-hint">0 表示该项不限制，等于阈值也达标。未知计数或不足以判断的下限送入待复核；过滤参数在本批次中保持不变。</p>
 </section>;
}
