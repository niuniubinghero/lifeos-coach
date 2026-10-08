#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评分器：八域覆盖度 + 四口径 + 优先级清单。

三个视角同时算，但**不合成总分** —— 书里明确把寿命、时间、金钱、自由
四样分开算，不互相折算。
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus                                        # noqa: E402
import decisions as dec                               # noqa: E402
import store                                         # noqa: E402
from model import (CALIBERS, CALIBER_LABEL, DOMAINS,  # noqa: E402
                   is_applicable)

# 计入「待办」口径的桶：event/avoid/emergency 不是日常该做的事
TODO_BUCKETS = ('daily', 'periodic', 'once')
ALL_BUCKETS = ('daily', 'periodic', 'once', 'event', 'emergency', 'avoid')

STATUS_THRESH = ((0.6, '领先'), (0.35, '达标'), (0.0, '落后'))


def _status(cov):
    for th, name in STATUS_THRESH:
        if cov >= th:
            return name
    return '落后'


def actionable_items(c, prof, strict=True):
    """当前应该推进的条目：分桶口径内的、已通关的、可用的。"""
    done = store.done_once()
    answered = store.answered_keys()
    out = []
    for b in TODO_BUCKETS:
        for it in c['buckets'].get(b, []):
            ok, _ = is_applicable(it, prof, strict=strict)
            if not ok:
                continue
            out.append((b, it, it['key'] in done or it['key'] in answered))
    return out


def score(as_of=None):
    c = corpus.load()
    prof = store.get_profile()
    done = store.done_once()
    answered = store.answered_keys()
    as_of = as_of or dt.date.today()

    pool = actionable_items(c, prof, strict=True)

    # ---- 1) 八域覆盖度
    # total 只数「可行动桶」（daily/periodic/once），但要同时给出该域全库条目数，
    # 否则像「消费与避坑」这种几乎全在 avoid 桶的域会显示 total=1，看着像 bug。
    kb_by_domain = {}
    for b in ALL_BUCKETS:
        for it in c['buckets'].get(b, []):
            kb_by_domain[it['domain']] = kb_by_domain.get(it['domain'], 0) + 1

    domains = []
    for d in DOMAINS:
        items = [it for _, it, _ in pool if it['domain'] == d['id']]
        if not items:
            continue
        tot = sum(it['weight'] for it in items)
        got = sum(it['weight'] for it in items
                  if it['key'] in done or it['key'] in answered)
        cov = got / tot if tot else 0
        remaining = sorted([it for it in items if it['key'] not in done],
                           key=lambda x: -x['weight'])
        domains.append({
            'id': d['id'], 'name': d['name'], 'desc': d['desc'],
            'total': len(items), 'done': len(items) - len(remaining),
            'kb_total': kb_by_domain.get(d['id'], 0),
            'coverage': round(cov, 3), 'status': _status(cov),
            'top_gap': remaining[0]['key'] if remaining else None,
            'top_gap_title': remaining[0]['title'] if remaining else None,
        })

    # ---- 2) 四口径，各自独立
    calibers = {}
    for cal in CALIBERS:
        items = [it for _, it, _ in pool if it['caliber'] == cal]
        if not items:
            continue
        tot = sum(it['weight'] for it in items)
        got = sum(it['weight'] for it in items
                  if it['key'] in done or it['key'] in answered)
        calibers[cal] = {
            'label': CALIBER_LABEL[cal],
            'total_items': len(items),
            'score': round(got / tot, 3) if tot else 0,
            'high_value_pending': sum(1 for it in items
                                      if it['weight'] >= 2.0
                                      and it['key'] not in done),
        }

    # ---- 3) 优先级清单
    pending = sorted([it for _, it, hit in pool if not hit],
                     key=lambda x: (-x['weight'], x['key']))

    stats_ = {
        'answers_total': len(store.read_events('daily.jsonl')),
        'days_answered': len({e['date'] for e in store.read_events('daily.jsonl')}),
        'streak': store.streak(as_of),
        'decisions_total': len(dec.replay()),
        'once_done': len(done),
        'once_total': len(c['buckets']['once']),
        'profile_ready': bool(prof.get('basic') or prof.get('work')),
    }
    stats_['sample_warning'] = (
        None if stats_['answers_total'] >= 7
        else f"只有 {stats_['answers_total']} 条回答，评分先当参考，"
             f"7 条以上再看覆盖率")

    return {
        'as_of': as_of.isoformat(),
        'domains': domains,
        'calibers': calibers,
        'priority': [{
            'key': it['key'], 'title': it['title'],
            'cite': f"第 {it['sec']} 节第 {it['no']} 条",
            'domain': it['domain'], 'ratio': it['ratio'], 'level': it['level'],
            'caliber': CALIBER_LABEL.get(it['caliber'], it['caliber']),
            'weight': it['weight'], 'cost': it['cost'],
        } for it in pending[:10]],
        'stats': stats_,
    }


def domain_detail(domain_id, strict=False):
    """某个生活域的全部条目。默认不过滤，给人看全貌。"""
    c = corpus.load()
    prof = store.get_profile()
    done = store.done_once()
    answered = store.answered_keys()
    d = next((x for x in DOMAINS if x['id'] == domain_id), None)
    if not d:
        return None
    rows = []
    for b in TODO_BUCKETS:
        for it in c['buckets'].get(b, []):
            if it['domain'] != domain_id:
                continue
            ok, why = is_applicable(it, prof, strict=strict)
            if not ok and strict:
                continue
            rows.append((b, it, ok, why))
    rows.sort(key=lambda x: -x[1]['weight'])
    return {'domain': d, 'items': rows,
            'done': len(done), 'answered': answered}


def unresolved_domains(prof):
    """画像里还没确认的人群域 —— 这些域的条目暂不主动推荐。"""
    c = corpus.load()
    hit = set()
    for b in TODO_BUCKETS:
        for it in c['buckets'].get(b, []):
            if it['cond']:
                ok, why = is_applicable(it, prof, strict=True)
                if not ok and any('未确认' in w for w in why):
                    hit.add(it['domain'])
    return hit