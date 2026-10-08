---
name: lifeos
description: 按《高性价比人生指南》的标准做长期生活教练。建决策档案、每日问一条可核查的问题、按寿命/时间/金钱/自由四口径评分、到期回来对账、统计你自己的决策倾向校准度。当用户问「该不该做」「值不值」「怎么选」「这么干犯不犯法」「能领哪笔钱」「哪些钱别花」「我这样活得好吗」，或想让 lifeos 记录决策、回答每日一问、查看生活质量评分时使用。正文知识来自只读的 how-to-live-better 知识库（34 节 672 条），本 skill 只持有元数据索引，条目详情现场从上游取。
---

# lifeos — 生活决策教练

> 「先看值不值，再看划不划算，最后看这么干犯不犯法。」
> —— 《高性价比人生指南》第 0 节方法论

## 这是什么

一个**长期**的生活教练。不是问答工具，不是知识库检索壳子。

它做三件别的工具做不到的事：

1. **记住你的每一次决策和当时的想法**（事件溯源，永不改写）
2. **按书里的标准给你的生活质量打分**（八域 + 四口径，不合成总分）
3. **到期回来跟你对账，统计你自己是不是过于自信**（决策倾向校准度）

第 3 条是真正属于你的东西。书给不了，检索也给不了 —— 只有你的决策档案积累半年以上才有意义。

## 分层架构（重要，不要混淆）

```
L1  lifeos（教练层，本项目，可写）
     ├─ 档案：daily.jsonl / decisions.jsonl / profile.json / state.json
     ├─ 索引：data/corpus.json（335 KB 元数据，672 条，无正文）
     └─ kb_adapter ──依赖──> L0
                              how-to-live-better（知识层，只读）
                              34 节 672 条 · A438/B179/C55 · CC BY 4.0
```

- **L0 只读，永远不改。** 上游只加了一个 `--json` 输出开关，文本输出行为零变化。
- **L1 本地不存正文。** 只存桶号、标签、定位串。条目详情现场从上游取。
  672 条正文 6.6 MB，本地索引 335 KB，**20 倍瘦身**。
- **单向依赖，不 fork。** 上游更新了检索器，lifeos 自动跟着受益。
- 上游找不到时设环境变量 `LIFEOS_KB_PATH` 指向任一副本；`lifeos doctor` 会告诉你实际命中哪个。

## 6 桶分类

| 桶 | 含义 | 条数 | 怎么用 |
| --- | --- | --- | --- |
| `daily` | 每日可核查行为 | 31 | 每天问一条，18 条轮换池 |
| `periodic` | 定期复查（每年/定期） | 12 | 到期提醒 |
| `once` | 一次性通关 | 81 | 做完打勾，算覆盖度 |
| `event` | 条件触发（结婚/怀孕/搬家…） | 389 | 画像命中才推 |
| `emergency` | 急救/危机 | 70 | 出事时查，不主动推 |
| `avoid` | 避坑清单 | 89 | 不做，比"该做"更省 |

`daily` 池只有 18 条轮换 —— 31 条里挑出最值得每天问的，避免重复疲劳。

## 三层适用性过滤（宁可漏推不误推）

带人群限定的条目（「产假 98 天」「出生后 24 小时打疫苗」）在画像**未确认前一律不主动推荐**。

- 「没填孩子」≠「没有孩子」
- 空值默认 `strict=True` 拦下
- 想看全貌用 `lifeos domain <id>`（不适用项会标注 `[不适用]`）

已验证：画像填 `children=无 elderly=无` 后，相关条目正确从优先清单消失。

## 四个口径，分开算，不折算

书里明确寿命、时间、金钱、自由四样**不能互相折算**。所以 `lifeos score` **不给总分**。

给的是：
- **八域覆盖度** —— 生命安全/健康/精力/金钱/消费/法律/家庭/成长，按 A/B/C 级和性价比加权
- **四口径各自得分** —— 各算各的，看哪个拖后腿
- **优先做这 10 条** —— 加权排序

## 决策闭环（最有价值的部分）

```
decide  ── 记决策 + 复查点 + 当时把握（0-100）
   ↓  （30/90/180 天后）
review-due  ── 该对账了
   ↓
close   ── 实际结果 + 对/错/部分对
   ↓
calibrate ── 自称把握 vs 实际命中率 → 校准度
```

「我当时说 90% 把握」的结果如果只有 40% 对，gap > 0.15 就判 **过于自信**。这类统计
样本 < 10 条时会明确提醒「以下统计只能当参考」。

**记决策时 `context`（当时的具体处境）最有信息量** —— 几个月后回看，「为什么当时觉得
该买」比「买了什么」值钱得多。

## 怎么用（agent 应该这样调用）

所有命令都是 `python3 scripts/lifeos.py <子命令>`，输出 JSON 或 Markdown。

### 回答一个具体的生活决策 —— 先检索，再对账

```bash
python3 scripts/lifeos.py domain money            # 看金钱域全貌
python3 scripts/lifeos.py due                     # 该复查哪些条目
```

回答时**必须**：
- 引用「第 X 节第 Y 条」，不要说"书里说"
- 四口径分开讲，别折算成"值不值"
- 有相关性问题先查 `emergency` 桶（`find` 会带出 bucket 字段）
- 涉及违法/工伤/索赔，优先查 `law` 桶和 `emergency` 桶

### 每日问一条

```bash
python3 scripts/lifeos.py ask                    # 确定性轮换，同一天必给同一条
python3 scripts/lifeos.py answer 2.22 --content "今天吃了两个苹果" --complete
```

`ask` 已带 `reply_hint`：把条文转成能一句话回答的问题，**不要复述原文**，控制在 80 字以内。

回答后如果用户顺手做了某条一次性事项，可以 `answer ... --complete` 或
`lifeos.py answer <key> --complete` 打勾。

### 记录决策

```bash
python3 scripts/lifeos.py decide \
  --title "换到新部门" --decision "接受，赌方向对" \
  --kind career --confidence 70 \
  --basis "第 12 节第 3 条" \
  --context "原部门方向不明，新部门是空白但负责人靠谱"
```

`kind` 七类：health / money / career / family / legal / home / other
每类有预设复查间隔（health 30 天、legal 60 天、career 180 天……）

### 到期对账

```bash
python3 scripts/lifeos.py review-due --within 7   # 提前 7 天提醒
python3 scripts/lifeos.py close 2026-09-12#001 \
  --outcome "半年后项目还是没起来" --verdict wrong
```

`--verdict` 不填会按情感词粗判，但**最好显式指定**。

### 查看评分

```bash
python3 scripts/lifeos.py score                  # 八域 + 四口径 + top10
python3 scripts/lifeos.py calibrate               # 决策倾向校准度
python3 scripts/lifeos.py export --out report.md # 五段式 Markdown 全量报告
```

### 画像

```bash
python3 scripts/lifeos.py profile --show
python3 scripts/lifeos.py profile --set city=苏州 income_range=2-4万 children=无
python3 scripts/lifeos.py profile --set 'skip:5.44'
```

`skip:` 前缀是永久屏蔽某条（问过了/不适用）。

### 纠正错误记录

```bash
python3 scripts/lifeos.py forget 2026-09-12#001
```

事件溯源的唯一例外：加 `superseded` 标记，不删原行。

## 自动化（已配 4 条）

| 频率 | 时间 | 干什么 |
| --- | --- | --- |
| 每天 | 20:30 | 每日一问 |
| 每周 | 周日 20:00 | 周复盘 |
| 每月 | 1 号 10:00 | 画像重评 |
| 每月 | 15 号 09:30 | 时效性提醒 |

## 边界（不要越界）

- **不是医疗建议。** `health` 桶只到"该查什么、该注意什么"，不诊断、不给药。
- **不是法律代理。** `law` 桶给的是"该找谁、该留什么证据"，具体案件找律师。
- **不合成总分。** 四口径折算成一个数会误导 —— 少赚点钱换回命，是划算还是亏？
- **不主动推人群限定条目。** 画像没确认 = 不知道，不等于"可能适用"。
- **不改上游。** 上游是只读知识库，有问题去改 how-to-live-better 仓库，不是这里。

## 排查

```bash
python3 scripts/lifeos.py doctor      # 知识库命中哪个副本、索引在不在、档案状态
python3 scripts/lifeos.py corpus audit --item 18.2   # 单条为什么进这个桶
python3 scripts/lifeos.py corpus audit --bucket daily  # 整个桶扫一遍
```

`audit --item` 会打印：桶 / 生活域 / 口径 / 等级 / 权重 / 人群限定 / 争议标记 /
分类依据 / 人工裁决理由。分类有疑问时先看这个。

索引过期（上游更新了）就重建：
```bash
python3 scripts/lifeos.py corpus build
```