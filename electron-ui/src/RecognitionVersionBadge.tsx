import InfoTip from './InfoTip';
import {algorithmStatusLabels,algorithmVersionDetails,clipAlgorithmFreshness,type AlgorithmFieldRecord} from './algorithmStatus';
import './recognition-recovery.css';

export default function RecognitionVersionBadge({fields}:{fields:readonly AlgorithmFieldRecord[]}){
 const status=clipAlgorithmFreshness(fields);
 return <span className="recognition-version" data-version-status={status}>
  <span>{algorithmStatusLabels[status]}</span>
  <InfoTip label="识别算法版本详情" text={algorithmVersionDetails(fields)}/>
 </span>;
}
