#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上游知识库适配器。

lifeos 不持有《高性价比人生指南》的任何副本：正文、items.json 都在上游仓库。
本模块负责把上游找出来、把条目读出来，并在上游不可用时给出可执行的修复指引。

调用链：
    adapter.resolve()   找到上游目录（多路径探测 + 环境变量覆盖）
    adapter.load_items()  读上游结构化索引
    adapter.get_item()   按「节.条」精确取一条
    adapter.search()     调上游 search.py（需要上游支持 --json，否则降级为文本扫描）

环境变量：
    LIFEOS_KB_PATH   显式指定上游知识库目录（优先级最高）
"""
import json
import os
import re
import subprocess
import sys

# 知识层候选路径，按优先级排列。
# 兼容三种形态：项目仓库、带 --skill 的技能目录、普通目录（含 data/items.json）
_KB_CANDIDATES = [
    os.environ.get('LIFEOS_KB_PATH'),
    # 同级仓库（开发时最常见）
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'how-to-live-better', 'data', 'items.json'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', '..', 'how-to-live-better', 'data', 'items.json'),
    # WorkBuddy 技能副本
    os.path.join(os.path.expanduser('~'), '.workbuddy', 'skills',
                 'how-to-live-better-skill', 'data', 'items.json'),
    os.path.join(os.path.expanduser('~'), '.workbuddy', 'skills',
                 'how-to-live-better', 'data', 'items.json'),
    # 跨客户端公约副本
    os.path.join(os.path.expanduser('~'), '.agents', 'skills',
                 'how-to-live-better-skill', 'data', 'items.json'),
    os.path.join(os.path.expanduser('~'), '.agents', 'skills',
                 'how-to-live-better', 'data', 'items.json'),
    # 桌面正式项目目录
    os.path.join(os.path.expanduser('~'), 'Desktop', 'how-to-live-better',
                 'data', 'items.json'),
    os.path.join(os.path.expanduser('~'), 'Desktop', 'how-to-live-better-skill',
                 'data', 'items.json'),
]

_HINT = """未找到上游知识库（lifeos 不持有正文副本，需要单独获取一次）。

三选一：
  1. 已有仓库：设环境变量 LIFEOS_KB_PATH 指向它
     set LIFEOS_KB_PATH=C:\\path\\to\\how-to-live-better
  2. 从 GitHub 克隆：git clone https://github.com/niuniubinghero/how-to-life-better-skill.git
     克隆后跑一次 python scripts/build_index.py 生成索引
  3. 已有技能副本：确认 ~/.workbuddy/skills/how-to-live-better-skill/ 存在，
     且里面有 data/items.json（没有就先在那个目录跑 build_index.py）"""


class KnowledgeBaseMissing(RuntimeError):
    """上游不可用。消息已包含修复步骤，可直接展示给用户。"""


_cached = {}


def resolve_index():
    """返回上游 items.json 的绝对路径。找不到就抛 KnowledgeBaseMissing。"""
    if _cached.get('idx'):
        return _cached['idx']
    tried = []
    for cand in _KB_CANDIDATES:
        if not cand:
            continue
        norm = os.path.abspath(os.path.expanduser(cand))
        if os.path.isfile(norm):
            _cached['idx'] = norm
            _cached['root'] = os.path.dirname(os.path.dirname(norm))
            return norm
        tried.append(norm)
    msg = _HINT + '\n\n已尝试：\n' + '\n'.join('  ' + t for t in tried[:8])
    raise KnowledgeBaseMissing(msg)


def kb_root():
    resolve_index()
    return _cached['root']


def load_items():
    """载入上游索引。返回 dict（含 items / sections）。"""
    if _cached.get('items') is not None:
        return _cached['items']
    with open(resolve_index(), encoding='utf-8') as f:
        data = json.load(f)
    _cached['items'] = data
    return data


def get_item(key):
    """按「节.条」精确取一条，例如 get_item('8.18')。找不到返回 None。"""
    try:
        sec, no = key.split('.')
        sec, no = int(sec), int(no)
    except (ValueError, AttributeError):
        return None
    for it in load_items()['items']:
        if it['sec'] == sec and it['no'] == no:
            return it
    return None


def search(kw, limit=8):
    """检索条目，返回 (hits, backend)。

    优先调上游 search.py --json（若上游支持）；不支持则退回本地标题/正文扫描。
    返回的每条都是 lifeos 内部的归一化结构，字段与 questions.json 对齐。
    """
    root = kb_root()
    script = os.path.join(root, 'scripts', 'search.py')
    idx = resolve_index()

    if os.path.exists(script):
        try:
            out = subprocess.run(
                [sys.executable, script, kw, '--json', '-k', str(limit)],
                capture_output=True, text=True, timeout=30,
                cwd=root)
            if out.returncode == 0:
                blob = out.stdout.strip()
                if blob.startswith('{') or blob.startswith('['):
                    data = json.loads(blob)
                    items = data.get('items', data) if isinstance(data, dict) else data
                    return [normalize(x) for x in items[:limit]], 'upstream-cli'
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass    # 上游不支持 --json，走下面的兜底

    # 兜底：直接扫索引。评分逻辑刻意保守，只做整词命中。
    items_all = load_items()['items']
    hits = []
    for it in items_all:
        hay = it.get('haystack', '') or (it['title'] + ' ' + it.get('plain', ''))
        s = 0
        for t in kw.split():
            c = hay.count(t)
            if c:
                s += c * (3 if t in it['title'] else 1)
        if s:
            hits.append((s, it))
    hits.sort(key=lambda x: -x[0])
    return [normalize(it) for _, it in hits[:limit]], 'local-scan'


def normalize(it):
    """把上游条目字段映射成 lifeos 内部结构。"""
    return {
        'key': f"{it['sec']}.{it['no']}",
        'sec': it['sec'],
        'no': it['no'],
        'sec_name': it.get('sec_name', ''),
        'title': it.get('title', ''),
        'plain': it.get('plain', ''),
        'cost': it.get('cost', ''),
        'benefit': it.get('benefit', ''),
        'note': it.get('note', ''),
        'source': it.get('source', ''),
        'level': it.get('level', ''),
        'ratio': it.get('ratio', ''),
        'tag': it.get('tag', {}),
        'dispute': it.get('dispute', False),
        'todo': it.get('todo', False),
    }


def kb_stats():
    """上游库统计，用于自检和文档。"""
    d = load_items()
    items = d['items']
    return {
        'index_path': resolve_index(),
        'kb_root': kb_root(),
        'total': len(items),
        'sections': len(d.get('sections', [])),
        'levels': {lv: sum(1 for x in items if x.get('level') == lv)
                   for lv in ('A', 'B', 'C')},
        'ratios': {r: sum(1 for x in items if x.get('ratio') == r)
                   for r in ('极高', '高', '一般')},
        'dispute': sum(1 for x in items if x.get('dispute')),
        'search_cli': os.path.exists(os.path.join(kb_root(), 'scripts', 'search.py')),
    }


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        print(json.dumps(kb_stats(), ensure_ascii=False, indent=1))
    except KnowledgeBaseMissing as e:
        print(e, file=sys.stderr)
        sys.exit(1)