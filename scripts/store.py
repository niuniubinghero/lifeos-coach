#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""档案层：事件溯源存储。

设计原则：
  * 一切都是事件，只追加，永不改写。用户改主意就再记一条。
  * 派生状态（画像、评分）从事件流重放算出，不单独维护 —— 不会有"对不上"的问题。
  * 档案目录在 git 仓库外：%USERPROFILE%\\.workbuddy\\lifeos\\（可用 LIFEOS_HOME 改）

文件：
  profile.json     画像事实（唯一允许改写的，因为是用户直接输入的事实，不是事件）
  daily.jsonl      每日回答
  decisions.jsonl  决策记录（含复查点与对账结果）
  state.json       出题游标
"""
import datetime as dt
import json
import os

HOME = os.environ.get('LIFEOS_HOME') or os.path.join(
    os.path.expanduser('~'), '.workbuddy', 'lifeos')

# 画像字段定义。分批问询按这个顺序来。
PROFILE_SCHEMA = {
    'basic': {
        'label': '基本情况', 'required': ['age'],
        'fields': {
            'age': '年龄（岁）', 'gender': '性别', 'city': '城市',
            'household': '家庭结构（独居/两人/有孩/与父母同住…）',
        },
    },
    'work': {
        'label': '工作与收入', 'required': ['occupation'],
        'fields': {
            'occupation': '职业',
            'employer_type': '单位类型（国企/私企/外企/自由职业/学生）',
            'income_range': '月收入区间',
            'income_stability': '收入稳定性（波动大/一般/稳定）',
            'work_hours': '每周工作小时数',
            'commute_min': '单程通勤分钟数',
            'dependents': '有没有人靠你的收入生活',
        },
    },
    'money': {
        'label': '资产与负债', 'required': [],
        'fields': {
            'savings_months': '存款能覆盖几个月生活开支',
            'debt': '负债情况（房贷/车贷/网贷/信用卡…）',
            'debt_monthly': '每月还款额',
            'insurance': '已买的保险（医保/商保/寿险…）',
            'housing': '住房（自有/租/宿舍/与家人同住）',
        },
    },
    'health': {
        'label': '健康', 'required': [],
        'fields': {
            'chronic': '慢性病（无/有哪些）',
            'smoking': '吸烟情况', 'drinking': '饮酒情况',
            'exercise': '运动习惯', 'sleep': '平均睡眠时长',
            'bmi': '身高体重', 'meds': '长期在吃的药',
        },
    },
    'family': {
        'label': '家庭责任', 'required': [],
        'fields': {
            'children': '孩子（年龄/阶段）', 'elderly': '需要照看的老人',
            'pregnant': '是否备孕/孕期', 'caregiver': '是否在照顾病患',
        },
    },
    'state': {
        'label': '当前处境', 'required': [],
        'fields': {
            'recent_events': '最近发生的大事（失业/搬家/重大支出…）',
            'pressure': '当前压力来源',
            'goal_90d': '接下来 90 天最想改的一件事',
        },
    },
}

ALL_FIELDS = {f: (grp, spec['fields'][f])
              for grp, spec in PROFILE_SCHEMA.items()
              for f in spec['fields']}


def ensure_home():
    os.makedirs(HOME, exist_ok=True)
    return HOME


def path(*parts):
    return os.path.join(HOME, *parts)


def now():
    return dt.datetime.now().isoformat(timespec='seconds')


def today(d=None):
    return (d or dt.date.today()).isoformat()


def load_json(name, default):
    p = path(name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


def save_json(name, obj):
    ensure_home()
    with open(path(name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def append_event(name, obj):
    """追加一条事件。这是唯一允许写档案的方式。"""
    ensure_home()
    with open(path(name), 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def read_events(name):
    p = path(name)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def init():
    ensure_home()
    save_json('profile.json', load_json('profile.json', {}))
    save_json('state.json', load_json('state.json', {}))
    for n in ('daily.jsonl', 'decisions.jsonl'):
        if not os.path.exists(path(n)):
            open(path(n), 'w', encoding='utf-8').close()
    return HOME


# ---------------------------------------------------------------- 画像
def set_profile(pairs):
    prof = load_json('profile.json', {})
    for k, v in pairs.items():
        if k.startswith('skip:'):
            grp = 'extra'
        elif k in ALL_FIELDS:
            grp = ALL_FIELDS[k][0]
        else:
            grp = 'extra'
        prof.setdefault(grp, {})[k] = str(v)
    prof['updated_at'] = now()
    save_json('profile.json', prof)
    return prof


def get_profile():
    return load_json('profile.json', {})


def profile_summary():
    """画像完成度：哪些还没填，下一个该问哪个。"""
    prof = get_profile()
    missing = []
    for grp, spec in PROFILE_SCHEMA.items():
        for f, label in spec['fields'].items():
            if not (prof.get(grp) or {}).get(f):
                missing.append({'group': grp, 'group_label': spec['label'],
                                'field': f, 'label': label,
                                'required': f in spec['required']})
    return {
        'home': HOME,
        'has_profile': bool(prof.get('basic') or prof.get('work')),
        'filled': sum(1 for m in missing if not m['required']),
        'missing_total': len(missing),
        'missing': missing,
        'next_ask': next((m for m in missing if m['required']), None),
    }


# ---------------------------------------------------------------- 派生状态
def answered_keys():
    """所有被回答过的条目号。"""
    return {e['key'] for e in read_events('daily.jsonl') if e.get('key')}


def done_once():
    """一次性通关清单：只认 --complete 标记，写在 state.json 里。

    决策事件流不带 completed_item 字段（决策和通关清单是两件事），
    这里刻意不扫 decisions.jsonl，避免把「做过某个决策」误算成
    「通关了某条一次性条目」。
    """
    return set(load_json('state.json', {}).get('completed_once', {}).keys())


def mark_done(key):
    st = load_json('state.json', {})
    st.setdefault('completed_once', {})[key] = now()
    save_json('state.json', st)


def streak(as_of=None):
    """连续答题天数。"""
    days = {e['date'] for e in read_events('daily.jsonl') if e.get('date')}
    if not days:
        return 0
    d = as_of or dt.date.today()
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= dt.timedelta(days=1)
    return n