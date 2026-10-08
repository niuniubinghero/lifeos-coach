#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日出题调度。

出题是**确定性**的：同一天重复调用必给同一条，不同日期轮换。
原因是自动化任务可能重试，也可能用户在同一天问两次 —— 非确定性会导致
「今天问了两遍不同的题」，体验很差。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus                                        # noqa: E402
import kb_adapter                                    # noqa: E402
import store                                         # noqa: E402
from model import CALIBER_LABEL, DOMAIN_BY_ID, is_applicable   # noqa: E402

BASE_DATE = dt.date(2026, 1, 1)
POOL_SIZE = 18          # 轮换池大小
WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def today_question(date=None, force_rotate=False):
    """取今天该问的那一条。返回完整可直接提问的 dict。"""
    c = corpus.load()
    prof = store.get_profile()
    d = date or dt.date.today()

    pool = []
    for it in c['buckets']['daily']:
        ok, _ = is_applicable(it, prof, strict=True)
        if ok:
            pool.append(it)
    if not pool:                      # 画像没确认太多，全部放行兜底
        pool = list(c['buckets']['daily'])

    pool.sort(key=lambda x: (-x['weight'], x['key']))
    pool = pool[:POOL_SIZE] if len(pool) > POOL_SIZE else pool

    idx = (d - BASE_DATE).days % len(pool)
    if force_rotate:
        idx = (idx + 1) % len(pool)
    meta = pool[idx]

    # 条目详情现场从上游取 —— lifeos 本地不存正文
    full = kb_adapter.get_item(meta['key']) or {}

    return {
        'date': d.isoformat(),
        'weekday': WEEKDAYS[d.weekday()],
        'key': meta['key'],
        'cite': f"第 {meta['sec']} 节第 {meta['no']} 条",
        'sec_name': full.get('sec_name', ''),
        'title': meta['title'],
        'domain': meta['domain'],
        'domain_name': DOMAIN_BY_ID.get(meta['domain'], {}).get('name', ''),
        'caliber': CALIBER_LABEL.get(meta['caliber'], meta['caliber']),
        'level': meta['level'],
        'ratio': meta['ratio'],
        'dispute': meta['dispute'],
        'ask': meta['title'],
        'plain': (full.get('plain') or '')[:160],
        'cost': full.get('cost', ''),
        'why': (full.get('benefit') or '')[:220],
        'note': (full.get('note') or '')[:300],
        'pool_size': len(pool),
        'answered_today': _answered_on(d),
        'last_asked': store.load_json('state.json', {}).get('last_asked'),
    }


def _answered_on(d):
    """今天是否已经回答过（不是「问过」，是「答了」）。"""
    return any(e.get('date') == d.isoformat()
               for e in store.read_events('daily.jsonl'))


def mark_asked(key):
    """记录「今天问了哪条」—— 出题是幂等的，问多少次同一条都是同一条。"""
    st = store.load_json('state.json', {})
    st['last_asked'] = {'date': store.today(), 'key': key, 'ts': store.now()}
    store.save_json('state.json', st)


def due_periodic(as_of=None, limit=12):
    """到期需要复查的周期项。"""
    c = corpus.load()
    prof = store.get_profile()
    done = store.done_once()
    as_of = as_of or dt.date.today()

    last = {}
    for e in store.read_events('daily.jsonl'):
        if e.get('key'):
            last[e['key']] = e.get('date')

    DAYS = {'每年': 365, '每几个月': 120, '每几年': 1095, '定期': 180}
    rows = []
    for it in c['buckets']['periodic']:
        ok, why = is_applicable(it, prof, strict=True)
        if not ok:
            continue
        d = last.get(it['key'])
        if it['key'] in done:
            if not d:
                continue
            try:
                gap = (as_of - dt.date.fromisoformat(d)).days
            except ValueError:
                continue
            if gap <= DAYS.get(it.get('cycle'), 365):
                continue
            rows.append({'key': it['key'], 'title': it['title'],
                         'cite': f"第 {it['sec']} 节第 {it['no']} 条",
                         'cycle': it.get('cycle'), 'state': '超期',
                         'last_done': d, 'days': gap})
        else:
            rows.append({'key': it['key'], 'title': it['title'],
                         'cite': f"第 {it['sec']} 节第 {it['no']} 条",
                         'cycle': it.get('cycle'), 'state': '待办',
                         'last_done': None, 'days': None})
    rows.sort(key=lambda r: (r['state'] == '待办', r['key']))
    return rows[:limit]