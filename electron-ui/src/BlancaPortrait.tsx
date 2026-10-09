import {actionForStage,assetUrl,frameAt} from './blancaState';
import type {Stage,MascotStyle} from './shared';
export default function BlancaPortrait({stage,style}:{stage:Stage;style:MascotStyle}){return <img className="blanca-portrait" src={assetUrl(style,actionForStage(stage),frameAt(stage,0,true))} alt={style==='flat'?'Blanca 平涂纸片样式预览':'Blanca 淡彩线稿样式预览'}/>;}
