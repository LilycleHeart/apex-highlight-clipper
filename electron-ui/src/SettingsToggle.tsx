import {useId} from 'react';
import InfoTip from './InfoTip';
export default function SettingsToggle({label,description,checked,onChange,disabled=false}:{label:string;description:string;checked:boolean;onChange:(value:boolean)=>void;disabled?:boolean}){
 const id=useId();return <div className="toggle"><div className="setting-label"><label htmlFor={id}><b>{label}</b></label><InfoTip label={label+'说明'} text={description}/></div><input id={id} type="checkbox" aria-label={label} checked={checked} disabled={disabled} onChange={e=>onChange(e.target.checked)}/></div>;
}
