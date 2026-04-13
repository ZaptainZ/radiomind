# RadioMind — 仿生记忆核心

**为 AI Agent 提供"越用越懂你"的深层记忆能力。**

> *不是又一个向量数据库。RadioMind 通过仿生的"聊天"和"做梦"机制，将零散对话炼化为深层习惯记忆，并确保 Agent 真正使用它们。*

[English](README.md) · [架构](#架构四层仿生记忆) · [快速开始](#快速开始) · [接入方式](#接入方式) · [文档](docs/)

**文档：** [Quickstart](docs/quickstart.md) · [集成指南](docs/integration.md) · [API 参考](docs/api-reference.md)

---

## 为什么选 RadioMind？

2026 年的 AI 记忆框架（Mem0、Zep、mempalace……）全部聚焦在"存"和"检索"上。**没有一个在"思考"自己存了什么。**

RadioMind 受神经科学启发——海马体快速编码、新皮层慢速巩固、睡眠中的突触修剪——它不只是记忆，而是将记忆**炼化为习惯**：

| 能力 | 现有框架 | **RadioMind** |
|------|---------|---------------|
| 存储检索 | ✅ | ✅ |
| 跨领域经验流动 | ❌ | ✅ Shortwave 提纯 |
| 主动炼化 | ❌ | ✅ 三体辩论 + 做梦修剪 |
| 强制记忆使用 | ❌ | ✅ 搜→用→追 行为契约 |
| LoRA 内化 | ❌ | ✅ 习惯→训练数据→MLX→adapter |
| 隐私分级 | ❌ | ✅ 开放/半开/封闭，按领域配置 |
| 自我意识 | ❌ | ✅ 双侧写（用户+系统自画像） |

## 架构：四层仿生记忆

```
Meta 元认知 ─── 用户侧写 + 系统自画像（运行时自省，不写死）
L4 外挂知识 ─── Shortwave 库："让记忆去读书"
L3 习惯记忆 ─── HDC 超维向量 + LoRA adapter（新皮层）
     ├─ "聊天"炼化: 三体博弈（守护者/探索者/精简者）
     └─ "做梦"炼化: SHY 修剪 + DMN 神游
L2 记忆笔记 ─── 3D 金字塔 (domain × time × level)（海马体）
L1 记忆草稿 ─── 注意力门控（工作记忆）
L0 本能 ─────── 基模权重（可更换，不绑定）
```

**神经科学映射：**

| 大脑结构 | 功能 | RadioMind |
|---------|------|-----------|
| 前额叶 | 工作记忆 | L1 注意力门控 |
| 海马体 | 情节记忆快速编码 | L2 3D 金字塔 |
| 新皮层 | 语义记忆慢速巩固 | L3 HDC + LoRA |
| 睡眠 (SHY) | 突触修剪 | "做梦"炼化 |
| 社会学习 | 检索练习 + 讨论 | "聊天"炼化 |
| 文化传承 | 书籍、教育 | L4 Shortwave |
| 元认知 | 自我意识 | 双侧写 |

### 三体辩论（"聊天"炼化）

灵感来自三国演义的三方制衡 + 三体问题的复杂涌现。两方容易吞并或妥协，三方互相牵制产生更稳健的结论：

- **守护者 (魏)**: 新记忆和已有习惯一致吗？
- **探索者 (吴)**: 这是不是新模式？值得记录！
- **精简者 (蜀)**: 真的需要吗？能和已有的合并吗？

三方各出论点 → 投票（2:1 通过）→ 候选洞察 → 后续验证确认。

### 做梦炼化

对标突触稳态假说 (SHY, Tononi & Cirelli)：

1. **修剪**: 矛盾消解 / 冗余合并 / 未使用记忆衰减归档
2. **神游**: 随机挑选不相关的记忆，寻找隐藏的跨域关联
3. **梦境记录**: 修剪直接执行，神游发现标记候选+置信度

### Rust 守护进程

热路径运行在 Rust 守护进程中，支持 10 万+ 条记忆和 7×24 常驻：

```
Python 逻辑层（LLM 调用、prompt、训练）
       ↕ Unix socket JSON Lines
Rust 守护进程（SQLite、FTS5、HDC、知识图谱，16 个 IPC 方法）
```

## 快速开始

```bash
pip install radiomind
```

```python
from radiomind import RadioMind
from radiomind.core.types import Message

mind = RadioMind()
mind.initialize()

# 导入对话
mind.ingest([
    Message(role="user", content="我叫小明"),
    Message(role="user", content="我喜欢跑步"),
])

# 搜索（金字塔：原则→模式→事实）
results = mind.search("运动")

# 三体辩论
mind.trigger_chat()

# 做梦
mind.trigger_dream()

# 上下文摘要（注入 system prompt）
digest = mind.get_context_digest()

mind.shutdown()
```

### CLI 命令

```bash
radiomind init                     # 初始化
radiomind ingest chat.jsonl        # 导入对话
radiomind search "跑步"            # 金字塔搜索
radiomind chat                     # 三体辩论
radiomind dream                    # 做梦炼化
radiomind train --iters 100        # LoRA 微调
radiomind status                   # 统计
radiomind community sync           # 同步社区知识
radiomind mcp-server               # 启动 MCP 服务
```

### 接入方式

| 方式 | 命令 |
|------|------|
| Python API | `from radiomind import RadioMind` |
| CLI | `radiomind search "query"` |
| MCP Server | `claude mcp add radiomind -- radiomind mcp-server` |
| Hermes Agent | `hermes config set memory.provider radiomind` |
| RadioHeader | `radiomind migrate-radioheader` |

## 配置

`~/.radiomind/config.toml` — 一切不写死：

```toml
[llm]
default_backend = "openai"

[llm.openai]
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-plus"

[llm.models]
economy = "qwen-turbo"      # 日常炼化
standard = "qwen-plus"      # 更好质量
deep = "qwen-max"           # 深度思考

[refinement]
cost_mode = "economy"
```

## Radio 家族

| 项目 | 角色 | 隐喻 |
|------|------|------|
| [RadioHeader](https://github.com/ZaptainZ/radioheader) | 规则与跨项目经验 | 头 |
| **RadioMind** | 仿生记忆核心 | 脑 |
| RadioHand | 个人 Agent 框架 | 手 |

```
头定规则 → 脑存记忆 → 手去执行
```

## 许可

MIT
