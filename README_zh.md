# RadioMind

**一个能从对话中学习的记忆模块——插入任何 AI Agent 即可使用。**

```python
import radiomind

mind = radiomind.connect()
mind.add([{"role": "user", "content": "我每天跑步，睡眠质量明显提升了"}])
mind.search("健康习惯")          # 几周后仍能找到
print(mind.digest())             # "User: 每天跑步, 重视睡眠质量"
```

4 个方法，零配置。你的 Agent 记住一切，且越用越聪明。

[English](README.md) · [Quickstart](docs/quickstart.md) · [集成指南](docs/integration.md) · [API 参考](docs/api-reference.md)

---

## 它做什么

大多数 AI 记忆系统只是存文本、搜文本。RadioMind 更进一步——它**把对话提炼成习惯**：

- "我喜欢跑步" + "跑步后睡得好" → **习惯：** *"运动能改善这个用户的睡眠质量"*
- 这个习惯会**跨领域**影响未来的对话——工作、健康、学习，什么场景都行。

| | 典型记忆系统 (Mem0, Zep 等) | RadioMind |
|---|---|---|
| 存储搜索 | ✅ | ✅ |
| 从对话提炼习惯 | ❌ | ✅ |
| 跨领域洞察（健康经验改善工作建议） | ❌ | ✅ |
| 不花额外 LLM 费用就变聪明 | ❌ | ✅ |
| 按话题设置隐私 | ❌ | ✅ |
| 了解自身状态（元认知） | ❌ | ✅ |

## 安装使用

```bash
pip install radiomind
```

```python
import radiomind

mind = radiomind.connect()

# 你的 Agent 对话循环中：
mind.add(messages)                    # 喂入对话
results = mind.search("query")       # 取回相关记忆
system_prompt = mind.digest()        # 注入用户上下文（~250 tokens）
mind.refine()                        # 提炼习惯（自动）
```

这就是全部 API。领域检测、隐私标记、习惯编码、记忆修剪——内部全自动。

**兼容任何框架：**

```python
# 传入你现有的 LLM 客户端 — RadioMind 自动识别类型
mind = radiomind.connect(llm=openai_client)
mind = radiomind.connect(llm=anthropic_client)
mind = radiomind.connect(llm=lambda prompt, system: my_llm(prompt))

# 或者环境变量里有 API key — RadioMind 自动找到
# OPENAI_API_KEY, ANTHROPIC_API_KEY, DASHSCOPE_API_KEY, DEEPSEEK_API_KEY...
# 支持 11 个 provider，不需要配置文件。
```

## 接入你的技术栈

| 方式 | 一行接入 | 适用场景 |
|------|---------|---------|
| **Python** | `radiomind.connect()` | 任何 Python Agent |
| **MCP** | `claude mcp add radiomind -- radiomind mcp-server` | Claude Desktop、Cursor、VS Code |
| **REST** | `radiomind serve --port 8730` | 任何语言、远程调用 |
| **CLI** | `radiomind search "query"` | 脚本、定时任务、Hook |

9 个 MCP 工具，6 个 REST 端点，20+ CLI 命令。详见[集成指南](docs/integration.md)。

### 在 AI 助手中运行（Claude Code、Codex、Hermes）

在 AI 助手内部运行时，RadioMind 让**助手自己来思考**——不需要额外的 LLM 调用，不花额外费用：

```
你的 AI 助手调用: radiomind_refine_step("prepare", domain="health")
RadioMind 返回:   "这里有 10 条健康记忆。作为守护者，请评估..."
助手自己推理:     "这些记忆一致显示运动改善睡眠..."
RadioMind 记录洞察，进入下一步。
```

助手扮演三个辩论角色（守护者、探索者、精简者），RadioMind 把结果提炼成持久习惯。零额外 API 调用。

---

## 原理（感兴趣可以展开）

<details>
<summary><b>架构——模拟大脑真实的记忆方式</b></summary>

RadioMind 模拟大脑的互补学习系统：

```
Meta ─── 用户画像 + 系统自画像
L4 ───── 外挂知识（"让记忆去读书"）
L3 ───── 习惯记忆: HDC 超维向量 + LoRA adapter（新皮层）
           ├─ "聊天"炼化: 三体辩论
           └─ "做梦"炼化: 修剪 + 自由联想
L2 ───── 记忆笔记: 3D 金字塔 (domain × time × level)（海马体）
L1 ───── 注意力门控: 从对话中提取事实（工作记忆）
L0 ───── 基模权重（可更换，不绑定）
```

| 大脑 | 功能 | RadioMind |
|------|------|-----------|
| 前额叶 | 工作记忆 | L1 注意力门控 |
| 海马体 | 快速编码 | L2 3D 金字塔 (SQLite FTS5) |
| 新皮层 | 慢速巩固 | L3 HDC + LoRA |
| 睡眠 (SHY) | 突触修剪 | "做梦"炼化 |
| 社会学习 | 讨论+回忆 | "聊天"三体辩论 |
| 文化记忆 | 书籍、教育 | L4 Shortwave 库 |

</details>

<details>
<summary><b>三体辩论——为什么是三个角色而不是两个</b></summary>

两方辩论容易吞并或妥协。三方各有利益冲突时才能产生稳健结论（ICLR 2025 DMAD: 91% vs 82%）。

```
守护者 (魏) — "这和我们已知的一致吗？"
探索者 (吴) — "这里有什么新东西？"
精简者 (蜀) — "能不能简化？"

投票: 三方中两方同意 → 候选洞察 → 未来对话中验证
```

灵感来自三国的三方制衡和三体问题的复杂涌现。

</details>

<details>
<summary><b>LoRA 训练——不需要检索的记忆</b></summary>

定期把习惯微调进本地小模型（0.5-3B）：

```bash
radiomind train --iters 100    # MacBook 上约 5 分钟，用 Apple MLX
```

训练后，模型"直接知道"用户的偏好——就像你知道火是烫的，不需要"检索"。Adapter 只有几 MB，加载不到 1 秒。

</details>

<details>
<summary><b>Rust 守护进程——10 万+ 条记忆和 7×24 运行</b></summary>

存储热路径运行在 Rust 守护进程中：

```
Python 逻辑层（LLM 调用、prompt、训练）
       ↕ Unix socket JSON Lines
Rust 守护进程（SQLite、FTS5、HDC、知识图谱，16 个 IPC 方法）
```

```bash
cd rust-core && cargo build --release
./target/release/radiomind-daemon
```

Python 自动检测 daemon 并通过 IPC 路由操作。

</details>

<details>
<summary><b>隐私——有些话题不出圈</b></summary>

每个领域有独立的隐私级别：

- **open** — 自由跨域流动（默认）
- **guarded** — 只有模式/原则跨域，原始事实不出圈（健康、理财自动标记）
- **sealed** — 完全隔离，绝不跨域

</details>

---

## Radio 生态

| 项目 | 做什么 |
|------|--------|
| **[RadioHeader](https://github.com/ZaptainZ/radioheader)** | 编程 Agent 的跨项目经验框架 |
| **RadioMind** | 仿生记忆模块（本仓库） |
| **RadioHand** | 个人 Agent 框架（规划中） |

RadioMind 是 RadioHeader 和 RadioHand 的默认记忆后端，但可以独立接入任何 Agent。

## 研究基础

基于：互补学习系统 (McClelland 1995)、突触稳态假说 (Tononi & Cirelli 2006)、超维计算 (Kanerva 2009)、多 Agent 辩论 (ICLR 2025 DMAD)、LoRA (Hu 2021)、NeuroDream (2026)、信息素模型 (Grassé 1959)。

## 许可

MIT
