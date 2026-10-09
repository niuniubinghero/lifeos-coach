# lifeos-coach

> 按《高性价比人生指南》的标准做长期生活教练。
> 记你的决策，按四口径给你打分，到期跟你对账。

一个独立的 Agent Skill 项目。**调用**知识库，不 fork 知识库。

---

## 为什么不寄生在书里

第一版做错过：把 lifeos 塞进 `how-to-live-better` 仓库的 `skills/` 下，自带一份 672 条
正文副本（6.6 MB）和一套自己的检索逻辑。问题很明确：

- 上游一改，两边就漂移
- 20 倍的存储冗余
- 检索逻辑两份实现，长期不一致

现在是两层解耦：

```
L1  lifeos（教练层，本仓库，可写）
     档案 daily.jsonl / decisions.jsonl / profile.json / state.json
     索引 data/corpus.json          335 KB 元数据（672 条，无正文）
     适配 scripts/kb_adapter.py     单向依赖 ↓
L0  how-to-live-better（知识层，只读）
     34 节 672 条 · A438 / B179 / C55 · CC BY 4.0
     scripts/search.py（加了 --json 开关，文本输出零变化）
```

三条硬约束：

| 约束 | 实现 | 收益 |
| --- | --- | --- |
| 不 fork | `kb_adapter` 探测 9 条候选路径，命中即用 | 上游更新自动受益 |
| 不改正文 | 上游只加 `--json`，文本路径逐字未变 | 知识层零风险 |
| 不存正文 | corpus.json 只有桶号/标签/定位串 | 6.6 MB → 335 KB |

## 安装

```bash
git clone https://github.com/niuniubinghero/lifeos-coach.git
cd lifeos-coach
python3 scripts/lifeos.py doctor
```

无第三方依赖，纯标准库 Python 3，完全离线。

知识层任一副本都能被自动识别：

```bash
export LIFEOS_KB_PATH=/path/to/how-to-live-better   # 可选，显式指定
```

`doctor` 会告诉你实际命中了哪个副本。

## 目录

```
lifeos/
├── SKILL.md                 Agent Skills 规范入口
├── README.md
├── data/
│   ├── corpus.json          335 KB 元数据索引（可重建，不建议手改）
│   └── overrides.json       人工分类裁决（约 96 条，每条写明 reason）
└── scripts/
    ├── lifeos.py            统一 CLI，17 个子命令
    ├── kb_adapter.py        L0 知识层适配（9 条路径探测 + 上游 CLI 优先）
    ├── model.py             8 生活域 + 4 口径 + 人群限定标签 + 适用性判定
    ├── corpus.py            6 桶分类器（build / audit / stats）
    ├── store.py             档案层：事件溯源读写、画像、状态
    ├── decisions.py         决策闭环：decide / replay / close / calibration
    ├── scorer.py            八域覆盖度 + 四口径 + 优先级清单
    └── scheduler.py         确定性轮换出题 + 定期复查到期
```

## 6 桶分类

| 桶 | 含义 | 条数 |
| --- | --- | --- |
| `daily` | 每日可核查行为（18 条轮换池） | 31 |
| `periodic` | 定期复查 | 12 |
| `once` | 一次性通关 | 81 |
| `event` | 条件触发 | 389 |
| `emergency` | 急救 / 危机 | 70 |
| `avoid` | 避坑清单 | 89 |

分类规则（`corpus.py`）刻意保守，两条经验值得留着：

1. **周期词只在 title 里匹配。** 全文搜 `每年` 会把「不捡来路不明金属件」误判成
   「每年复查」。全库只有 31 条标题带周期词，这个可信集足够用。
2. **人群限定标签要扫正文。** 18.2 标题是「产假 98 天」，「生孩子」写在 `plain` 里。
   所以 `cond_tags` 扫 `title + plain[:80]`。

规则判不准的地方，用 `data/overrides.json` 人工钉死（键是「节.条」）。目前约 96 条，
每条都带 `reason`，改动可追溯。

## 三层适用性过滤

带人群限定的条目，画像未确认前**一律不主动推**。

```
strict=True（默认，用于评分/优先清单）
  → 有人群标签 且 画像字段为空 → 拦下
strict=False（用于 domain --no-strict 看全貌）
  → 只提示
```

理由：「没填孩子」不等于「没有孩子」。宁可漏推不误推 —— 推错一次的代价，
远大于漏掉一条本来也不急着做的。

已验证：画像填 `children=无 elderly=无` 后，「产假 98 天」「出生后 24 小时打疫苗」
正确从优先清单消失。

## 事件溯源

档案是 `.jsonl`，一行一条事件，**只追加，永不改写**。

```
2026-09-12#001  {"event":"decide","did":"2026-09-12#001","confidence":70,...}
2026-10-03#007  {"event":"close","did":"2026-09-12#001","verdict":"wrong",...}
```

派生状态（画像、覆盖率、校准度）全部通过**重放事件流**算出。

`did` 是稳定标识（`日期#序号`），不能用日期当主键 —— 同一天可能记多条决策。

纠正错误记录用 `forget`，它是唯一的例外：给原行加 `superseded` 标记，不删。

## 决策闭环

```
decide ──► 留复查点 + 当时把握(0-100)
   │
   │  30/90/180 天
   ▼
review-due ──► 该对账了
   │
   ▼
close ──► 实际结果 + 对/错/部分对
   │
   ▼
calibrate ──► 自称把握 vs 实际命中率
```

**校准度**是这个项目的核心价值。gap > 0.15 判「过于自信」/「偏保守」，
样本 < 10 条时明确标注「只能当参考」。

典型用法：`--context` 一定要写。三个月后回看，「当时为什么觉得该买」比
「买了什么」值钱得多。

## 四口径，不折算

书里明确：寿命、时间、金钱、自由**四样分开算，不互相折算**。

所以 `score` **不给总分**，给的是：

- 八域覆盖度（8 个生活域，权重按 A/B/C 级 + 性价比）
- 四口径各自得分（看哪个拖后腿）
- 优先做这 10 条

「少赚点钱换回命」——折算成一个数就答不出这个问题了。

## 自动化

| 频率 | 时间 | 命令 |
| --- | --- | --- |
| 每天 | 20:30 | `lifeos ask` |
| 每周 | 周日 20:00 | `lifeos review` |
| 每月 | 1 号 10:00 | `lifeos profile` + `score` |
| 每月 | 15 号 09:30 | `lifeos due` |

由 WorkBuddy `automation_update` 调度，cwd 指向本仓库。

## 维护

**上游更新了条目** → 重建索引：
```bash
python3 scripts/lifeos.py corpus build
python3 scripts/lifeos.py corpus audit --item 18.2   # 单条：为什么进这个桶
```

**改了分类规则** → 一并更新 `data/overrides.json`，并在提交信息里写清 why。

**索引不落 git？** 建议落 —— 335 KB 很小，reproducibility 比省事重要。
但如果你更想让使用者自己 build，删掉 `data/corpus.json` 并在 `.gitignore` 里加上。

## 边界

- 不是医疗建议。`health` 桶只到「该查什么、该注意什么」。
- 不是法律代理。`law` 桶给的是「该找谁、该留什么证据」。
- 不合成总分。
- 不改上游。上游有问题去改它自己的仓库。

## 许可

代码 MIT。正文知识来自 [eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter)，
正文 CC BY 4.0。本仓库**不含正文副本**。