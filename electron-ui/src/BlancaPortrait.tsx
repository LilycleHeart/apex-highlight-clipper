import {useEffect,useState} from 'react';
import {actionForStage,frameAt} from './blancaState';
import {getBlancaSprite} from './blancaSprites';
import type {Stage,MascotStyle} from './shared';
export default function BlancaPortrait({stage}:{stage:Stage;style:MascotStyle}){
 const [url,setUrl]=useState<string>();
 useEffect(()=>{let live=true;void getBlancaSprite(actionForStage(stage),frameAt(stage,0,true)).then(value=>{if(live)setUrl(value);},()=>{if(live)setUrl(undefined);});return()=>{live=false;};},[stage]);
 return <span className="blanca-portrait"><img className="blanca-sprite" src={url} alt="Blanca 俏皮工作动作预览"/></span>;
}
