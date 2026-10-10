import {argbFromHex,hexFromArgb,Hct,SchemeFidelity,MaterialDynamicColors} from '@material/material-color-utilities';
import type {ThemePreferences,SystemTheme} from './shared';
const roles=['primary','onPrimary','primaryContainer','onPrimaryContainer','secondary','onSecondary','secondaryContainer','onSecondaryContainer','tertiary','onTertiary','tertiaryContainer','onTertiaryContainer','surface','surfaceContainerLowest','surfaceContainerLow','surfaceContainer','surfaceContainerHigh','surfaceContainerHighest','onSurface','onSurfaceVariant','outline','outlineVariant','error','onError','errorContainer','onErrorContainer'] as const;
const cache=new Map<string,Record<string,string>>();
let applied='';
export function applyTheme(prefs:ThemePreferences,system:SystemTheme){
 try{
  const seed=prefs.seed||'#1274ff',dark=prefs.mode==='dark'||prefs.mode==='system'&&system.dark,key=seed+':'+dark;
  let tokens=cache.get(key);
  if(!tokens){
   const scheme=new SchemeFidelity(Hct.fromInt(argbFromHex(seed)),dark,0);
   tokens={};
   for(const role of roles)tokens[role]=hexFromArgb(MaterialDynamicColors[role].getArgb(scheme));
   const primary=(tone:number)=>hexFromArgb(scheme.primaryPalette.tone(tone));
   const neutral=(tone:number)=>hexFromArgb(scheme.neutralPalette.tone(tone));
   const variant=(tone:number)=>hexFromArgb(scheme.neutralVariantPalette.tone(tone));
   // 大面积品牌工作区使用调色板中的命名语义角色，其余直接复用官方scheme角色。
   Object.assign(tokens,{
    'page-blue':primary(dark?26:46),'page-on':neutral(99),'page-muted':neutral(dark?88:96),
    'page-control':primary(dark?18:34),'page-control-on':neutral(98),
    'card-paper':tokens.surfaceContainerLow,'card-ink':tokens.onSurface,
    'card-muted':tokens.onSurfaceVariant,'card-tint':variant(dark?22:94),
    'card-line':tokens.outlineVariant,'card-accent':tokens.primary,'accent-on':tokens.onPrimary,
    'chrome':neutral(dark?6:12),'chrome-on':neutral(96)
   });
   cache.set(key,tokens);if(cache.size>64)cache.delete(cache.keys().next().value!);
  }
  if(applied!==key){for(const [name,value] of Object.entries(tokens))document.documentElement.style.setProperty('--'+name,value);applied=key;}
  document.documentElement.dataset.theme=dark?'dark':'light';
  document.documentElement.dataset.seed=seed;
  document.documentElement.dataset.reduced=String(prefs.reduceMotion||system.reduceMotion);
  document.documentElement.style.colorScheme=dark?'dark':'light';
  return {color:tokens.chrome,foreground:tokens['chrome-on']};
 }catch{/* 保留上次有效配色，不把非法颜色或部分token写进界面。 */}
}
