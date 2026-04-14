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

## RadioMind 给 AI 助手带来了什么

接入 Claude Code、Codex、Hermes 或任何 MCP 工具后，RadioMind 给助手增加了它原本没有的能力：

| 能力 | 没有 RadioMind | 有 RadioMind |
|------|--------------|-------------|
| **跨会话记忆** | 每次对话后遗忘 | 记住一切，永不丢失 |
| **了解用户** | 每次从零开始 | 知道你的名字、偏好、习惯、目标 |
| **从错误中学习** | 反复犯同样的错 | "上次这种方法失败了，因为..." |
| **关联不同话题** | 每个话题是孤岛 | "你的失眠可能和上周提到的加班有关" |
| **越用越聪明** | 能力始终不变 | 持续积累习惯，深化理解 |
| **尊重隐私** | 没有敏感度概念 | 健康数据受保护，封闭话题绝不泄露 |

助手负责所有的思考——RadioMind 只负责组织和存储。**零额外 LLM 费用。**

---

## 记忆是如何工作的

一段对话进入 RadioMind 后，像大脑一样逐层流动：

```
对话 → "我开始跑步了，睡眠质量提升了"
 │
 ▼
┌─ L1 注意力门控 ────────────────────────────────┐
│  提取: 跑步 + 睡眠的事实                        │
│  检测: 领域 = 健康                              │
│  标记: 隐私 = guarded（健康数据默认受保护）      │
└────────────────────────────┬────────────────────┘
                             ▼
┌─ L2 记忆笔记（3D 金字塔）──────────────────────┐
│  存为事实: "跑步改善睡眠"                       │
│  索引: 领域 × 时间 × 抽象层级                   │
│  累计 10+ 条事实 → 总结为模式                    │
│  累计 3+ 条模式 → 提炼为原则                     │
└────────────────────────────┬────────────────────┘
                             ▼
┌─ L3 习惯记忆 ──────────────────────────────────┐
│  三体辩论:                                      │
│    守护者: "和已知的一致"                        │
│    探索者: "新模式: 运动→睡眠"                   │
│    精简者: "和已有健康习惯合并"                   │
│  → 编码为 HDC 超维向量 (10,000-bit)             │
│  → 定期烘焙进 LoRA 权重                         │
└────────────────────────────┬────────────────────┘
                             ▼
┌─ L4 外挂知识 ──────────────────────────────────┐
│  Shortwave 库: 来自文章、文档、社区的            │
│  精选知识 —— "让记忆去读书"                     │
└────────────────────────────────────────────────┘

Meta 层（始终活跃）:
  用户画像: 是谁、怎么工作、关注什么
  系统自画像: 用的什么模型、有多少记忆、当前状态
```

**每一层对应一个大脑结构：**

| 大脑结构 | 它在大脑中做什么 | RadioMind |
|---------|--------------|-----------|
| 前额叶 | 同时保持 5-9 个焦点，决定什么值得编码，从意识流中过滤噪声 | L1 — 注意力门控：匹配 15+ 种触发模式（"我叫..."、"请记住..."），自动检测领域，标记隐私 |
| 海马体 | 快速记录经历并附带时空上下文，充当新皮层可查询的快速索引 | L2 — 3D 金字塔：SQLite FTS5，按领域 × 时间 × 抽象层级索引，注意力式检索（原则→模式→事实） |
| 新皮层 | 通过反复接触，将经历慢慢整合为泛化知识，形成不依赖具体情节的抽象理解 | L3 — 习惯记忆：三体辩论将模式提炼为习惯，编码为 HDC 10,000-bit 超维向量，定期烘焙进 LoRA 模型权重 |
| 睡眠 (SHY) | 全局缩小突触强度，保留常用连接、修剪很少激活的，重播重要记忆 | "做梦"炼化：衰减 30+ 天未访问的记忆，合并冗余条目，跨领域自由联想发现元模式 |
| 社会对话 | 通过检索练习和精细化讨论强化记忆，通过辩论创造新连接 | "聊天"炼化：三个目标冲突的 Agent（一致性、新颖性、简洁性）辩论投票，产出单一视角无法发现的洞察 |
| 书籍与文化 | 不需要亲身经历就能获取知识，通过语言和共享叙事传递 | L4 — Shortwave 库：从文章和社区中采集知识，作为事实进入 L2，走和个人经验相同的巩固路径 |

### 深入了解

<details>
<summary><b>三体辩论——为什么是三个角色而不是两个</b></summary>

两方辩论容易吞并或妥协。三方各有利益冲突时才能产生稳健结论（ICLR 2025 DMAD: 91% vs 82%）。

```
守护者 (魏) — "这和我们已知的一致吗？"    → 奖励一致性
探索者 (吴) — "这里有什么真正新的东西？"   → 奖励新颖性
精简者 (蜀) — "能不能简化或合并？"         → 奖励简洁性

投票: 三方中两方同意 → 候选洞察 → 未来对话中验证
```

灵感来自三国：两方容易一方吞并另一方；三方才能长期制衡。

</details>

<details>
<summary><b>LoRA 训练——不需要检索的记忆</b></summary>

定期把习惯微调进本地小模型（0.5-3B）：

```bash
radiomind train --iters 100    # MacBook 上约 5 分钟 (Apple MLX)
```

训练后，模型"直接知道"用户的偏好——就像你知道火是烫的，不需要"检索"。Adapter 只有几 MB，加载不到 1 秒。

Mac (MLX)、Linux (QLoRA/CUDA) 都支持，没装则优雅跳过。

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

Python 自动检测 daemon，未运行时回退到直连 SQLite。

</details>

<details>
<summary><b>隐私分级——有些话题不出圈</b></summary>

每个领域有独立的隐私级别：

- **open** — 自由跨域流动（默认）
- **guarded** — 只有模式/原则跨域，原始事实不出圈（健康、理财自动标记）
- **sealed** — 完全隔离，绝不跨域

"跑步改善睡眠"可以作为原则（"规律作息提升表现"）影响工作建议，但原始健康事实不会暴露。

</details>

---

## 安装

### 一行安装 + 激活

```bash
pip install radiomind && radiomind setup
```

`radiomind setup` 自动检测你的平台并配置一切：

| 平台 | 自动配置 |
|------|---------|
| Claude Code | Hooks（每 15 条消息自动保存 + 压缩前紧急保存）+ MCP（9 工具） |
| Codex CLI | hooks.json + MCP |
| Cursor | MCP 配置写入 `~/.cursor/mcp.json` |
| Windsurf | 输出 MCP 配置供粘贴 |

Claude Code 用户也可以用 plugin 方式安装：

```bash
claude plugin add radiomind
```

如果已安装 [RadioHeader](https://github.com/ZaptainZ/radioheader)，RadioMind 会检测到并跳过 RadioHeader 已处理的 hook。

### 推荐：让你的 AI 助手来安装

复制以下提示词，发给你的 AI 助手（Claude Code、Cursor、Windsurf、Codex 等）：

```text
帮我安装 RadioMind 持久记忆模块：
1. 安装（选适合的方式）：
   - uv pip install radiomind
   - pip install radiomind
   - 如果 pip 报 "externally-managed"：python3 -m venv ~/.radiomind-env && ~/.radiomind-env/bin/pip install radiomind，并添加到 PATH
2. 激活：radiomind setup
3. 验证：radiomind status
RadioMind 自动从环境变量或本地 Ollama 检测 LLM，不需要配置文件。
```

### 手动安装

```bash
uv pip install radiomind             # 最快
pip install radiomind                # 标准（venv/conda）
pipx install radiomind               # 仅 CLI，自动隔离
```

```bash
# 可选扩展
pip install 'radiomind[server]'      # REST API (FastAPI)
pip install 'radiomind[train]'       # LoRA 微调 (Apple Silicon MLX)
pip install 'radiomind[embedding]'   # 向量搜索 (ONNX MiniLM)
```

## 使用

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

**兼容任何 LLM——零配置：**

```python
# 传入你现有的客户端 — RadioMind 自动识别类型
mind = radiomind.connect(llm=openai_client)
mind = radiomind.connect(llm=anthropic_client)

# 或者环境变量里有 API key — RadioMind 自动找到
# 支持: OpenAI, Anthropic, DashScope, DeepSeek, Groq, Together,
#       Moonshot, 智谱, 硅基流动, Mistral, Fireworks, Ollama
```

## 接入你的技术栈

| 方式 | 设置 | 适用场景 |
|------|------|---------|
| **自动** | `radiomind setup` | Claude Code、Codex、Cursor、Windsurf — 自动检测平台 |
| **Plugin** | `claude plugin add radiomind` | Claude Code — hooks + MCP 一步到位 |
| **Python** | `radiomind.connect()` | 任何 Python Agent、LangChain、自定义 |
| **MCP** | `radiomind mcp-server` | 任何 MCP 兼容工具 |
| **REST** | `radiomind serve --port 8730` | 任何语言、远程调用 |
| **CLI** | `radiomind search "query"` | 脚本、定时任务、自动化 |

9 个 MCP 工具，6 个 REST 端点，20+ CLI 命令。详见[集成指南](docs/integration.md)。

---

## 研究基础

RadioMind 的设计源自经过验证的神经科学和 AI 研究：

**互补学习系统** (McClelland, McNaughton & O'Reilly, 1995) — 大脑使用两套系统：海马体负责快速、具体的学习，新皮层负责慢速、泛化的知识。RadioMind 用 L2（快速金字塔存储）和 L3（慢速习惯巩固）来模拟这个过程。

**突触稳态假说** (Tononi & Cirelli, 2006) — 睡眠期间，大脑全局缩小突触连接，保留强连接、修剪弱连接。RadioMind 的"做梦"炼化做同样的事：衰减不用的记忆，合并冗余的，归档过时的。

**超维计算** (Kanerva, 2009) — 大脑的信息表示是极高维且分布式的。HDC 使用 10,000-bit 双极向量，其中绑定=关联、捆绑=叠加。RadioMind 用这种方式编码习惯——一个固定大小的向量存储无限数量的模式。

**多 Agent 辩论** (ICLR 2025, DMAD) — 使用不同基础模型的异构多 Agent 辩论优于单 Agent 和同构团队。RadioMind 的三体辩论应用了这一原理：三个目标冲突的 Agent（一致性、新颖性、简洁性）产出的洞察比任何单一视角都更稳健。

**LoRA** (Hu et al., 2021) — 低秩适应通过添加小型可训练矩阵实现高效模型微调。RadioMind 用它把习惯"烘焙"进模型权重——将依赖检索的知识转化为参数化知识（模型直接知道，不需要查找）。

**NeuroDream** (2026) — 在训练中引入显式的"做梦阶段"——模型断开输入，重播存储的表征——使遗忘减少 38%，零样本迁移提高 17.6%。RadioMind 的做梦炼化遵循相同原理。

**信息素模型** (Grassé, 1959) — 蚂蚁通过留下随时间衰减的信息素轨迹来协调行为，无需直接交流。常走的路径越来越强，废弃的路径自然消退。RadioMind 的社区知识评分使用相同模型：条目因使用而增强，因时间而自然衰减，不需要人工管理。

---

## Radio 生态

RadioMind 是为"AI Agent 持续学习成长"设计的工具家族的一部分：

| 项目 | 做什么 | 和 RadioMind 的关系 | 阶段 |
|------|--------|-------------------|------|
| **[RadioHeader](https://github.com/ZaptainZ/radioheader)** | 编程 Agent 的跨项目经验框架。在一个项目中调试的经验自动应用到另一个项目。 | 使用 RadioMind 作为记忆后端。RadioHeader 负责规则和行为契约（"写代码前先搜经验"），RadioMind 负责存储、检索和习惯提炼。 | 已发布，100+ 条经验 |
| **RadioMind** | 仿生记忆核心。存储、搜索、将记忆提炼为习惯。可独立使用或接入任何 Agent。 | 本仓库。整个生态的"大脑"。 | 已发布 |
| **RadioHand** | 个人 Agent 框架。多通道（Telegram、微信、Web），任务规划，工具调度。 | 将使用 RadioMind 作为默认记忆模块。RadioHand 负责执行（"手"），RadioMind 负责记忆（"脑"）。 | 规划中 |

```
RadioHeader（规则与经验）→ RadioMind（记忆与习惯）→ RadioHand（执行与通道）
         头                        脑                        手
```

## 许可

MIT
