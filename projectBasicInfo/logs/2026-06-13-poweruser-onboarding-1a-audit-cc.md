# PowerUserOnboarding-1a — 硬核用户直接使用路径审计（只读）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 范围: 只读。CLI/Python/MCP 直接使用 RadioMind 的入口完整性 + 文档 gap。
> 不改代码、不跑 benchmark、不接订阅、不碰 RadioHeader repo、不扩 LoRA/provider 行为。

## 1. CLI 命令图（21 个,实测自 cli/main.py）
| 命令 | 用途 | 副作用类 | 需 LLM | 需 embed | doc |
|---|---|---|---|---|---|
| init | 建数据目录 | writes local（建 data/,不写 config） | — | — | quickstart/README |
| doctor | 健康检查 | safe read-only | — | — | quickstart（1b 改过） |
| status | 统计 | safe read-only | — | — | quickstart |
| config | 看/改配置 | writes config | — | — | quickstart（1b 加 dashscope 示例） |
| search | 检索 | safe read-only | — | 可选 | README×4 |
| ingest <file> | 入库对话 | writes local memory | 触发抽取(可无 LLM,gate 正则) | — | quickstart/integration |
| learn <text> | 入库知识 | writes local memory | — | — | api-ref |
| chat | 三体炼化 | writes local + **calls LLM** | ✅ | — | 少 |
| dream | 做梦修剪 | writes local + **calls LLM** | ✅ | — | 仅 1 doc |
| refine-step | 宿主驱动炼化单步 | writes local（宿主给 LLM 输出） | 宿主 | — | 少 |
| train（_LORA gated） | LoRA 微调 | **trains model** + writes adapter | ✅ | — | README×3/quickstart |
| deploy（_LORA gated） | fuse+GGUF+ollama | **deploys model** + 外部 ollama | — | — | 仅 1 doc |
| serve | REST server | **starts server** | 视调用 | — | README/api-ref |
| mcp-server | MCP stdio server | **starts server** | 视调用 | — | README/api-ref |
| setup / setup-restore | 装/还原宿主 hook | writes host config（备份） | — | — | README |
| embed-backfill | 回填向量 | writes local + **calls embedding** | — | ✅ | 少 |
| push-habits | 推 habit 到宿主 | writes host files | — | — | 少 |
| migrate-radioheader / rh-search / rh-consolidate | RadioHeader 桥 | mixed | — | — | integration |

副作用分级清楚: safe read-only（doctor/status/search）/ writes local（init/ingest/learn）/
calls LLM（chat/dream/refine-step）/ trains-deploys（train/deploy）/ starts server
（serve/mcp-server）/ writes host（setup/push-habits）。train/deploy 已 `_LORA_ENABLED` 门控
（opt-in,InstallUX 已确认）。

## 2. Python API 图
- **Simple（`connect()` → SimpleRadioMind）**: add / search / get / update / delete /
  delete_all / history / list / digest / refine / close / advanced。覆盖记忆 CRUD + digest +
  refine。**dream/train 不在 Simple 层**,需 `.advanced` 取全量 RadioMind（trigger_dream/
  train/...）。
- **Advanced（RadioMind）**: 全子系统。api-reference §3 有 trigger_dream/train/meta/stats。
- **Primitives**: `trinity` / `attention` 顶层导出（方法论原语,硬核可直接调）。
- **doc 对齐**: README "Use" 用 add/search/digest/refine——全部存在且签名对;api-reference
  三层（Simple 4 / Protocol / Advanced）较完整。**gap: dream/train 是 power-user 高频意图,
  但"要走 .advanced"这条路径在 README 不显眼**（只在 api-ref §3）。

## 3. MCP / server 成熟度判定
- **MCP server: 功能成熟,文档不成熟。** 实测 **17 tools**（search/ingest/learn/digest/
  status/chat/dream/refine_step/push_habits/reject_habit/get_memory/update_memory/
  delete_memory/list_memories/memory_history/delete_scope + namespace）——与 CLI/Python
  记忆操作基本对等。但 **README 说"9 MCP tools"、api-reference 说"8 tools",实际 17**——
  严重低报,硬核用户会以为 MCP 只暴露一半能力。docs 未枚举完整 tool 列表。
- **授权原则**: MCP tools **无 scope 门控**。判定: **可接受且与 PersonalOnboarding-1c 一致**——
  MCP tool call 是客户端/用户**显式发起的前台动作**（同 CLI 命令）,1c 门控的是**后台自动
  副作用**（sync_turn/on_session_end）。前台显式调用不门控是设计一致,不是违规。
  （未来若 MCP 客户端不可信场景需要细粒度授权,另起线,不在本审计。）
- **REST server**: 6 endpoints（README 数字正确）。

## 4. 文档路径审计: 新硬核用户能否走通
| 步骤 | 能否 | 备注 |
|---|---|---|
| 安装 | ✅ | InstallUX-1b 已修（uv/pip/venv + python -m） |
| 初始化 | ✅ | init / doctor |
| 配 LLM/embedding | ✅ | 1b 加了 dashscope 多 profile + env-var 头条 |
| 写第一条记忆 | ✅ | ingest / learn |
| 搜索 | ✅ | search |
| digest | ✅ | digest |
| refine/dream（可选） | ⚠️ | CLI refine/dream 有;Python 需 `.advanced`,不显眼 |
| LoRA train/deploy（可选） | ✅ | quickstart 1b 新增冷启动到 LoRA 节 |
| MCP/server 接入（可选） | ⚠️ | 命令在;但 MCP tool 列表低报（8-9 vs 17）,无完整枚举 |

## 5. Gap 分级
- **BLOCKER**: 无。命令/API/MCP 都存在且可达,安装文档 1b 已修。
- **MISLEADING**: MCP tool 数严重低报（README 9 / api-ref 8 / 实际 17）→ 硬核用户低估 MCP
  能力面,可能放弃 MCP 集成或自己造轮子。
- **MISSING**: ① 无**统一 CLI 命令参考**（21 命令散在 README/quickstart,无单页 map）;
  ② MCP **完整 tool 列表**未枚举（只列了部分）;③ Python power-user 的 dream/train **走
  `.advanced` 的路径**在 README 不显眼。
- **NICE_TO_HAVE**: `radiomind onboard` 交互式命令（04 §4.2 提及）;CLI 命令带 doctor 式
  next-step 提示（部分已在 1b 做）。

## 6. PowerUserOnboarding-1b 建议
**主要是文档 gap,不是 CLI UX 缺陷,也不需要单独 MCP 线**（MCP 功能成熟,只是低报）。
→ **1b = 纯文档**:
1. api-reference MCP 段从"8 tools"更新为**完整 17 tool 枚举**;README"9 MCP tools"改正。
2. 加**统一 CLI 命令参考**（单页表: 命令/用途/副作用类/需 LLM-embed）——复用本审计 §1 表。
3. README/quickstart 点明 Python power-user 的 dream/train 走 `mind.advanced`（或 CLI）。
**不开 MCPOnboarding 单独线**（无功能缺口）;`radiomind onboard` 留 NICE_TO_HAVE,不进 1b。

## 7. 不做 / 守住
零代码、未跑 benchmark、未接订阅、未碰 RadioHeader repo、未扩 LoRA/provider。
MCP 无 scope 门控经判定为前台动作一致行为,不在本轮改。
