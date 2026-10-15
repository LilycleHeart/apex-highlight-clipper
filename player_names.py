"""玩家名的有限跨帧共识；保留实际读到的拼写，不生成或猜补字符。"""
from collections import Counter
import re
from statistics import median
import unicodedata


def strip_clan_tag(value):
    name=unicodedata.normalize('NFKC',value or '').strip()
    name=re.sub(r'^\[?[^\[\]\s]{1,6}\]\s*','',name)
    name=re.sub(r'^\[[A-Za-z0-9]{2,6}(?=[\u3040-\u30ff\u3400-\u9fff])','',name)
    return re.sub(r'^\[[A-Za-z0-9]{2,6}\s+','',name).strip()


def name_key(value):
    return ''.join(c for c in strip_clan_tag(value).casefold() if c.isalnum())


def close_name(left, right,minimum_length=6):
    left, right = name_key(left), name_key(right)
    if left == right:
        return bool(left)
    length=min(len(left),len(right))
    limit=2 if length>=12 or length>=10 and left.isascii() and right.isascii() else 1
    if min(len(left), len(right)) < minimum_length or abs(len(left)-len(right)) > limit:
        return False
    previous=list(range(len(right)+1))
    for i,a in enumerate(left,1):
        row=[i]
        for j,b in enumerate(right,1):row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous=row
    return previous[-1]<=limit


def player_name(text):
    if not isinstance(text, str):
        return ''
    name = strip_clan_tag(re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text))).strip(' ()（）♫♪◀▶□')
    key = name_key(name)
    # 固定昵称框也可能是纯数字账号；不要只保留被 OCR 错读出字母的版本。
    if not 2 <= len(name) <= 40 or not (any(c.isalpha() for c in name) or re.fullmatch(r'\d{5,20}',name)):
        return ''
    if re.search(r'[\x00-\x1f\ufffd□<>:=+!?！？。]', name):
        return ''
    if key.upper() in {'MAXLEVEL', 'DEATHBOXRECOVERY', 'RECOVERBANNER', 'SPECTATING', 'DAMAGEINFLICTED', 'KNOCKEDDOWN', 'ELIMINATED', 'ASSIST'}:
        return ''
    if re.search(r'傷害|伤害|造成|擊倒|击倒|消滅|消灭|助攻|進化|进化|等級|等级|下個|下个|回收|旗幟|旗帜|觀戰|观战', name):
        return ''
    return name


def consensus_name(values, minimum=2):
    # 调用者按不同画面传入；同一画面的两个预处理视图不能算两票。
    values = [{**v,'name':strip_clan_tag(v['name'])} for v in values if v and name_key(v.get('name')) and v.get('confidence', 0) >= .80]
    counts = Counter(name_key(v['name']) for v in values)
    reliable = [key for key, n in counts.items() if n >= minimum]
    if not reliable:
        return None
    key = max(reliable, key=lambda k: (counts[k], sum(v['confidence'] for v in values if name_key(v['name']) == k)))
    if any(counts[k] == counts[key] and not close_name(k, key) for k in reliable if k != key):
        return None
    selected = [v for v in values if name_key(v['name']) == key]
    spelling = Counter(v['name'] for v in selected)
    best = max(selected, key=lambda v: (spelling[v['name']], v['confidence']))
    return {**best, 'confidence': min(v['confidence'] for v in selected), 'consensus_confidence':median(v['confidence'] for v in selected), 'votes': len(selected)}


def canonical_name(value, reference,*,same_player=False):
    value={**value,'name':strip_clan_tag(value['name'])} if value else None
    reference={**reference,'name':strip_clan_tag(reference['name'])} if reference else None
    if not value or not reference or not close_name(value['name'], reference['name'],2 if same_player else 6):
        return value
    if same_player and reference.get('consensus_confidence',reference.get('confidence',0))>=.86 and reference.get('votes',0)>=max(4,2*value.get('votes',1)):
        return {**value,'name':reference['name'],'method':'same_player_frame_consensus'}
    if name_key(value['name']) != name_key(reference['name']) and (
        value.get('confidence', 0) >= .92 or reference.get('confidence', 0) < .86 or reference.get('votes', 0) < 3):
        return value
    return {**value, 'name': reference['name'], 'method': 'recording_name_consensus'}
