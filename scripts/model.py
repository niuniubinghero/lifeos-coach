#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生活域定义与人群适用性判定。

从 34 节归纳 8 个生活域；人群限定标签从标题和正文里抽（只看标题会漏，
18.2 标题是「产假 98 天」，「生孩子」写在 plain 里）。
"""
import re

DOMAINS = [
    {'id': 'life', 'name': '生命与安全', 'secs': [1, 13, 14],
     'desc': '不出意外、救命时会做、账号身份不被别人拿走。'},
    {'id': 'health', 'name': '健康与身体', 'secs': [2, 16, 28, 33, 34],
     'desc': '不慢慢折损，吃药、减重、常备药这些事不被做错。'},
    {'id': 'energy', 'name': '精力与时间', 'secs': [3, 4, 29],
     'desc': '同样的时间产出更多，不把清醒时候耗在没收益的事上。'},
    {'id': 'money', 'name': '钱与资产', 'secs': [5, 7],
     'desc': '钱放着不缩水、该领的领到、亏钱的地方不踩。'},
    {'id': 'spend', 'name': '消费与避坑', 'secs': [6, 22],
     'desc': '不交智商税，娱乐放松不踩安全与法律红线。'},
    {'id': 'law', 'name': '法律与职场', 'secs': [8, 9, 11, 19],
     'desc': '不踩刑事红线，被动到的事（被裁、工伤、被举报）知道怎么办。'},
    {'id': 'family', 'name': '家庭与关系', 'secs': [10, 17, 18, 20, 27, 30],
     'desc': '伴侣、父母、孩子相关的取舍与安排。'},
    {'id': 'growth', 'name': '成长与出路', 'secs': [12, 21, 23, 24, 25, 26, 31, 32],
     'desc': '学什么、去哪干、看病怎么少花钱、人生下一步怎么选。'},
]
SEC2DOMAIN = {s: d['id'] for d in DOMAINS for s in d['secs']}
DOMAIN_BY_ID = {d['id']: d for d in DOMAINS}

# 书把要换回的东西分成四样，明确分开算不互相折算
CALIBERS = ['死亡率', '时间', '金钱', '自由']
CALIBER_LABEL = {
    '死亡率': '寿命与健康',
    '时间': '时间与精力',
    '金钱': '金钱',
    '自由': '人身自由与安全',
}

# 人群限定 -> 画像里的对应字段
COND_TAGS = [
    (r'生孩子|产假|生育津贴|怀孕|孕期|产后|哺乳|孕妇|备孕', 'pregnant'),
    (r'新生儿|婴儿期|幼儿期|孩子出生|婴幼儿|喂奶', 'children'),
    (r'孩子|儿童|小学生|中学生|学生体检|家长会|托育', 'children'),
    (r'老人|老年人|父母|照看|监护|遗嘱', 'elderly'),
    (r'\d+\s*岁(以上|以后|起)', 'age'),
    (r'残障|残疾|瘫痪|重病|病患|长期卧床', 'caregiver'),
    (r'开车|驾驶|私家车|车主', 'drive'),
    (r'骑摩托车|电动车|电动自行车|头盔', 'ride'),
    (r'程序|代码|服务器|接单|外包|副业|兼职', 'techworker'),
    (r'当兵|退役|服兵役|应征|军龄', 'veteran'),
]

# 这些字段在画像里填了「有/是/具体值」才算适用
COND_FIELDS = ('children', 'elderly', 'pregnant', 'caregiver')

NONE_WORDS = {'无', '没有', '不', '否', '0', '不适用', 'none', 'no', 'n/a', ''}


def cond_tags(item):
    """抽取人群限定标签。标题 + 正文前 80 字。"""
    if item.get('cond') is not None:
        return item['cond']
    text = item.get('title', '') + ' ' + item.get('plain', '')[:80]
    return [label for pat, label in COND_TAGS if re.search(pat, text)]


def flatten_profile(prof):
    """把分组画像摊平成 {字段: 值}，统一小写去空格。"""
    out = {}
    for grp in ('basic', 'work', 'money', 'health', 'family', 'state', 'extra'):
        for k, v in (prof.get(grp) or {}).items():
            out[k] = str(v).strip().lower()
    return out


def is_applicable(item, prof, strict=True):
    """这条条目适不适合推荐给当前用户。

    strict=True（主动推荐场景）：人群限定条目在画像未确认前一律不推。
    「没填孩子」不等于「没有孩子」，宁可漏推不误推。
    strict=False（用户主动问 / 查看全貌）：照常返回。

    返回 (bool, 原因列表)
    """
    tags = cond_tags(item)
    if not tags:
        return True, []

    flat = flatten_profile(prof)

    skipped = {k[5:] for k in flat if k.startswith('skip:')}
    if item.get('key') in skipped:
        return False, ['用户已标记不适用']

    blocked, unknown = [], []
    for t in tags:
        if t == 'age':
            continue                      # 年龄条件交给用户自己判断
        if t not in COND_FIELDS:
            continue                      # 职业/驾驶类不构成排除依据
        val = flat.get(t, '')
        if val == '':
            unknown.append(t)
        elif val in NONE_WORDS:
            blocked.append(t)
    if blocked:
        return False, ['画像显示不适用：' + ','.join(blocked)]
    if unknown and strict:
        return False, ['画像未确认（' + ','.join(unknown) + '），先问用户再推']
    return True, []