export interface WindowBounds {x:number;y:number;width:number;height:number}
export interface WindowPlacement extends WindowBounds {maximized:boolean}

/** Restore to a connected work area, including when a monitor was unplugged. */
export function restoreWindowPlacement(raw:unknown,areas:WindowBounds[],primary:WindowBounds):WindowPlacement{
 const saved=raw as Partial<WindowPlacement>|null;
 const valid=!!saved&&['x','y','width','height'].every(key=>typeof saved[key as keyof WindowBounds]==='number'&&Number.isFinite(saved[key as keyof WindowBounds]))&&saved.width!>0&&saved.height!>0;
 const overlap=(area:WindowBounds)=>valid?Math.max(0,Math.min(saved!.x!+saved!.width!,area.x+area.width)-Math.max(saved!.x!,area.x))*Math.max(0,Math.min(saved!.y!+saved!.height!,area.y+area.height)-Math.max(saved!.y!,area.y)):0;
 const area=valid?areas.reduce((best,next)=>overlap(next)>overlap(best)?next:best,primary):primary;
 const width=Math.round(Math.min(area.width,Math.max(Math.min(760,area.width),valid?saved!.width!:1120))),height=Math.round(Math.min(area.height,Math.max(Math.min(620,area.height),valid?saved!.height!:820)));
 const x=valid?saved!.x!:area.x+(area.width-width)/2,y=valid?saved!.y!:area.y+(area.height-height)/2;
 return{x:Math.round(Math.max(area.x,Math.min(area.x+area.width-width,x))),y:Math.round(Math.max(area.y,Math.min(area.y+area.height-height,y))),width,height,maximized:valid&&saved!.maximized===true};
}
