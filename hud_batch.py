"""Overlap independent manifests without multiplying native reader pools.

Each coordinator owns one manifest and keeps its existing ordered commits.
Heavy preparation shares one bounded pool; no coordinator mutates execution
settings, creates another isolated process, or writes another group's metadata.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import threading

from app_cancel import check_cancel


def parallel_groups(request):
    keys=[str(Path(job['directory']).resolve()).casefold() for job in request['jobs']]
    return len(set(keys))>1


def run_batch(request,emit,run_group):
    from queue_policy import QueuePolicy
    from hud_read_queue import shared_read_pool
    policy=QueuePolicy();fields=request['fields'];by_directory={}
    # Resume/upgrade can split one manifest into different field selections.
    # Keep those selections in one coordinator, rather than disabling the
    # entire batch or allowing concurrent writes to the same export.json.
    for job in request['jobs']:
        key=str(Path(job['directory']).resolve()).casefold()
        by_directory.setdefault(key,[]).append(job)
    groups=list(by_directory.values())
    units=[sum(len(job['files'])*(bool(set(job.get('fields',fields))&{'account','weapons','teammates','hero','rank'})+
        bool(set(job.get('fields',fields))&{'statistics','opponents','event_weapons'})) for job in group) for group in groups]
    total=sum(units);counts=[0]*len(groups);lock=threading.RLock()
    results=[];coordinators=min(len(groups),policy.budget.max_workers)
    emit({'type':'hud-info-start','index':0,'total':total,'message':'准备跨录像组识别'})

    def run(index):
        check_cancel()
        def forward(event):
            kind=event.get('type')
            if kind in {'hud-info-start','hud-info-done'}:return
            with lock:
                if kind=='hud-info-progress':counts[index]=max(counts[index],min(units[index],event['index']))
                emit({**event,'index':sum(counts),'total':total})
        # Plain internal runner: global environment and recovery session are
        # configured only once by the parent, before any worker starts.
        return run_group({**request,'jobs':groups[index]},forward)

    with shared_read_pool(policy,coordinators,total):
        with ThreadPoolExecutor(max_workers=coordinators,thread_name_prefix='hud-group') as executor:
            futures=[executor.submit(run,index) for index in range(len(groups))]
            try:
                for future in as_completed(futures):
                    check_cancel();results.append(future.result())
            except BaseException:
                for future in futures:future.cancel()
                raise
    updated=set().union(*(set(result.get('files_updated',[])) for result in results))
    unconfirmed=set().union(*(set(result.get('unconfirmed_files',[])) for result in results))
    errors=[error for result in results for error in result.get('errors',[])]
    result={'type':'hud-info-done','updated':len(updated),'errors':errors,'unconfirmed':len(unconfirmed),
        'files_updated':sorted(updated),'unconfirmed_files':sorted(unconfirmed),'total':total}
    emit(result);return result
