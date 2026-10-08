#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决策闭环。

这是原书和检索工具都给不了的东西：书里 672 条是**通用建议**，
但一个人真正要面对的是「当时那个决定，后来怎么样了」。

闭环三步：
  1. decide   做决策时记下：处境、判断、依据、置信度、复查点
  2. review   到复查点回来问一句「后来怎么样了」，记录结果
  3. calibrate 长期下来，统计你的决策倾向（见 calibration 函数）

第3 步是真正有价值的部分：
  * 你历史上决策的对错分布
  * 高置信度决策的实际命中率（校准度 —— 会不会系统性过度自信）
  * 哪类事项你判断得更准（哪类该多信自己）
  * 哪些决定你反复在同一件事上栽跟头
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store                                            # noqa: E402

# 决策类型：用于统计「哪类判断准」
DECISION_KINDS = {
    'health': '健康与习惯', 'money': '钱与大额支出',
    'career': '职业与学习', 'family': '家庭与关系',
    'legal': '法律与合规', 'home': '居住与搬家', 'other': '其他',
}

# 复查点预设：不同类型多久回来看一次
REVIEW_DAYS = {
    'health': 30, 'money': 90, 'career': 180,
    'family': 90, 'legal': 60, 'home': 180, 'other': 90,
}


def decide(title, decision, kind='other', confidence=None,
           basis=None, review_at=None, context=None, tags=None):
    """记一条决策。

    kind        决策类型，见 DECISION_KINDS
    confidence  当时有多大把握（0-100，可空）。空的话不算进校准度统计
    basis       依据（通常是「第X节第Y条」）
    review_at   复查日期，默认按 kind 预设自动推算
    context     当时的具体处境（几个月后回看，这是最有信息量的部分）
    """
    d = dt.date.today()
    if not review_at:
        days = REVIEW_DAYS.get(kind, 90)
        review_at = (d + dt.timedelta(days=days)).isoformat()
    # did 稳定标识：同一天可能记多条决策，不能用日期当主键
    did = f"{d.isoformat()}#{len(store.read_events('decisions.jsonl')) + 1:03d}"
    ev = {
        'ts': store.now(),
        'did': did,
        'date': store.today(d),
        'kind': kind,
        'title': title,
        'decision': decision,
        'context': context,
        'confidence': confidence,
        'basis': basis,
        'review_at': review_at,
        'outcome': None,          # 由 close 事件补充
        'verdict': None,          # 由 close 事件补充
    }
    store.append_event('decisions.jsonl', ev)
    return ev


def due_reviews(within_days=0, as_of=None):
    """到期该复查的决策。"""
    as_of = as_of or dt.date.today()
    limit = (as_of + dt.timedelta(days=within_days)).isoformat()
    out = []
    for e in replay():
        if e.get('verdict') or not e.get('review_at'):
            continue
        if e['review_at'] <= limit:
            out.append(e)
    out.sort(key=lambda x: x['review_at'])
    return out


def close(decision_date, outcome, verdict=None, title=None):
    """回填对账结果。

    verdict: right（当初判断对） / partial（部分对） / wrong（判断错）
             不填的话按 outcome 粗判，判不准就返回 None 让用户自己说

    只追加一条 close 事件，**不改原行** —— 这是事件溯源的基本约束。
    """
    events = replay()
    hit = None
    for e in events:
        if e.get('verdict'):
            continue
        if decision_date and e.get('date') != decision_date:
            continue
        if title and title not in e.get('title', ''):
            continue
        hit = e
        break
    if not hit:
        return None

    if verdict is None:
        verdict = _guess_verdict(hit.get('decision', ''), outcome)

    store.append_event('decisions.jsonl', {
        'ts': store.now(), 'date': store.today(),
        'did': hit['did'], 'kind': hit.get('kind', 'other'), 'event': 'close',
        'outcome': outcome, 'verdict': verdict,
    })
    hit = dict(hit)
    hit['outcome'] = outcome
    hit['verdict'] = verdict
    hit['closed_at'] = store.now()
    return hit


def _guess_verdict(decision_text, outcome_text):
    """没有明确 verdict 时，按文本相似度粗判。判不准就返回 None 让用户自己说。"""
    if not outcome_text:
        return None
    neg = ('后悔', '不该', '亏', '不值', '错了', '没选', '不该选', '遗憾', '不好')
    pos = ('值', '赚', '好', '顺利', '不错', '满意', '对', '有用', '值得')
    o = outcome_text
    if any(w in o for w in neg):
        return 'wrong'
    if any(w in o for w in pos):
        return 'right'
    return None


def replay():
    """重放决策事件流，合并出每个决策的最终状态。

    decisions.jsonl 里 decide 和 close 是分开的行（只追加，不改写），
    统计前必须合并：decide 提供基础信息，后续 close 覆盖 verdict/outcome。
    合并键是 decide 时生成的 did（不能用 date —— 同一天可能记多条）。
    """
    merged = {}
    order = []
    for e in store.read_events('decisions.jsonl'):
        if e.get('event') == 'close':
            ref = merged.get(e.get('did'))
            if ref is not None:
                ref['outcome'] = e.get('outcome')
                ref['verdict'] = e.get('verdict')
                ref['closed_at'] = e.get('ts')
            continue
        if e.get('verdict') is not None and 'review_at' not in e:
            continue                     # 早期版本原地改写的行，忽略
        did = e.get('did')
        if did:
            merged[did] = dict(e)
            order.append(did)
    return [merged[k] for k in order if k in merged]


def calibration(as_of=None):
    """决策倾向校准度 —— 真正属于用户个人的那一层。

    重点不是「对了几次」，而是：
      * 整体对错分布
      * 按类型看：哪类事项判断得准
      * 校准度：说 90% 有把握的，实际对的比例是不是 90%
      * 待复查积压：有多少决策还没对账（积压越多越不可信）
    """
    events = replay()
    closed = [e for e in events if e.get('verdict')]
    today = store.today(as_of)
    pending = [e for e in events
               if not e.get('verdict') and e.get('review_at')
               and e['review_at'] <= today]

    dist = {'right': 0, 'partial': 0, 'wrong': 0}
    for e in closed:
        v = e.get('verdict')
        if v in dist:
            dist[v] += 1

    by_kind = {}
    for e in closed:
        k = e.get('kind', 'other')
        by_kind.setdefault(k, {'right': 0, 'partial': 0, 'wrong': 0, 'n': 0})
        by_kind[k]['n'] += 1
        if e.get('verdict') in dist:
            by_kind[k][e['verdict']] += 1
    for k, v in by_kind.items():
        decided = v['right'] + v['wrong']
        v['hit_rate'] = round(v['right'] / decided, 2) if decided else None
        v['label'] = DECISION_KINDS.get(k, k)

    # 校准度：把预测置信度分档，看实际命中率
    buckets = {}
    for e in closed:
        c = e.get('confidence')
        if c is None:
            continue
        band = ('high' if c >= 70 else 'mid' if c >= 40 else 'low')
        b = buckets.setdefault(band, {'conf': [], 'right': 0, 'decided': 0})
        b['conf'].append(c)
        if e.get('verdict') in ('right', 'wrong'):
            b['decided'] += 1
            if e['verdict'] == 'right':
                b['right'] += 1
    calib = {}
    for band, b in buckets.items():
        if not b['decided']:
            continue
        avg_conf = round(sum(b['conf']) / len(b['conf']))
        actual = round(b['right'] / b['decided'], 2)
        calib[band] = {
            'avg_confidence': avg_conf,
            'actual_hit_rate': actual,
            'gap': round(actual - avg_conf / 100, 2),
            'n': b['decided'],
            'verdict': ('过于自信' if actual < avg_conf / 100 - 0.15 else
                        '偏保守' if actual > avg_conf / 100 + 0.15 else
                        '校准良好'),
        }

    return {
        'total_decisions': len(events),
        'closed': len(closed),
        'pending_review': len(pending),
        'pending_list': [{'date': e['date'], 'title': e['title'],
                          'review_at': e['review_at'],
                          'days_overdue': (dt.date.today() -
                                           dt.date.fromisoformat(e['review_at'])).days
                          if as_of is None else 0}
                         for e in pending[:8]],
        'verdict_dist': dist,
        'hit_rate': round(dist['right'] / (dist['right'] + dist['wrong']), 2)
                    if dist['right'] + dist['wrong'] else None,
        'by_kind': by_kind,
        'calibration': calib,
        'sample_warning': (None if len(closed) >= 10 else
                           f'样本只有 {len(closed)} 条，以下统计只能当参考，'
                           f'至少 10 条闭环后才有意义'),
    }


def stats(as_of=None):
    return calibration(as_of)