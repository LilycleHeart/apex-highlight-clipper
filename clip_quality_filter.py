"""按最终单段战绩过滤，严格区分确定不足与计数下限/未知。"""
VERSION='clip-quality-v1'

def assess(record,options):
    limits={key:options.get('min_'+key,0) for key in ['damage','kills','assists']}
    enabled={key:value for key,value in limits.items() if value>0}
    if not options.get('filter_enabled',False) or not enabled:
        return {'status':'kept','reason':'未启用战绩阈值','fields':{}}
    fields={}
    for key,limit in enabled.items():
        value=record['counts'].get(key)
        fields[key]='unknown' if value is None else 'pass' if value>=limit else 'unknown' if record.get('partial',{}).get(key,False) else 'fail'
    if options.get('filter_mode','any')=='all':
        status='rejected' if 'fail' in fields.values() else 'review' if 'unknown' in fields.values() else 'kept'
    else:
        status='kept' if 'pass' in fields.values() else 'review' if 'unknown' in fields.values() else 'rejected'
    reason={'kept':'达到单段保留阈值','rejected':'单段战绩低于保留阈值','review':'战绩未知或只有下限，无法确定是否达标'}[status]
    return {'status':status,'reason':reason,'fields':fields}

def apply_thresholds(aligned,statistics,options):
    if len(aligned)!=len(statistics['segments']):raise ValueError('过滤区间与统计不匹配')
    indices=[];decisions=[];rejected=[];review=[]
    for i,(segment,record) in enumerate(zip(aligned,statistics['segments'])):
        if abs(segment['start']-record['start'])>.001 or abs(segment['end']-record['end'])>.001:raise ValueError('过滤区间与统计不匹配')
        decision={'index':i,'start':segment['start'],'end':segment['end'],**assess(record,options),'counts':record['counts'],'partial':record['partial']}
        decisions.append(decision)
        if decision['status']=='kept':indices.append(i)
        elif decision['status']=='rejected':rejected.append(decision)
        else:review.append({**decision,'review_reason':decision['reason']})
    report={'version':VERSION,'enabled':options.get('filter_enabled',False),'mode':options.get('filter_mode','any'),
            'thresholds':{key:options.get('min_'+key,0) for key in ['damage','kills','assists']},'decisions':decisions,
            'summary':{'kept':len(indices),'rejected':len(rejected),'review':len(review)}}
    return [aligned[i] for i in indices],{**statistics,'segments':[statistics['segments'][i] for i in indices]},report,rejected,review
