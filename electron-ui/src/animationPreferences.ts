export interface AnimationPreferences {mascotFps:number;backgroundFps:number}
export const animationDefaults:AnimationPreferences={mascotFps:30,backgroundFps:60};
export const MIN_ANIMATION_FPS=1,MAX_ANIMATION_FPS=240;
export function normalizeFrameRate(value:unknown,fallback:number){
 return typeof value==='number'&&Number.isFinite(value)?Math.min(MAX_ANIMATION_FPS,Math.max(MIN_ANIMATION_FPS,Math.round(value))):fallback;
}
export function normalizeAnimationPreferences(value:unknown):AnimationPreferences{
 const prefs=value&&typeof value==='object'?value as Partial<AnimationPreferences>:{};
 return {mascotFps:normalizeFrameRate(prefs.mascotFps,animationDefaults.mascotFps),backgroundFps:normalizeFrameRate(prefs.backgroundFps,animationDefaults.backgroundFps)};
}
