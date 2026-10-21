import {useEffect,useRef,useState} from 'react';
import {RecognitionActionGate} from './recognitionActionGate';

/** The backend must persist/deduplicate the job before resolving the callback. */
export default function useRecognitionNoticeAction(identity:string){
 const gate=useRef<RecognitionActionGate>(new RecognitionActionGate(identity)),[,render]=useState(0),[error,setError]=useState('');
 gate.current.update(identity);
 useEffect(()=>{setError('');},[identity]);
 async function run(action:()=>void|Promise<void>){
  const token=gate.current.begin();if(!token)return;
  render(value=>value+1);setError('');
  try{await action();/* Keep this request locked until backend snapshot changes. */}
  catch(error){if(gate.current.fail(token)){render(value=>value+1);setError(String(error).replace(/^Error:\s*/,''));}}
 }
 return {pending:gate.current.pending,error,run};
}
