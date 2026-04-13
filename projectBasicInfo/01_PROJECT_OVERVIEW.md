# RadioMind — Project Overview

> **文档性质**: 方向性设计文档，经多轮讨论对齐后的架构方案。
> **更新日期**: 2026-04-13
> **版本**: v3 (仿生记忆核心定位)

---

## 一、愿景与定位

### 1.1 一句话定位

**RadioMind 是一个独立的仿生记忆-思考核心，为 AI Agent 提供"越用越懂你"的深层记忆能力。**

### 1.2 完整定位

RadioMind 是一个受神经科学启发的**可插拔记忆模块**，模拟人类大脑的多层记忆系统（工作记忆→海马体→新皮层），通过"聊天"和"做梦"两种仿生机制将零散对话炼化为深层习惯记忆。

它是 RadioHeader（编程经验框架）和 RadioHand（个人 Agent 框架）的**默认记忆模块**，同时遵循通用记忆接口，可接入 Hermes Agent、OpenClaw、HomeGenie 等任何 Agent 系统。

### 1.3 产品关系

```
RadioMind (仿生记忆核心) ← 本项目
  │
  ├─ RadioHeader = RadioMind + Claude Code/Codex 适配器
  │    (编程场景的跨项目经验框架，已有项目)
  │
  ├─ RadioHand = RadioMind + Agent Runtime + 多通道
  │    (通用个人 Agent 框架，规划中)
  │
  ├─ Hermes Memory Provider = RadioMind + Hermes API 适配器
  │    (接入 Hermes 47k star 生态)
  │
  └─ HomeGenie = RadioMind + 硬件运行时
       (本地 AI 家庭中枢，已有项目，可作为参考运行时)
```

### 1.4 不是什么

- 不是 Agent 框架（那是 RadioHand 的职责）
- 不是聊天机器人（RadioMind 只提供记忆能力，对话由宿主 Agent 负责）
- 不是向量数据库的替代品（向量检索只是 L2 层的实现手段之一）
- 不是静态配置（一切可能变化的东西都不写死）

### 1.5 核心设计原则

| 原则 | 含义 |
|------|------|
| **仿生优先** | 架构对标大脑（海马体、新皮层、睡眠巩固），不是数据库思维 |
| **可插拔** | 作为独立模块，宿主 Agent 通过标准接口调用 |
| **本地优先** | 所有记忆数据本地存储，炼化用本地小模型，隐私不出设备 |
| **不写死** | LLM、存储后端、通道、领域——一切外部依赖都是配置，非代码 |
| **知己知彼** | 持续更新用户侧写 + 系统自画像，元认知驱动自适应 |

---

## 二、竞品格局

### 2.1 记忆系统赛道现状（2026）

| 框架 | Stars | 核心方法 | 存储 | 独特点 | 缺失 |
|------|-------|---------|------|--------|------|
| **Mem0** | ~48k | 向量+图+KV 多存储 | 云端 | 生态最广 | 无经验提纯，无巩固机制 |
| **Zep/Graphiti** | — | 时序推理引擎 | 云/自托管 | 时序推理强 | 无跨域流动 |
| **Letta** | — | OS 式三层 | 自托管 | 类操作系统模型 | 无自进化 |
| **mempalace** | — | 记忆宫殿层级 | 本地 ChromaDB | 96.6% R@5 | 2D 层级，无抽象维度 |
| **Holographic** | — | SQLite FTS5 + HRR | 本地 | 信任评分，代数查询 | 无巩固，社区小 |
| **Supermemory** | — | 图谱 API + MCP | 云端 | 编程最适配 | 付费，无本地 |
| **MemOS** | — | 参数/激活/声明三类 | 可插拔 | LoRA 作参数记忆 | 概念框架，实现早期 |

### 2.2 RadioMind 的差异化

**所有竞品都聚焦在"存 + 检索"，没有人做"炼化"和"强制使用"。**

| RadioMind 能力 | 竞品有没有 | 独特程度 |
|---------------|----------|---------|
| 向量/FTS/知识图谱检索 | 全都有 | ❌ 无差异 |
| **四层仿生记忆（草稿→笔记→习惯→外挂）** | 无 | ✅ 独一无二 |
| **"聊天"炼化（三体博弈创造新洞察）** | 无 | ✅ 独一无二 |
| **"做梦"炼化（神游修剪 + 自由联想）** | Claude AutoDream 仅机械修剪 | ✅ 有创造性联想 |
| **跨领域经验提纯（Shortwave）** | 无 | ✅ 独一无二 |
| **行为契约（Search→Apply→Trace）** | 无 | ✅ 独一无二 |
| **双侧写（用户 + 系统自身）** | 用户侧写普遍有，系统自画像无 | ✅ 元认知层 |
| **HDC 超维压缩存储** | Holographic 用 HRR（类似思路） | ⚠️ 有差异 |
| **个人 LoRA 深层内化** | MemOS 概念有，Hermes 可导出训练数据 | ⚠️ 闭环实现差异 |

---

## 三、仿生记忆架构

### 3.1 神经科学基础

RadioMind 的架构直接对标大脑的互补学习系统（Complementary Learning Systems）：

| 大脑结构 | 功能 | RadioMind 对应 |
|---------|------|---------------|
| 前额叶 (工作记忆) | 当前处理，容量极小 | L1 记忆草稿 |
| 海马体 (情节记忆) | 快速编码，空间索引 | L2 记忆笔记 |
| 新皮层 (语义/程序记忆) | 慢速巩固，深层理解 | L3 习惯记忆 |
| 文化传承 (替代性学习) | 从他人经验学习 | L4 外挂知识 |
| 元认知 (自我意识) | 知道自己知道什么 | Meta 双侧写 |
| 睡眠巩固 (SHY) | 修剪弱连接，强化重要连接 | "做梦"炼化 |
| 检索练习 + 社会学习 | 主动回忆 + 讨论巩固 | "聊天"炼化 |

### 3.2 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  Meta 元认知层                                               │
│  ┌──────────────────────┐  ┌─────────────────────────────┐ │
│  │  用户侧写             │  │  系统自画像                  │ │
│  │  WHO/HOW/WHAT         │  │  IDENTITY/STATE/CAPABILITY  │ │
│  │  (持续学习)            │  │  (运行时自省)               │ │
│  └──────────────────────┘  └─────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  L4 外挂知识 ─── "记忆去读书"                                │
│  Shortwave 库 + Learn 命令 + 社区共享                       │
│  入口 → L2（走正常巩固路径，不直接进 L3）                    │
├─────────────────────────────────────────────────────────────┤
│  L3 习惯记忆 ─── 新皮层                                     │
│  存储: HDC 超维向量 (10,000-bit) + 个人 LoRA adapter        │
│                                                             │
│  ┌─ "聊天"炼化 ──────────────────────────────────────────┐ │
│  │  三体博弈: 守护者(一致性) / 探索者(新颖性) / 精简者    │ │
│  │  异构模型 (如 Qwen/Gemma/Phi)                         │ │
│  │  产出: 新洞察(候选，需后续验证) + 强化关联             │ │
│  │  触发: 活跃使用时（"白天"）                            │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌─ "做梦"炼化 ──────────────────────────────────────────┐ │
│  │  Phase 1 修剪(SHY): 矛盾消解 / 冗余合并 / 衰减淘汰    │ │
│  │  Phase 2 神游(DMN): 随机关联 → 发现跨域元模式          │ │
│  │  Phase 3 梦境记录: 修剪直接执行 / 神游标记候选置信度    │ │
│  │  触发: 空闲/会话结束时（"夜晚"）                       │ │
│  └────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  L2 记忆笔记 ─── 海马体 (3D 金字塔)                         │
│  三维索引: domain(领域) × time(时间) × level(抽象层级)      │
│  存储: SQLite + sqlite-vec                                  │
│  检索: 注意力式 — 原则层扫描 → 模式层聚焦 → 事实层精筛      │
│  抽象层级: L0 事实 → L1 模式 → L2 原则                      │
├─────────────────────────────────────────────────────────────┤
│  L1 记忆草稿 ─── 工作记忆                                    │
│  对话历史 → 注意力门控（值得记吗？）→ 合格者存入 L2          │
│  Context-Digest 注入（Meta 层的摘要）                        │
├─────────────────────────────────────────────────────────────┤
│  L0 本能 ─── 基模权重（可更换，不绑定任何具体模型）          │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 数据流与巩固路径

```
对话输入
  ↓
L1 注意力门控 → 过滤噪声
  ↓
L2 3D 金字塔编码 (事实层)
  ↓ 积累足够事实后
L2 内部聚合: 事实→模式→原则（金字塔向上聚合）
  ↓ "聊天"触发条件满足
L3 三体炼化 → 候选洞察 → 验证后确认 → HDC 编码
  ↓ "做梦"触发条件满足
L3 修剪整合 + 神游联想 → 元模式
  ↓ 定期离线（如每周）
L3 → LoRA 训练数据 → MLX 微调 → 个人 adapter 更新

外挂知识（L4）:
  Learn/Shortwave → L2 事实层 → 走同样的巩固路径

Meta 双侧写:
  每次交互更新用户侧写
  每次配置变更/做梦时更新系统自画像
  双侧写本身也是 L2 记忆，可被聊天/做梦炼化为 L3 元习惯
```

---

## 四、核心模块详解

### 4.1 L1 记忆草稿 — 注意力门控

**来源**: 对话历史（由宿主 Agent 提供）

**职责**: 从原始对话中筛选出值得记忆的内容

**机制**:
- 规则匹配: 15+ 种模式（"我叫"、"请记住"、"我喜欢"等，沿用 HomeGenie）
- 轻量分类: 本地小模型判断"这段对话有长期价值吗？"
- 去噪: 过滤寒暄、重复、无信息量的内容

**输出**: 结构化的记忆条目，带领域标注，送入 L2

### 4.2 L2 记忆笔记 — 3D 金字塔

**核心思想**: 像 3D NAND 一样，不在单一维度上做到极致，而是通过升维获得效率飞跃。

**三维索引**:

```
维度 X — 领域 (domain): 工作/学习/健康/生活/...
维度 Y — 时间 (time):   事件的时间戳和因果链
维度 Z — 抽象层级 (level):
  Level 0 (事实): "3月5日用户说想自己写解析器"
  Level 1 (模式): "用户偏好自造工具而非用现成方案"
  Level 2 (原则): "用户高度重视自主性"
```

**检索效率** (注意力式，类似 Transformer Attention):

```
传统: 搜索全部 300 条事实 → O(300)
金字塔: 先搜 3 条原则 → 命中 → 展开 ~10 条模式 → 展开 ~30 条事实 → O(43)
效率提升: ~7x
```

**存储实现**:

```sql
CREATE TABLE memories (
  id INTEGER PRIMARY KEY,
  content TEXT,
  domain TEXT,           -- X: 领域
  timestamp INTEGER,     -- Y: 时间
  level INTEGER,         -- Z: 抽象层级 (0=事实, 1=模式, 2=原则)
  parent_id INTEGER,     -- 垂直通道（类似 3D NAND 的 TSV）
  embedding BLOB,        -- 向量 (sqlite-vec)
  hit_count INTEGER DEFAULT 0,
  last_hit_at INTEGER,
  decay_count INTEGER DEFAULT 0
);

CREATE INDEX idx_3d ON memories(domain, level, timestamp);
```

**聚合机制**: 当同一领域的事实层累积足够多条（如 10+）时，触发聚合——用本地小模型将事实总结为模式，多个模式再总结为原则。

### 4.3 L3 习惯记忆 — 双炼化引擎

#### 存储: HDC 超维向量 + LoRA

**HDC 层** — 即时可查的压缩记忆:

```python
DIM = 10000  # 超维度

# 核心操作（~50 行代码，零依赖）
bind(a, b)     = a * b          # 编码关联
bundle(*vecs)  = sign(sum(vecs)) # 叠加多条习惯
similarity     = dot(a, b) / DIM # 余弦查询

# 习惯编码示例
habit = bind(random_hv("用户"), random_hv("重视自主性"))
all_habits = bundle(habit1, habit2, ...)  # 一个向量存所有
```

**LoRA 层** — 深度内化的参数记忆:

```
定期（如每周）:
  L3 习惯记忆 → 生成训练 JSONL
  → MLX LoRA 微调 (Mac) / QLoRA (Linux GPU)
  → 个人 adapter 导出
  → Ollama Modelfile 加载

结果: Agent 不需要检索就"知道"用户的习惯
      就像你不需要"检索"火是烫的这个事实
```

**微调在 Mac 上的实际表现** (Apple Silicon):

| 模型 | 量化后大小 | 训练内存 | 500 轮耗时 |
|------|----------|---------|-----------|
| Qwen3 0.6B (4-bit) | ~400MB | ~2.5GB | ~5 分钟 |
| Phi-3.5 3B (4-bit) | ~2.5GB | ~5GB | ~15-30 分钟 |

#### "聊天"炼化 — 三体博弈

**灵感**: 三国演义的三方制衡 + 三体问题的复杂涌现。两方容易吞并或妥协，三方互相牵制产生更稳健的结论。

**学术支撑**: ICLR 2025 DMAD — 异构 3-Agent 在 GSM-8K 上 91% vs 同构 2-Agent 的 82%。

**角色设计**:

```
守护者 (Wei/魏) — 利益: 一致性
  "这条新记忆和已有习惯一致吗？"
  奖励: 新记忆与已有习惯的 coherence score

探索者 (Wu/吴) — 利益: 新颖性
  "这是新模式！值得记录！"
  奖励: 新记忆与已有记忆的 distance score

精简者 (Shu/蜀) — 利益: 简洁性
  "真的需要这条吗？能和已有的合并吗？"
  奖励: 总记忆条数的减少量
```

**博弈规则**:
- 三方各出论点 → 投票（2:1 通过）
- 三方各持不同意见 → 记录为"候选"，下次再议
- 持续僵局 → 提交给用户裁决（极少数情况）
- 新洞察标记"候选"，需后续对话验证才确认

**模型选择**: 建议异构——如守护者用 Qwen（中文理解强）、探索者用 Gemma（创造性好）、精简者用 Phi（逻辑紧凑）。三个小模型成本可能低于一次大模型调用。

**示例**:

```
守护者: "用户3月说运动改善了睡眠"
探索者: "但4月说加班后即使运动了也睡不好，
         改善睡眠的可能不是运动本身，而是运动带来的规律作息"
精简者: "综合: 规律作息是睡眠质量的核心变量，运动是手段而非目的。
         建议合并原有两条为一条更精确的习惯。"
→ 2:1 通过 → 候选洞察 → 等待验证
```

#### "做梦"炼化 — 神游式思考

**灵感**: 突触稳态假说 (SHY, Tononi & Cirelli) + 默认模式网络 (DMN)

**学术支撑**:
- NeuroDream (2026): 做梦阶段使遗忘减少 38%，零样本迁移提高 17.6%
- Claude Code AutoDream: 已在生产环境验证记忆修剪的可行性

**三阶段流程**:

```
Phase 1 — 修剪 (SHY 突触稳态):
  - 矛盾记忆 → 保留更新的/更多验证的
  - 冗余记忆 → 合并
  - 30 天未被检索命中 → 标记"衰减"
  - 衰减 3 次 → 移入"遗忘区"（降权，不真删）

Phase 2 — 神游 (DMN 自由联想):
  - 随机挑选 3-5 条看似不相关的习惯记忆
  - 寻找隐藏的关联模式
  - 例: "讨厌被催促" + "喜欢自主选择" + "偏好自己造工具"
    → "用户高度重视自主性 (autonomy)"
  - 跨领域 meta-pattern 是最高价值记忆

Phase 3 — 梦境记录:
  - 修剪结果 → 直接执行
  - 神游发现 → 标记候选 + 置信度
  - 下次检索命中时追踪验证
```

### 4.4 L4 外挂知识 — "让记忆去读书"

**核心思想**: 人类大部分知识不是亲身经历的，而是通过语言/书籍/教育从他人处获得的。RadioMind 的 Shortwave 机制就是"让记忆系统自己去读书"。

**来源**:
- RadioHeader 的 Learn 命令（URL → 提取 → 提纯）
- Shortwave 库（跨领域通用知识）
- 社区共享池（Stigmergy 模型）

**关键规则**: 外挂知识**不直接进入 L3 习惯记忆**。它进入 L2 事实层，然后走和亲身经验相同的巩固路径（聊天/做梦炼化）。这保证了外挂知识的质量——只有经过炼化检验的才会成为习惯。

**从 RadioHeader 继承的概念映射**:

| RadioHeader | RadioMind | 变化 |
|-------------|-----------|------|
| 项目 (Project) | 领域 (Domain) | 编程项目 → 生活领域 |
| `[source:ProjectName]` | `[domain:DomainName]` | 来源标注 |
| Topics (项目经验) | Topics (领域经验) | 扩大范围 |
| Shortwave (通用技术知识) | Shortwave (通用生活智慧) | 去领域化 |
| Search→Apply→Trace | Search→Apply→Trace | 不变 |

### 4.5 Meta 元认知层 — 双侧写

**核心思想**: 大脑不仅知道自己知道什么，还知道自己*不知道*什么。RadioMind 需要同时了解用户和了解自己。

#### 用户侧写 (User Profile)

```
WHO — 用户是谁:
  角色/身份、知识水平、语言偏好

HOW — 用户怎么工作:
  沟通风格、决策模式、偏好/禁忌

WHAT — 用户关注什么:
  活跃领域、当前目标、长期愿景
```

#### 系统自画像 (Self Profile)

```
IDENTITY — 我是什么:
  当前推理模型及其能力、可用工具列表、通道配置
  
STATE — 我现在怎么样:
  记忆库大小/健康度、上次做梦/聊天时间、网络状态、资源使用率
  
CAPABILITY — 我能做什么:
  擅长/薄弱的领域、配置变更历史、已知局限
```

#### 自画像的运行时自省（不写死）

```
错误 ❌: config.toml 写 model = "qwen3-0.6b"，代码里 if model == "qwen3-0.6b"
正确 ✅: config.toml 写 model = "qwen3-0.6b"（用户可改）
         自画像运行时生成: "当前推理模型: qwen3-0.6b (0.5B, 本地, 34t/s)"
         用户改成 claude-sonnet 后自动更新:
         "当前推理模型: claude-sonnet (云端, ~80t/s, 需要网络)"
```

**自画像更新时机**:

| 事件 | 更新内容 |
|------|---------|
| 配置变更 | 模型/通道/存储后端 |
| 每次"做梦" | 记忆库统计（大小、健康度、各层占比） |
| 工具增减 | 可用能力列表 |
| 性能异常 | 检索耗时突增、模型响应变慢 |
| 版本升级 | 新增/移除的功能模块 |

#### 元认知参与炼化

双侧写本身也是 L2 记忆，可以被三体聊天和做梦炼化。这产生**元习惯**——系统关于自身行为的优化洞察：

```
三体聊天示例:

守护者: "L2 记忆笔记已有 8,000 条"（引用自画像 STATE）
探索者: "用户近三周主要聊'健康'，但健康模式层只有 5 条"
         （交叉引用用户侧写 + 自画像）
精简者: "建议: 触发健康专项聊天炼化 + 修剪工作领域冗余"

→ 元习惯: "当领域对话频率与记忆密度不匹配时，主动触发该领域的聊天炼化"
```

---

## 五、炼化触发与成本策略

### 5.1 触发时机（按接入环境分策略）

| 接入环境 | 类型 | "聊天"触发 | "做梦"触发 |
|---------|------|-----------|-----------|
| RadioHand/OpenClaw/HomeGenie | Agent 框架 | 同一话题被检索 3+ 次 | Cron 定时（空闲时） |
| RadioHeader/Claude Code | 编程工具 | 项目 Echo 写入时 | Stop hook / 会话结束时 |
| Hermes Agent | Memory Provider | `sync_turn()` 累计 N 次后 | `on_session_end()` |
| 独立运行 | CLI/API | 用户手动 `radiomind chat` | `radiomind dream` 或 cron |

类比大脑节律：
- "聊天" = 白天的精细化复述 → 在活跃使用时触发
- "做梦" = 夜间的突触修剪 → 在空闲/会话结束时触发

### 5.2 炼化成本（透明分级）

```
省电模式 (默认):
  本地 0.5B 模型 (Qwen3-0.6B via Ollama)
  三体各一轮 ≈ 900 token, ~10s, 费用 $0

标准模式:
  本地 3B 模型 (Phi-3.5-mini via Ollama)
  三体各一轮 ≈ 1500 token, ~30s, 费用 $0

深度模式 (用户主动触发):
  云端大模型 (DeepSeek/Claude)
  三体各一轮 ≈ 3000 token, ~5s, 费用 ~$0.003
```

**原则**: 有低成本模型则用低成本的，没有则用可用的，但**必须让用户知道**当前使用的模式和预估成本。

---

## 六、接口设计

### 6.1 通用记忆模块接口

RadioMind 对外暴露的标准接口（宿主 Agent 通过此接口调用）：

```python
class RadioMindInterface:
    # 生命周期
    def initialize(config: dict) -> None
    def shutdown() -> None
    
    # L1 写入
    def ingest(conversation: list[Message]) -> list[MemoryEntry]
    
    # L2 检索
    def search(query: str, domain: str = None) -> list[MemoryEntry]
    def search_pyramid(query: str, start_level: int = 2) -> list[MemoryEntry]
    
    # L3 查询
    def query_habits(query: str) -> list[Habit]
    
    # 炼化
    def trigger_chat(domain: str = None) -> ChatResult
    def trigger_dream() -> DreamResult
    
    # Meta
    def get_user_profile() -> UserProfile
    def get_self_profile() -> SelfProfile
    def get_context_digest(token_budget: int = 250) -> str
    
    # 外挂知识
    def learn(url: str) -> list[MemoryEntry]
    
    # 配置
    def update_config(key: str, value: any) -> None
```

### 6.2 Hermes Memory Provider 适配

```python
class RadioMindHermesProvider(MemoryProvider):
    @property
    def name(self) -> str: return "radiomind"
    
    def system_prompt_block(self) -> str:
        return self.mind.get_context_digest(token_budget=250)
    
    def prefetch(self, query: str) -> str:
        habits = self.mind.query_habits(query)
        notes = self.mind.search_pyramid(query)
        return self.format(habits, notes)
    
    def sync_turn(self, user_msg, assistant_msg):
        self.mind.ingest([user_msg, assistant_msg])
        self._turn_count += 1
        if self._turn_count % 10 == 0:
            self.mind.trigger_chat()  # 累计 10 轮后触发聊天
    
    def on_session_end(self, messages):
        self.mind.trigger_dream()
```

---

## 七、技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| **v0.1-v0.2 核心** | Python | 快速验证、跨平台、所有目标 Agent 框架都有 Python 接口 |
| **v0.3+ 核心** | Rust + Python 插件 | Rust 守护进程(存储/检索/调度)、Python 插件(炼化/MLX) |
| **L2 存储** | SQLite + sqlite-vec | 单文件、零运维、3D 索引 + 向量搜索 |
| **L3 存储 (HDC)** | NumPy / 纯 Rust | 核心 ~50 行，零依赖 |
| **L3 存储 (LoRA)** | MLX (Mac) / QLoRA (Linux) | Mac 原生优化，Linux 用 CUDA |
| **推理 (LoRA)** | Ollama + ADAPTER 指令 | 热加载 LoRA，<1s 切换 |
| **推理 (炼化)** | Ollama (本地) / OpenAI API (云端) | 本地优先，云端可选 |
| **Embedding** | ONNX MiniLM-L6-v2 (384维) | 86MB、无 torch（沿用 HomeGenie） |
| **经验文件** | Markdown + YAML frontmatter | 人类可读可编辑（沿用 RadioHeader） |
| **配置** | TOML | 所有外部依赖通过配置声明，不写死 |
| **接口协议** | IPC (Unix socket) + MCP + Python API | 多种接入方式 |

---

## 八、从自有项目继承的核心经验

### 8.1 来自 RadioHeader 的经验

| 经验 | 教训 | RadioMind 如何应用 |
|------|------|-------------------|
| **Context-Digest 预算控制** | 注入超过 3,500 字符拖慢响应 | Meta 层摘要严控 250 token |
| **Shortwave > Topics** | 去项目化后命中率更高 | 经验提纯是核心，Topics 只是中间产物 |
| **症状关键词 > 解法关键词** | 用户搜问题不搜答案 | 存储时保留"用户原话" + "提纯结论" |
| **行为指令 > 知识描述** | MUST 比建议有效 10 倍 | 行为契约用强制指令 |
| **PostToolUse Hook 是关键** | 无 Hook 验证 Agent 会偷懒 | 行为契约必须有 Hook 层 |
| **贪婪加载是反模式** | 启动时全量扫描导致慢启动 | 严格 lazy loading |

### 8.2 来自 HomeGenie 的经验

| 经验 | 教训 | RadioMind 如何应用 |
|------|------|-------------------|
| **三层搜索降级** | embedding 不可用时不能挂 | L2 保留 LIKE 兜底 |
| **Rust 核心 + Python 插件** | 核心要稳，AI 要灵活 | 沿用分工 |
| **去 OpenClaw 省 1.7GB** | Node.js 代价太大 | 不引入 Node.js |
| **意图分类门控省钱** | 70% 请求不需要上云 | 本地分类 + 路由 |
| **记忆自动提取规则模式** | 15 种短语匹配简单有效 | L1 注意力门控沿用 |
| **IPC 优于 HTTP** | Unix socket 延迟远低于 HTTP | 本地通信走 IPC |

---

## 九、MVP 范围（v0.1）

### 目标: 证明"炼化"机制的价值（草稿→笔记→习惯的完整路径）

**v0.1 包含**:
- [ ] Python 包（先验证核心逻辑，Rust 重写留 v0.2+）
- [ ] L1 记忆草稿: 对话输入 + 注意力门控
- [ ] L2 记忆笔记: 3D 金字塔 (SQLite + sqlite-vec)
- [ ] L3 习惯记忆: HDC 超维编码（纯 NumPy，~50 行）
- [ ] "聊天"炼化: 三体博弈（本地 Ollama 0.5B 模型）
- [ ] "做梦"炼化: 修剪 + 神游（本地 Ollama）
- [ ] Meta 双侧写: 用户侧写 + 系统自画像
- [ ] CLI 接口: `radiomind ingest`, `search`, `chat`, `dream`, `status`
- [ ] 标准 Python API（供宿主 Agent 调用）

**v0.1 不包含**:
- LoRA 微调闭环（v0.2 — 需要 MLX 集成）
- Hermes Memory Provider 适配（v0.2）
- RadioHeader 适配（v0.2 — 替换现有 memory 层）
- Rust 重写（v0.3）
- MCP Server（v0.3）
- 社区共享（远期）
- RadioHand Agent 框架（独立项目）

---

## 十、设计决策记录

| 问题 | 结论 | 理由 |
|------|------|------|
| 产品定位 | 独立记忆核心，非 Agent 框架 | Agent 框架竞争激烈，记忆炼化无人做 |
| 记忆架构 | 四层仿生 + Meta 元认知 | 对标大脑互补学习系统 |
| 炼化机制 | 三体聊天 + 神游做梦 | ICLR 2025 验证三方优于双方 |
| 技术路线 | 金字塔(L2) + HDC(L3) + LoRA(深层) | 金字塔=注意力机制, HDC=简洁零依赖 |
| Mac 兼容 | MLX 训练 + Ollama 推理 | bitsandbytes 不支持 Apple Silicon |
| 配置原则 | 一切不写死，运行时自省 | 用户可能更改 LLM/后端/通道 |
| 领域管理 | 不预设，从对话中自然生长 | 仿生：大脑的分类从经验涌现，非预装 |
| 隐私策略 | 隐私项不外流 + 记忆口令身份验证 | 强记忆项作为口头密码，比传统密码更自然且难伪造 |
| 开源许可 | MIT | 与 RadioHeader/Hermes 一致，采用门槛最低 |
| 产品命名 | Radio 家族: Header(规则) + Mind(记忆) + Hand(执行) | 头定规则、脑存记忆、手去执行 |
| 项目范围 | 本项目只聚焦 RadioMind 记忆模块 | RadioHand 为独立项目 |
| v0.1 语言 | Python 先行 → v0.3 Rust 核心 | Python 跨平台兼容所有目标 Agent 框架 |

---

## 十一、项目元信息

- **Tech stack**: Python (v0.1) → Rust + Python (v0.3+) | SQLite + HDC + MLX
- **License**: MIT
- **Status**: 架构设计完成，所有设计决策已确认，待进入 v0.1 开发
- **Repository**: 待创建
- **Related projects**:
  - RadioHeader (经验层来源): `~/DarkForce/RadioHead/radioheader/`
  - HomeGenie (运行时参考): `~/DarkForce/HomeGenie/`
  - RadioHand (Agent 框架，规划中): TBD
- **Key paths**:
  - `CLAUDE.md` / `AGENTS.md`: 项目入口索引
  - `.claude/rules/`: 项目规则
  - `projectBasicInfo/`: 项目文档
  - `projectBasicInfo/logs/`: 实施记录
