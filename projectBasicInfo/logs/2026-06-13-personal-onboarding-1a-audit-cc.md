# PersonalOnboarding-1a — 个人 Agent 初始化流程审计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: RadioHeaderMind-1a（公开三入口定位已上线）+ 04 §2。
> 范围: 只读盘点 Hermes/OpenClaw/RadioHand 接入 RadioMind 的初始化产品化。零代码、
> 不设计订阅、不动 RadioHeader repo、不要求普通用户给 API key。

## Q1. 宿主 Agent 能/不能提供哪些能力（按现有接入面实测）
| 能力 | 现状 | 复用通道 |
|---|---|---|
| **LLM 调用** | ✅ 已支持 | `RadioMind(llm=fn)` / `connect(llm=)` / Hermes `initialize(..., llm=)`,callable `(prompt,system)->str`,解析链 Priority 1。**这是宿主 LLM 复用的唯一且已通的通道。** |
| 文件/历史记忆访问 | ⚠️ 部分 | Hermes `on_memory_write(action,target,content)` 把宿主内建记忆**镜像**进 RadioMind;但**无"发现并批量导入旧记忆"**入口（只有逐条 learn/ingest）。 |
| 用户授权弹窗/确认 | ❌ 无契约 | 宿主可能有,但 RadioMind 侧**无任何 capability 标志或授权回调**;provider 直接执行副作用。 |
| 长期后台任务/hook | ⚠️ 隐式 | Hermes `sync_turn`（每轮异步 ingest + 每 10 轮 trigger_chat）、`on_session_end`（auto_dream 默认 True）——**已在后台跑,但无宿主能力声明、无用户开关粒度**。 |
| embedding/vector | ⚠️ 自检 | config 有 dashscope key 时 DashScopeEmbedder 自动激活;无则 FTS。宿主**无法声明**自己能否提供检索能力。 |

## Q2. RadioMind 现有入口哪些适合宿主调用
- **适合宿主**: Hermes provider 生命周期（initialize/get_tool_schemas/handle_tool_call/
  system_prompt_block/prefetch/sync_turn/on_session_end/on_memory_write/shutdown）——
  已是较完整的宿主契约;MCP 18 tools（search/ingest/learn/digest/dream/refine_step/
  push_habits/delete_memory/delete_scope/memory_history…）。
- **仅硬核**: CLI（init/doctor/train/deploy/setup）、Python 全量 RadioMind API。
- **缺口**: Hermes provider 的 tool 集只有 4 个（search/learn/habits/status）,**比 MCP 的 18
  个窄**——个人 Agent 经 provider 拿不到 ingest/digest/delete/history;且 provider 无
  readiness/capability 协商方法。

## Q3. 首次安装后的理想 onboarding 流程（蓝图）
```
宿主选用 RadioMind 为 memory provider
  ↓ ① 宿主能力检测（缺口: 无契约,见 Q5）
HostCapabilities{can_provide_llm, can_prompt_user, can_import_memory,
                 can_write_config, supports_background_hooks, has_retrieval}
  ↓ ② 请求导入授权（缺口: 无发现/导入流程）
"发现 Hermes/OpenClaw 旧记忆 N 条,导入?" → 用户同意 → 格式化导入文本 → ingest
  ↓ ③ 配置最大可用能力
LLM: 宿主 llm 优先（不问普通用户 key）;检索: 本地/宿主优先,托管延后;
后台炼化/做梦: 默认 OFF,需用户显式开（当前默认 ON,见 Q4 缺口）
  ↓ ④ readiness report（缺口: 无此函数）
base memory / search 模式 / LLM 来源 / dream / LoRA(opt-in|blocked+原因)
```

## Q4. 必须询问用户授权的步骤 vs 当前实际
| 副作用 | 应授权 | 当前实际 |
|---|---|---|
| 读旧记忆/聊天历史/项目文件 | ✅ | 无导入流程（中性,但 1b 要加时须带授权） |
| 写长期记忆 | ✅ | **`sync_turn` 每轮自动 ingest,无 per-user 授权**（仅靠"启用 provider"隐含同意） |
| 调外部 LLM | ✅ | 宿主注入则用宿主;config 有 key 则自动用 dashscope——**自动,无确认** |
| 后台自动炼化 | ✅ | **`sync_turn` 每 10 轮自动 trigger_chat,无开关粒度** |
| 后台做梦/训练/上传 | ✅ | **`on_session_end` auto_dream 默认 True**;train/deploy 仅 CLI（opt-in,OK） |
→ **关键缺口: provider 的 sync_turn/on_session_end 把"写记忆 + 炼化 + 做梦"当默认行为,
与 04 §1.4"所有副作用需宿主代请求授权"相悖。** 需要 capability/authz gate。

## Q5. 缺口清单（按类型）
- **宿主能力契约缺口（最关键）**: 无 `HostCapabilities` 数据结构;`initialize(**kwargs)` 只取
  `llm`/`hermes_home`,无 can_prompt_user/can_import_memory/supports_background_hooks/
  has_retrieval。→ **PersonalOnboarding-1b 应先做这个**。
- **API 缺口**: 无 readiness-report 纯函数;无"发现+导入旧记忆"入口;provider 无 authz 回调
  （宿主无法在副作用前插入用户确认）。
- **MCP 缺口**: 较小——MCP tool 集比 provider 全;但 MCP 也无 capability/authz 协商。
- **文档缺口**: 04 已定方向,但个人 Agent 的"装完后宿主该调哪几个方法初始化"无 how-to。
- **future RadioHand 需提供**: 标准的 can_prompt_user（授权弹窗）+ can_import_memory
  （历史发现）+ 后台任务调度——这些是宿主侧能力,RadioMind 只需定义契约去消费。

## 结论与 1b 起点
**个人 Agent 初始化蓝图 = 能力检测 → 授权导入 → 宿主优先配置 → readiness 报告;
RadioMind 侧已有 LLM 注入 + provider 生命周期两块地基,缺的是"宿主能力契约 + 授权 gate +
readiness 报告"三件，且现有 provider 的后台副作用默认开、违反授权原则。**

**PersonalOnboarding-1b 先做**: 把 `HostCapabilities` 写成具体接口草案（04 §2.2 1b 的字段
+ 本审计 Q1 补的 has_retrieval），并定义 provider 如何用它**门控** sync_turn 写入 /
on_session_end 做梦 / 自动炼化（默认保守 = 未授权则不跑后台副作用）。仍只写接口草案 +
设计 log,不实现、不动订阅、不动 RadioHeader repo。

## 不做 / 守住
零代码。未设计订阅/向量托管。未改 RadioHeader repo。未要求普通用户 API key。
关键定位变化（provider 后台副作用 vs 授权原则）已在本 log 标注,overview 同步一行。
