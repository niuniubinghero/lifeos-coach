#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lifeos —— 高性价比生活教练。统一命令行入口。

    lifeos doctor                 检查环境与知识库连通性
    lifeos ask                    取今天该问的问题
    lifeos answer <条目号> "回答"   记录回答
    lifeos decide "标题" "决定"     记录决策（自动推算复查点）
    lifeos close <日期> "结果"      给到期决策对账
    lifeos review-due             列出到期该复查的决策
    lifeos calibrate              决策倾向校准度
    lifeos find 关键词             检索条目（转发上游）
    lifeos profile --set k=v      画像
    lifeos score                  三视角评分
    lifeos domain <域id>          看某生活域
    lifeos due                    到期复查项
    lifeos weekly / monthly       复盘
    lifeos export                 导出 Markdown 档案
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus                                        # noqa: E402
import decisions as dec                              # noqa: E402
import kb_adapter                                    # noqa: E402
import scheduler                                     # noqa: E402
import scorer                                        # noqa: E402
import store                                         # noqa: E402
from model import CALIBER_LABEL, DOMAINS             # noqa: E402


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 环境
def cmd_corpus(args):
    """分桶器的封装。corpus.py 可独立运行，这里只是转发。"""
    if args.action == 'build':
        p = corpus.build()
        size = os.path.getsize(corpus.OUT) / 1024
        print(f'已写出 {corpus.OUT}（{size:.0f} KB）')
        print(f'上游：{kb_adapter.kb_root()}')
        for b, arr in p['buckets'].items():
            print(f'  {b:<10} {len(arr):>4} 条')
        return 0
    if args.action == 'audit':
        if args.item:
            corpus.audit_item(args.item)
        else:
            corpus.audit(args.bucket or 'daily', args.k)
        return 0
    print(json.dumps({
        'upstream': kb_adapter.kb_stats(),
        'corpus_kb': round(os.path.getsize(corpus.OUT) / 1024) if
                     os.path.exists(corpus.OUT) else None,
        'buckets': {b: len(a) for b, a in corpus.load()['buckets'].items()},
    }, ensure_ascii=False, indent=1))
    return 0


def cmd_doctor(args):
    r = {'lifeos_home': store.ensure_home(), 'ok': True, 'issues': []}
    try:
        r['knowledge_base'] = kb_adapter.kb_stats()
        r['upstream_readonly'] = True
    except kb_adapter.KnowledgeBaseMissing as e:
        r['ok'] = False
        r['issues'].append(str(e))
    cp = corpus.OUT
    r['corpus'] = {'path': cp, 'exists': os.path.exists(cp)}
    if not os.path.exists(cp):
        r['issues'].append('corpus.json 不存在，跑：python scripts/lifeos.py corpus build')
    r['events'] = {
        'daily': len(store.read_events('daily.jsonl')),
        'decisions': len(dec.replay()),
    }
    r['profile'] = store.profile_summary()
    r['streak'] = store.streak()
    out(r)
    return 0 if r['ok'] and not r['issues'] else 1


# ---------------------------------------------------------------- 问 / 答
def cmd_ask(args):
    if args.date:
        d = dt.date.fromisoformat(args.date)
    else:
        d = dt.date.today()
    q = scheduler.today_question(d, force_rotate=args.next)
    if not args.date:
        scheduler.mark_asked(q['key'])
    q['reply_hint'] = (
        f"把「{q['title']}」转成今天能一句话回答的问题，让用户报个数或说做了/没做。"
        f"不要复述条文，控制在 80 字以内。")
    out(q)


def cmd_answer(args):
    ev = {'ts': store.now(), 'date': store.today(), 'key': args.key,
          'answer': args.content, 'note': args.note}
    store.append_event('daily.jsonl', ev)
    if args.complete:
        store.mark_done(args.key)
        ev['marked_complete'] = True
    out({'ok': True, 'recorded': ev})


def cmd_forget(args):
    """删掉最近一条回答（用于记错时纠正）。

    注意：jsonl 是只追加的，这里是唯一的例外 —— 纠正一次错误记录。
    原始行会被重写成一份「更正版」，事件流仍然完整可回放。
    """
    path = store.path('daily.jsonl')
    lines = open(path, encoding='utf-8').read().strip().split('\n') if \
        os.path.exists(path) else []
    if not lines:
        out({'ok': False, 'reason': '没有记录'})
        return
    last = json.loads(lines[-1])
    if args.key and last.get('key') != args.key:
        out({'ok': False, 'reason': f'最后一条是 {last.get("key")}，不是 {args.key}'})
        return
    lines[-1] = json.dumps({**last, 'superseded': store.now(),
                            'note': '记录有误，已撤回'}, ensure_ascii=False)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    out({'ok': True, 'superseded': last})


# ---------------------------------------------------------------- 决策
def cmd_decide(args):
    ev = dec.decide(args.title, args.content, kind=args.kind,
                    confidence=args.confidence, basis=args.basis,
                    review_at=args.review_at, context=args.context)
    out({'ok': True, 'recorded': ev,
         'hint': f"到 {ev['review_at']} 回来对账：lifeos close {ev['date']} \"实际结果\""})


def cmd_close(args):
    hit = dec.close(args.date, args.outcome, verdict=args.verdict, title=args.title)
    if not hit:
        out({'ok': False, 'reason': '没找到待对账的决策（可用 lifeos review-due 查看）'})
        return
    out({'ok': True, 'closed': hit})


def cmd_review_due(args):
    rows = dec.due_reviews(args.within)
    out({'count': len(rows),
         'decisions': [{'date': r['date'], 'title': r['title'],
                        'decision': r['decision'], 'kind': r.get('kind'),
                        'review_at': r['review_at'], 'basis': r.get('basis'),
                        'context': r.get('context')} for r in rows]})


def cmd_calibrate(args):
    out(dec.calibration())


# ---------------------------------------------------------------- 检索
def cmd_find(args):
    hits, backend = kb_adapter.search(args.kw, args.k)
    if not hits:
        out({'found': 0, 'backend': backend,
             'note': f'没查到「{args.kw}」。如实告诉用户查不到，'
                     f'可以给常识判断但要标明那是常识不是书里的内容，'
                     f'不要凭记忆补数字或法条条款号。'})
        return
    prof = store.get_profile()
    order = {'emergency': 0, 'event': 1, 'avoid': 2,
             'daily': 3, 'periodic': 4, 'once': 5}
    rows = []
    for h in hits:
        c = corpus.load()
        bucket = next((b for b, arr in c['buckets'].items()
                       if any(x['key'] == h['key'] for x in arr)), 'unknown')
        ok, why = (True, [])
        rows.append({'key': h['key'], 'bucket': bucket,
                     'cite': f"第 {h['sec']} 节第 {h['no']} 条（{h['title'][:18]}）",
                     'title': h['title'], 'plain': h['plain'][:160],
                     'cost': h['cost'][:120], 'benefit': h['benefit'][:220],
                     'note': h['note'][:260],
                     'ratio': h['ratio'], 'level': h['level'],
                     'caliber': CALIBER_LABEL.get(h['tag'].get('口径'), ''),
                     'dispute': h['dispute'], 'todo': h['todo'],
                     'applicable': ok, 'applicability': why})
    rows.sort(key=lambda r: (order.get(r['bucket'], 9), r['key']))
    out({'found': len(hits), 'backend': backend,
         'order': '急症 > 事件 > 避坑 > 日常 > 定期 > 一次性', 'items': rows})


# ---------------------------------------------------------------- 画像
def cmd_profile(args):
    if args.set:
        pairs = {}
        for kv in args.set:
            if '=' in kv:
                k, v = kv.split('=', 1)
                pairs[k.strip()] = v.strip()
        store.set_profile(pairs)
    if args.show or not args.set:
        s = store.profile_summary()
        unconfirmed = scorer.unresolved_domains(store.get_profile())
        s['unconfirmed_domains'] = sorted(unconfirmed)
        out(s)


# ---------------------------------------------------------------- 评分
def cmd_score(args):
    d = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    out(scorer.score(d))


def cmd_domain(args):
    # --all 不传时也显示全部，但会标注 [不适用]，让用户知道哪些被过滤掉了
    r = scorer.domain_detail(args.id, strict=False)
    if not r:
        out({'error': f"未知域 {args.id}",
             'available': [{'id': d['id'], 'name': d['name'],
                            'desc': d['desc']} for d in DOMAINS]})
        return
    print(f"## {r['domain']['name']} — {r['domain']['desc']}\n")
    for b, it, ok, why in r['items']:
        mark = '✅' if it['key'] in r['done'] else ('▸ ' if it['key'] in r['answered'] else '· ')
        flag = ' [不适用]' if not ok else ''
        print(f"{mark} {it['key']:<7} [{it['ratio']}/{it['level']}] "
              f"{it['title'][:46]}{flag}")


def cmd_due(args):
    rows = scheduler.due_periodic(
        dt.date.fromisoformat(args.date) if args.date else None)
    if not rows:
        print('近期没有到期的复查项')
        return
    print(f'共 {len(rows)} 项：\n')
    for r in rows:
        tag = '待办' if r['state'] == '待办' else f"上次 {r['last_done']}（{r['days']} 天前）"
        print(f"[{tag:<22}] {r['key']:<7} {r['cycle'] or '定期':<5} {r['title'][:38]}")


# ---------------------------------------------------------------- 复盘
def _review(days):
    c = corpus.load()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    answers = [e for e in store.read_events('daily.jsonl') if e['date'] >= since]
    dcs = [e for e in dec.replay() if e['date'] >= since]

    agg = {}
    for e in answers:
        agg.setdefault(e['key'], []).append(e)
    idx = {x['key']: (b, x)
           for b, arr in c['buckets'].items() for x in arr}
    tracked = []
    for k, lst in agg.items():
        b, meta = idx.get(k, ('?', {}))
        tracked.append({'key': k, 'bucket': b,
                        'title': meta.get('title', k),
                        'cite': f"第 {meta['sec']} 节第 {meta['no']} 条"
                                if meta.get('sec') else '',
                        'count': len(lst),
                        'answers': [x['answer'] for x in lst][-5:]})
    tracked.sort(key=lambda x: -x['count'])

    closed = [e for e in dec.due_reviews(0)]
    return {
        'period': f'{since} ~ {dt.date.today().isoformat()}',
        'days': days,
        'answers': len(answers),
        'decisions': len(dcs),
        'reviews_due': len(closed),
        'tracked': tracked,
        'score': scorer.score(),
        'calibration': dec.calibration(),
    }


def cmd_review(args):
    out(_review(7 if args.week else 30))


def cmd_export(args):
    c = corpus.load()
    prof = store.get_profile()
    sc = scorer.score()
    cal = dec.calibration()
    p = args.out or store.path('lifeos_export.md')

    L = ['# 高性价比生活档案', '', f"导出：{store.now()}", '']
    L.append('\n## 一、画像事实\n')
    for grp, spec in store.PROFILE_SCHEMA.items():
        L.append(f"\n### {spec['label']}\n")
        for f, label in spec['fields'].items():
            L.append(f"- {label}：{(prof.get(grp) or {}).get(f) or '（未填）'}")

    L.append('\n## 二、生活质量评分\n')
    L.append('\n### 八域覆盖度\n')
    L.append('| 生活域 | 已完成 | 待办 | 覆盖度 | 状态 | 下一条 |')
    L.append('| --- | --- | --- | --- | --- | --- |')
    for d in sc['domains']:
        kb = f"（全库 {d['kb_total']} 条）" if d.get('kb_total', 0) > d['total'] else ""
        L.append(f"| {d['name']}{kb} | {d['done']}/{d['total']} | "
                 f"{d['total']-d['done']} | {d['coverage']*100:.0f}% | "
                 f"{d['status']} | {d['top_gap_title'] or '-'} |")

    L.append('\n### 四口径（分开算，不折算）\n')
    for k, v in sc['calibers'].items():
        L.append(f"- **{v['label']}**：{v['score']*100:.0f}% "
                 f"（{v['total_items']} 条相关，高性价比待办 "
                 f"{v['high_value_pending']} 条）")

    L.append('\n### 优先做这 10 条\n')
    for i, x in enumerate(sc['priority'], 1):
        L.append(f"{i}. **{x['title']}** — {x['cite']}｜"
                 f"{x['ratio']}性价比/证据{x['level']}/{x['caliber']}")

    L.append('\n## 三、决策档案\n')
    for e in dec.replay():
        L.append(f"\n### {e['date']} {e['title']}"
                 f"（{dec.DECISION_KINDS.get(e.get('kind'), '')}）\n")
        if e.get('context'):
            L.append(f"- 当时处境：{e['context']}")
        L.append(f"- 决定：{e['decision']}")
        if e.get('confidence') is not None:
            L.append(f"- 当时把握：{e['confidence']}%")
        if e.get('basis'):
            L.append(f"- 依据：{e['basis']}")
        L.append(f"- 复查点：{e['review_at']}"
                 + (f"（已对账：{e['verdict']}，{e['outcome']}）"
                    if e.get('verdict') else '（未对账）'))

    L.append('\n## 四、决策倾向\n')
    L.append(f"- 决策 {cal['total_decisions']} 条，已对账 {cal['closed']} 条")
    if cal.get('hit_rate') is not None:
        L.append(f"- 命中率：{cal['hit_rate']*100:.0f}%")
    for band, v in cal.get('calibration', {}).items():
        L.append(f"- {band}: 平均把握 {v['avg_confidence']}%，"
                 f"实际命中 {v['actual_hit_rate']*100:.0f}% → {v['verdict']}")
    if cal.get('sample_warning'):
        L.append(f"\n> {cal['sample_warning']}")

    L.append(f"\n## 五、持续性\n\n"
             f"- 累计回答 {sc['stats']['answers_total']} 次，"
             f"覆盖 {sc['stats']['days_answered']} 天，"
             f"连续 {sc['stats']['streak']} 天")
    if sc['stats'].get('sample_warning'):
        L.append(f"- {sc['stats']['sample_warning']}")

    with open(p, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'已导出 {p}')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(prog='lifeos')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('doctor').set_defaults(fn=cmd_doctor)

    a = sub.add_parser('ask'); a.add_argument('--date'); a.add_argument('--next', action='store_true')
    a.set_defaults(fn=cmd_ask)
    a = sub.add_parser('answer')
    a.add_argument('key'); a.add_argument('content')
    a.add_argument('--note'); a.add_argument('--complete', action='store_true')
    a.set_defaults(fn=cmd_answer)
    a = sub.add_parser('forget'); a.add_argument('--key')
    a.set_defaults(fn=cmd_forget)

    a = sub.add_parser('decide')
    a.add_argument('title'); a.add_argument('content')
    a.add_argument('--kind', default='other', choices=list(dec.DECISION_KINDS))
    a.add_argument('--confidence', type=int)
    a.add_argument('--basis'); a.add_argument('--review-at'); a.add_argument('--context')
    a.set_defaults(fn=cmd_decide)
    a = sub.add_parser('close')
    a.add_argument('date'); a.add_argument('outcome')
    a.add_argument('--verdict', choices=['right', 'partial', 'wrong'])
    a.add_argument('--title')
    a.set_defaults(fn=cmd_close)
    a = sub.add_parser('review-due'); a.add_argument('--within', type=int, default=0)
    a.set_defaults(fn=cmd_review_due)
    sub.add_parser('calibrate').set_defaults(fn=cmd_calibrate)

    a = sub.add_parser('find')
    a.add_argument('kw'); a.add_argument('-k', type=int, default=8)
    a.set_defaults(fn=cmd_find)

    a = sub.add_parser('profile')
    a.add_argument('--show', action='store_true'); a.add_argument('--set', nargs='+')
    a.set_defaults(fn=cmd_profile)

    a = sub.add_parser('score'); a.add_argument('--date')
    a.set_defaults(fn=cmd_score)
    a = sub.add_parser('domain'); a.add_argument('id')
    # 默认全貌（含人群限定条目）；加 --all 显式表明「我知道我在看全部」
    a.add_argument('--all', action='store_true',
                   help='显示全貌（含人群限定条目），默认不适用项会被标注')
    a.set_defaults(fn=cmd_domain)
    a = sub.add_parser('due'); a.add_argument('--date')
    a.set_defaults(fn=cmd_due)

    a = sub.add_parser('review'); a.add_argument('--week', action='store_true')
    a.set_defaults(fn=cmd_review)
    a = sub.add_parser('export'); a.add_argument('--out')
    a.set_defaults(fn=cmd_export)

    a = sub.add_parser('corpus')
    a.add_argument('action', choices=['build', 'audit', 'stats'])
    a.add_argument('--bucket'); a.add_argument('--item')
    a.add_argument('-k', type=int, default=30)
    a.set_defaults(fn=cmd_corpus)

    args = ap.parse_args()
    try:
        code = args.fn(args)
        sys.exit(code or 0)
    except kb_adapter.KnowledgeBaseMissing as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()