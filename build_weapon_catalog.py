"""按已核对的 EA 武器指南生成目录；保留已有实拍图标模板。"""
import json
from pathlib import Path

BASE=Path(__file__).resolve().parent
# id, category, short name, official English name, official Traditional Chinese, English HUD label
ROWS=[
 ('havoc','assault','哈博克','HAVOC Rifle','哈博克步槍','HAVOC'),
 ('flatline','assault','平行','VK-47 Flatline','V-47 平行步槍','FLATLINE'),
 ('hemlok','assault','汗洛','Hemlok Burst AR','汗洛連發突擊步槍','HEMLOK'),
 ('r301','assault','R301','R-301 Carbine','R-301 卡賓槍','R-301'),
 ('nemesis','assault','死敌','Nemesis Burst AR','死敵連發突擊步槍','NEMESIS'),
 ('alternator','smg','转换者','Alternator SMG','轉換者衝鋒槍','ALTERNATOR'),
 ('prowler','smg','猎兽','Prowler Burst PDW','獵獸連發個人防衛武器','PROWLER'),
 ('r99','smg','R99','R-99 SMG','R-99 衝鋒槍','R-99'),
 ('volt','smg','电能冲锋枪','Volt SMG','電能衝鋒槍','VOLT'),
 ('car','smg','CAR','C.A.R. SMG','C.A.R. 衝鋒槍','C.A.R.'),
 ('devotion','lmg','专注','Devotion LMG','專注輕機槍','DEVOTION'),
 ('lstar','lmg','LSTAR','L-STAR EMG','L-STAR 電磁機槍','L-STAR'),
 ('spitfire','lmg','喷火','M600 Spitfire','M600 噴火槍','SPITFIRE'),
 ('rampage','lmg','狂暴','Rampage LMG','狂暴輕機槍','RAMPAGE'),
 ('g7','marksman','G7','G7 Scout','G7 斥候','G7 SCOUT'),
 ('triple_take','marksman','三重击','Triple Take','三重擊','TRIPLE TAKE'),
 ('repeater3030','marksman','3030','30-30 Repeater','30-30 連發槍','30-30'),
 ('bocek','marksman','博切克','Bocek 2.0','博切克 2.0','BOCEK'),
 ('charge_rifle','sniper','电能步枪','Charge Rifle','電能步槍','CHARGE RIFLE'),
 ('longbow','sniper','长弓','Longbow DMR','長弓 DMR','LONGBOW'),
 ('kraber','sniper','克莱博','Kraber .50-Cal Sniper','克萊博 50 口徑狙擊槍','KRABER'),
 ('sentinel','sniper','哨兵','Sentinel','哨兵','SENTINEL'),
 ('eva8','shotgun','EVA8','EVA-8 Auto','EVA-8 自動','EVA-8'),
 ('mastiff','shotgun','獒犬','Mastiff','獒犬霰彈槍','MASTIFF'),
 ('mozambique','shotgun','莫桑比克','Mozambique Shotgun','莫三比克霰彈槍','MOZAMBIQUE'),
 ('peacekeeper','shotgun','和平使者','Peacekeeper','和平使者','PEACEKEEPER'),
 ('re45','pistol','RE45','RE-45 Auto','RE-45 自動','RE-45'),
 ('p2020','pistol','P2020','P2020','P2020','P2020'),
 ('wingman','pistol','小帮手','Wingman','小幫手','WINGMAN'),
]
EXTRA_ALIASES={
 'havoc':['哈沃克','哈沃克步枪','哈博克','哈博克步枪'],
 'flatline':['VK-47','VK47','VK47平行步枪','平行步枪'],
 'hemlok':['Hemlock','Hemlok Breach AR','Hemlok Breach','汗洛','赫姆洛克','汗洛连发突击步枪'],
 'r301':['R301','R-301','R301卡宾枪'],
 'nemesis':['死敵','死敌','Nemesis','复仇女神','复仇女神连发突击步枪'],
 'alternator':['轉換者','转换者','转换者冲锋枪'],
 'prowler':['獵獸','猎兽','猎兽冲锋枪','猎兽连发个人防卫武器'],
 'r99':['R99','R-99'], 'volt':['電能衝鋒槍','电能冲锋枪','Volt'],
 'car':['CAR','C.A.R.','C.A.R. SMG'],
 'devotion':['專注','专注','专注轻机枪'], 'lstar':['LSTAR','L-STAR'],
 'spitfire':['M600','噴火','喷火','喷火轻机枪'],
 'rampage':['Rampage','狂暴','狂暴轻机枪','暴走','暴走轻机枪'],
 'g7':['G7','G7侦察枪','G7侦察','G7斥候'],
 'triple_take':['TripleTake','三重擊','三重击','三重狙击枪'],
 'repeater3030':['30-30','3030','30-30连发枪','30-30杠杆式步枪'],
 'bocek':['Bocek','Bocek Compound Bow','Bocek Bow','博切克','波塞克','波塞克复合弓','博切克复合弓'],
 'charge_rifle':['ChargeRifle','電能步槍','电能步枪','充能步枪'],
 'longbow':['Longbow','長弓','长弓','长弓精确射手步枪'],
 'kraber':['Kraber','克萊博','克莱博','克雷贝尔','克雷贝尔狙击枪'],
 'sentinel':['哨兵狙击枪'], 'eva8':['EVA8','EVA-8','EVA8自动霰弹枪'],
 'mastiff':['獒犬','獒犬霰弹枪'],
 'mozambique':['莫三比克','莫桑比克','莫三比克霰弹枪','莫桑比克霰弹枪'],
 'peacekeeper':['和平捍卫者','和平使者'],
 're45':['RE45','RE-45','RE-45 Burst','RE45 Burst','RE45自动手枪','RE-45自動'],
 'wingman':['小幫手','小帮手','辅助手枪'],
}
SOURCES=[
 'https://help.ea.com/en/articles/apex-legends/guns-and-weapons/',
 'https://help.ea.com/zh-hant/articles/apex-legends/guns-and-weapons/',
 'https://help.ea.com/zh/articles/apex-legends/guns-and-weapons/',
 'https://www.ea.com/games/apex-legends/apex-legends/news/28-1-designers-notes',
]

def main():
    path=BASE/'weapon-catalog.json'
    old=json.loads(path.read_text(encoding='utf-8'))
    backup=BASE/'weapon-catalog.v1.json'
    if old['version']==1 and not backup.exists(): backup.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
    previous={w['name']:w for w in old['weapons']}
    weapons=[]
    for ident,category,name,en,zh,hud in ROWS:
        aliases=list(dict.fromkeys([name,en,zh,hud]+EXTRA_ALIASES.get(ident,[])))
        record={'id':ident,'name':name,'category':category,'english_name':en,'traditional_name':zh,
                'hud_english':hud,'aliases':aliases,'prototypes':previous.get(name,{}).get('prototypes',[]),
                'calibration_times':previous.get(name,{}).get('calibration_times',[]),
                'real_video_validated':bool(previous.get(name,{}).get('prototypes',[]))}
        if ident in ['p2020','mozambique']: record['variants']=['single','akimbo']
        if ident=='re45': record['variants']=['auto_legacy','burst']
        if ident=='hemlok': record['variants']=['burst','breach']
        weapons.append(record)
    supplements=[
        {'id':'epg1','name':'EPG1','category':'event','aliases':['EPG-1','EPG1'],
         'source':'https://www.ea.com/zh-tw/inside-ea/news/winters-haunt-event'},
        {'id':'sheila','name':'席拉','category':'legend','aliases':['Sheila','席拉','希拉'],
         'source':'https://www.ea.com/games/apex-legends/apex-legends/seasons/marked'},
        {'id':'snipers_mark','name':'狙击标记','category':'legend','aliases':["Sniper's Mark",'Sniper’s Mark','狙击标记','狙擊標記'],
         'source':'https://www.ea.com/en-gb/inside-ea/news/hunted-patch-notes'},
    ]
    catalog={'version':2,'checked_date':'2026-10-08','sources':SOURCES,'base_weapon_count':29,
             'notes':'官方指南29种基础武器；双持和精英变体按基础武器归类。名称识别使用HUD文字，图标模板仅作实拍辅助。',
             'weapons':weapons,'supplemental_weapons':supplements}
    assert len(weapons)==29 and len({w['id'] for w in weapons})==29
    path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    (BASE/'validation'/'sources').mkdir(parents=True,exist_ok=True)
    snapshot={'source':SOURCES[0],'checked_date':'2026-10-08',
              'official_english_weapons':[r[3] for r in ROWS]}
    (BASE/'validation'/'sources'/'ea-weapons-snapshot.json').write_text(json.dumps(snapshot,indent=2),encoding='utf-8')
    print(f'29 base weapons, {sum(bool(w["prototypes"]) for w in weapons)} real-video template sets, 3 supplemental names')

if __name__=='__main__': main()
