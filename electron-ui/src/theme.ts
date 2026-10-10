import {argbFromHex,hexFromArgb,Hct,SchemeTonalSpot,MaterialDynamicColors} from '@material/material-color-utilities';
import type {ThemePreferences,SystemTheme} from './shared';
export function applyTheme(prefs:ThemePreferences,system:SystemTheme){
 try{
  const seed=prefs.seed||system.accent;const dark=prefs.mode==='dark'||prefs.mode==='system'&&system.dark;
  const scheme=new SchemeTonalSpot(Hct.fromInt(argbFromHex(seed)),dark,0);
  const roles=['primary','onPrimary','primaryContainer','onPrimaryContainer','secondary','onSecondary','secondaryContainer','onSecondaryContainer','tertiary','onTertiary','tertiaryContainer','onTertiaryContainer','surface','surfaceContainerLowest','surfaceContainerLow','surfaceContainer','surfaceContainerHigh','surfaceContainerHighest','onSurface','onSurfaceVariant','outline','outlineVariant','error','onError','errorContainer','onErrorContainer'] as const;
  for(const role of roles){const color=MaterialDynamicColors[role];document.documentElement.style.setProperty('--'+role,hexFromArgb(color.getArgb(scheme)));}
  document.documentElement.style.setProperty('--card-accent',prefs.seed?hexFromArgb(MaterialDynamicColors.primary.getArgb(scheme)):'#1274ff');
  document.documentElement.dataset.theme=dark?'dark':'light';document.documentElement.dataset.reduced=String(prefs.reduceMotion||system.reduceMotion);document.documentElement.style.colorScheme=dark?'dark':'light';
 }catch{/* 生成失败时保留上次有效 tokens。 */}
}
