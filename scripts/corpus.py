#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把上游 672 条分桶，产出轻量元数据索引。

**关键设计：产物里只有桶号、标签和定位串，没有正文。**
questions.json 只有几十 KB，而上游 items.json 是 2.9 MB —— 这是分层的主要收益。

用法：
    python scripts/corpus.py build              # 建/重建索引
    python scripts/corpus.py build --audit daily
    python scripts/corpus.py stats
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb_adapter                                    # noqa: E402
from model import SEC2DOMAIN, cond_tags              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'corpus.json')
OVERRIDES = os.path.join(ROOT, 'data', 'overrides.json')

BUCKETS = ('daily', 'periodic', 'once', 'event', 'emergency', 'avoid')

# 周期词：只在【标题】里找。全文搜会误判（正文里解释数据常提「每年」）
CYCLE_RULES = [
    (r'每\s*年|一年一?次', 'yearly', '每年'),
    (r'每\s*[两三四五六七八九\d]+\s*个?月|[三四六]个月|半年|每\s*周',
     'months', '每几个月'),
    (r'每\s*[两三四五六七八九\d]+\s*年|[二三四五六七八九2-9]\s*年一?次',
     'multiyear', '每几年'),
    (r'定期|按时', 'periodic', '定期'),
]

EMERGENCY_RULES = [
    r'120|110|119|急救|心肺复苏|止血|压迫止血',
    r'昏迷|抽搐|窒息|溺水|触电|中毒|气道|呛',
    r'立刻去医院|马上去医院|立即就医|当场|第一时间',
    r'自杀|抑郁|12356|喝农药|吸煤气|高处坠落',
]

ONCE_VERBS = ('装', '买', '设', '写', '备', '注册', '办', '存', '签', '过户', '注销',
              '预约', '整理', '清点', '配', '体检', '筛查', '年检', '查一次', '查一遍',
              '绑定', '开具', '申请', '备份', '立好', '核对', '咨询', '检查一次')

EVENT_ONLY_SECS = {7, 9, 10, 12, 13, 16, 17, 19, 21, 24, 25, 26, 27, 29, 31, 32, 33}
HABIT_SECS = {1, 2, 3, 4, 5, 6, 22, 28, 34}


def detect_cycle(title):
    for pat, key, label in CYCLE_RULES:
        m = re.search(pat, title)
        if m:
            return key, label, m.group(0)
    return None, None, None


def first_match(rules, text):
    for p in rules:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None


def weight_of(item):
    """追问权重：证据等级 × 性价比。排序和覆盖度加权都用它。"""
    lw = {'A': 1.0, 'B': 0.7, 'C': 0.45}.get(item.get('level'), 0.4)
    rw = {'极高': 3.0, '高': 2.0, '一般': 1.0}.get(item.get('ratio'), 1.0)
    return round(lw * rw, 3)


def classify(it, ov):
    key = f"{it['sec']}.{it['no']}"
    title = it['title']
    tag = it.get('tag') or {}
    plain = it.get('plain', '')

    if key in ov:
        return ov[key]['bucket'], ov[key].get('reason', '人工指定')

    if first_match(EMERGENCY_RULES, title) or first_match(EMERGENCY_RULES, plain[:60]):
        return 'emergency', '急救/危机措辞，先救命不算账'

    if re.match(r'^(不要|别|勿|不能|禁止|避免|不)', title):
        return 'avoid', '标题是禁令，推荐时挡掉'

    _, label, hit = detect_cycle(title)
    if label:
        return 'periodic', f'标题带周期词「{hit}」→ {label}'

    from model import COND_TAGS
    cond = next((lbl for pat, lbl in COND_TAGS if re.search(pat, title)), None)
    if cond:
        return 'event', f'限定人群「{cond}」，需条件成立才启用'

    if it['sec'] in EVENT_ONLY_SECS:
        return 'event', f"第 {it['sec']} 节属条件触发场景，被问到时再检索"

    if (tag.get('毅力') in ('否', '些') and tag.get('收益') == '大'
            and tag.get('时间') in ('少', '中') and tag.get('钱') in ('0', '少')
            and it['sec'] in HABIT_SECS
            and not any(v in title for v in ONCE_VERBS)):
        return 'daily', '成本低 + 收益大 + 可每日重复'

    verb = next((v for v in ONCE_VERBS if v in title), None)
    if verb:
        return 'once', f'标题含一次性动作「{verb}」'

    if it.get('ratio') == '极高':
        return 'once', '极高性价比但不适合每日重复'
    return 'event', '条件触发或不适合按日追踪'


def build():
    kb = kb_adapter.load_items()
    ov_path = OVERRIDES if os.path.exists(OVERRIDES) else \
        os.path.join(HERE, 'default_overrides.json')
    overrides = {}
    if os.path.exists(ov_path):
        with open(ov_path, encoding='utf-8') as f:
            overrides = json.load(f)
        overrides = {k: v for k, v in overrides.items() if not k.startswith('_')}

    buckets = {b: [] for b in BUCKETS}
    for it in kb['items']:
        bucket, rule = classify(it, overrides)
        _, cyc_label, _ = detect_cycle(it['title'])
        buckets[bucket].append({
            'key': f"{it['sec']}.{it['no']}",
            'sec': it['sec'],
            'no': it['no'],
            'title': it['title'],
            'level': it.get('level', ''),
            'ratio': it.get('ratio', ''),
            'caliber': (it.get('tag') or {}).get('口径', ''),
            'cost': {'钱': (it.get('tag') or {}).get('钱', ''),
                     '时间': (it.get('tag') or {}).get('时间', ''),
                     '毅力': (it.get('tag') or {}).get('毅力', '')},
            'domain': SEC2DOMAIN.get(it['sec'], 'other'),
            'cycle': cyc_label,
            'cond': cond_tags(it),
            'weight': weight_of(it),
            'dispute': bool(it.get('dispute')),
            'todo': bool(it.get('todo')),
            'rule': rule,
        })

    payload = {
        'schema': 3,
        # 只记上游仓库名，不写绝对路径 —— 换机器/换目录后索引依然有效。
        # 实际路径由 kb_adapter 运行时探测（9 条候选 + LIFEOS_KB_PATH）。
        'upstream_repo': 'how-to-live-better',
        'upstream_index': 'data/items.json',
        'upstream_license': 'CC BY 4.0 (eternity4719/HowToLiveBetter)',
        'built_at': dt.datetime.now().isoformat(timespec='seconds'),
        'note': '本文件只含元数据，不含正文。'
                '需要条目详情时用 kb_adapter.get_item() 取，'
                '上游实际路径由 kb_adapter 运行时探测。',
        'total': sum(len(v) for v in buckets.values()),
        'buckets': buckets,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return payload


def load():
    if not os.path.exists(OUT):
        sys.exit('corpus.json 不存在，先跑：python scripts/corpus.py build')
    with open(OUT, encoding='utf-8') as f:
        return json.load(f)


def audit(bucket, limit=30):
    c = load()
    arr = sorted(c['buckets'].get(bucket, []), key=lambda x: -x['weight'])
    print(f'\n===== {bucket} ({len(arr)}) =====')
    for x in arr[:limit]:
        flag = ' [争议]' if x['dispute'] else ''
        print(f"  {x['key']:<7} w={x['weight']:<5} [{x['domain']:<6}] "
              f"{x['title'][:42]}{flag}")
        print(f"          依据：{x['rule']}")


def audit_item(key):
    """单条：为什么进了这个桶 —— 排查分类错误用。"""
    c = load()
    meta = next((x for arr in c['buckets'].values() for x in arr
                 if x['key'] == key), None)
    if not meta:
        print(f'{key} 不在索引里')
        return
    print(f"{meta['key']}  {meta['title']}")
    print(f"桶          {find_bucket(c, key)}")
    print(f"生活域      {meta['domain']}")
    print(f"口径        {meta['caliber']}")
    print(f"等级/性价比 {meta['level']} / {meta['ratio']}  权重 {meta['weight']}")
    if meta['cond']:
        print(f"人群限定    {meta['cond']}   ← 画像未确认时 strict 模式会拦下")
    if meta['dispute']:
        print('争议        书里标注有争议，别当定论')
    print(f"分类依据    {meta['rule']}")

    ov = load_overrides()
    if key in ov:
        print(f"人工裁决    {ov[key].get('reason', '(无说明)')}")


def find_bucket(c, key):
    for b, arr in c['buckets'].items():
        if any(x['key'] == key for x in arr):
            return b
    return '?'


def load_overrides():
    import json as _json
    p = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'data', 'overrides.json')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as f:
        return _json.load(f)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['build', 'audit', 'stats'])
    ap.add_argument('--audit', dest='audit_bucket',
                    help='按桶审计，如 --audit daily')
    ap.add_argument('--item', help='审计单条，如 --item 18.2')
    ap.add_argument('-k', type=int, default=30)
    args = ap.parse_args()

    if args.cmd == 'build':
        p = build()
        size = os.path.getsize(OUT) / 1024
        print(f'已写出 {OUT}（{size:.0f} KB）')
        print(f'上游 {kb_adapter.kb_root()}')
        for b, arr in p['buckets'].items():
            print(f'  {b:<10} {len(arr):>4} 条')
    elif args.cmd == 'audit':
        if args.item:
            audit_item(args.item)
        else:
            audit(args.audit_bucket or 'daily', args.k)
    else:
        kb = kb_adapter.kb_stats()
        c = load()
        print(json.dumps({
            'upstream': kb,
            'corpus_kb': os.path.getsize(OUT) / 1024,
            'corpus_items': c['total'],
            'buckets': {b: len(a) for b, a in c['buckets'].items()},
        }, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()