#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 lifeos-coach 安装到各个 agent 的 skills 目录。

lifeos 与知识层的区别：本地只有 335 KB 元数据索引，没有正文副本，
所以「安装」只是拷贝 SKILL.md + scripts/ + data/corpus.json，很轻。

条目详情在运行时由 kb_adapter 从上游知识库现场取 —— 安装包里永远不会有正文。

用法：
    python3 scripts/install.py --list      # 看各副本状态
    python3 scripts/install.py            # 装到缺失的副本
    python3 scripts/install.py --force    # 覆盖已有副本
"""
import argparse
import filecmp
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = ('SKILL.md', 'LICENSE', 'README.md', 'data', 'scripts')

# 各 agent 的 skills 目录
TARGETS = [
    ('workbuddy', os.path.join(os.path.expanduser('~'), '.workbuddy', 'skills')),
    ('agents', os.path.join(os.path.expanduser('~'), '.agents', 'skills')),
    ('claude', os.path.join(os.path.expanduser('~'), '.claude', 'skills')),
]

SKILL_NAME = 'lifeos-coach'
# 不该进安装包的目录
SKIP_DIRS = {'__pycache__', '.git'}


def _files_of(d):
    """目录下所有文件的相对路径集合（用于比对差异）。"""
    out = set()
    for base, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            out.add(os.path.relpath(os.path.join(base, f), d).replace('\\', '/'))
    return out


def status_of(target_root):
    """返回 (是否已安装, 是否有差异, 本地文件数, 副本文件数)"""
    dst = os.path.join(target_root, SKILL_NAME)
    if not os.path.isdir(dst):
        return (False, False, _count(ROOT), 0)
    same, diff = _compare(ROOT, dst)
    return (True, diff, _count(ROOT), _count(dst))


def _count(root):
    n = 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        n += len(files)
    return n


def _compare(src, dst):
    """逐文件比对内容，返回 (是否全部一致, 是否有差异)。"""
    src_files, dst_files = _files_of(src), _files_of(dst)
    if src_files == dst_files:
        all_same = True
    else:
        all_same = False
    diff = False
    for rel in src_files & dst_files:
        a, b = os.path.join(src, rel), os.path.join(dst, rel)
        if not filecmp.cmp(a, b, shallow=False):
            diff = True
            break
    return all_same, diff


def _rmtree_safe(d):
    """删目录。

    不用 shutil.rmtree —— 部分环境会把它的删除动作重定向到系统回收站 API，
    在没有桌面 shell 的场景下会抛 SHFileOperationW 失败。
    逐文件 unlink + 逐层 rmdir，纯文件系统调用，任何环境都能跑。
    """
    if not os.path.isdir(d):
        return
    for base, dirs, files in os.walk(d, topdown=False):
        for f in files:
            p = os.path.join(base, f)
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
        for sub in dirs:
            try:
                os.rmdir(os.path.join(base, sub))
            except OSError:
                pass
    try:
        os.rmdir(d)
    except OSError:
        pass


def install(dst_root, force=False):
    dst = os.path.join(dst_root, SKILL_NAME)
    installed, diff, _, _ = status_of(dst_root)
    if installed and not diff and not force:
        return 'skip'
    _rmtree_safe(dst)
    os.makedirs(dst, exist_ok=True)
    for item in PKG:
        s = os.path.join(ROOT, item)
        if not os.path.exists(s):
            continue
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        else:
            shutil.copy2(s, d)
    # .gitignore 也带上，避免用户往安装目录里塞东西后误提交
    gi = os.path.join(ROOT, '.gitignore')
    if os.path.exists(gi):
        shutil.copy2(gi, os.path.join(dst, '.gitignore'))
    return 'update' if installed else 'create'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true', help='只列状态，不安装')
    ap.add_argument('--force', action='store_true', help='覆盖已有副本')
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding='utf-8')
    print(f'{"副本":<12} {"状态":<10} {"本地文件":>8} {"副本文件":>8}  路径')
    print('-' * 78)
    for name, root in TARGETS:
        installed, diff, sn, dn = status_of(root)
        if not installed:
            st = '未安装'
        elif diff:
            st = '有差异'
        else:
            st = '最新'
        print(f'{name:<12} {st:<10} {sn:>8} {dn:>8}  {root}')
    if args.list:
        return 0

    print()
    for name, root in TARGETS:
        if not os.path.isdir(os.path.dirname(root)):
            print(f'{name:<12} 跳过（{root} 的上级目录不存在）')
            continue
        r = install(root, force=args.force)
        print(f'{name:<12} {r}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())