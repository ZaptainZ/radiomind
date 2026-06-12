# LLMRouter-1a — LLM 解析层审计 + 最小修复设计（只读，零代码）

> 作者: Claude Code (cc) ｜ 日期: 2026-06-13
> 前置: LoRAFuel-1b smoke 排障暴露 CLI 炼化静默 0 产出。用户裁决: 基础设施债优先于
> 继续 LoRA;先只读 audit + 输出最小修复方案;不改 LoRA;修完回头跑 CLI train smoke。

## 1. "CLI 炼化 0 产出"完整因果链（完成标准 ①）

解析链 `mind._resolve_llm`（mind.py:2492）: 宿主注入 → 环境变量 → 本地 Ollama → config.toml → 纯记忆。

| 层 | 实测行为 | 判定 |
|---|---|---|
| P1 宿主注入 | CLI `_get_mind()` 不注入 → 跳过 | 按设计 |
| P2 环境变量 | `ENV_PROVIDERS` 11 家,本 shell 无任何 *_API_KEY → 跳过 | 按设计 |
| P3 本地 Ollama | `llm_auto._from_ollama` **已有空模型检查**（2026-04-19 修过,docstring 在档）→ 空 ollama 正确返回 None | 按设计（昨日嫌疑洗清） |
| **P4 config router** | `LLMRouter._init_backends`（llm.py:200-214）**只硬编码读 `llm.ollama` 与 `llm.openai` 两段** → `[llm.dashscope]/[llm.openrouter]/[llm.openai_direct]` 从未构建 | **缺陷 A（根因）** |
| P4 续 | `generate()`: `default_backend="dashscope"` 在 `_backends` 查无 → `_find_available()` **静默**取 dict 序第一个"可用"后端,零警告 | **缺陷 C** |
| P4 续 | config 版 `OllamaBackend.is_available` 只 ping `/api/tags`,**不查模型**（与 llm_auto 的 P3 探活双标）→ 实验残留的空 ollama 被当可用,全调用 404 | **缺陷 B** |
| P4 续 | `OpenAICompatBackend.is_available = bool(base_url and api_key)`——配置了 ≡ 可用,无活性概念 → 杀掉 ollama 后兜底到 4 月起 403 的 TokenPlan 死端点 | 缺陷 C 的放大器 |

> 404→403 的演进与实测完全吻合: daemon 在 → config-ollama 兜底(无模型 404);
> daemon 杀 → openai 兜底(死端点 403)。两层缺陷叠加,任何依赖自解析的功能
> （dream/refinement/train/doctor/CLI）在独立模式下全部静默废掉。

**bench 为何绕过**: ①历史上 router 曾解析成空（April 笔记在档）;②bench 需要同进程
多 provider 并行（answer=dashscope / judge=openrouter / internal 第三配置）+ 逐调用
model/max_tokens/retry 控制,router 的 cost-tier 模型解析（`llm.models.economy` 等）
会覆盖意图。绕过是症状,根因即缺陷 A。

## 2. 最小修复设计（完成标准 ②,不破坏现有 ollama/openai）

**Fix A — 通用 OpenAI-compatible profile 构建**（核心,~15 行）
`_init_backends` 保留现有两段构建**原样不动**,其后追加:
```python
for name, sec in (self.config.get("llm", {}) or {}).items():
    if name in ("ollama", "openai", "models", "default_backend"): continue
    if isinstance(sec, dict) and sec.get("base_url") and sec.get("api_key"):
        self._backends[name] = OpenAICompatBackend(
            base_url=sec["base_url"], api_key=sec["api_key"],
            default_model=sec.get("model", ""))
```
→ `default_backend = "dashscope"` 直接命中;openrouter/openai_direct 同享。
注: cost-tier 映射（economy=qwen-turbo/standard=qwen-plus/deep=qwen-max）恰好是
DashScope 真实模型名,与 Fix A 兼容;设计文档注明"tier 模型名须存在于所选 provider"。

**Fix B — OllamaBackend.is_available 查模型**（~6 行）
对齐 llm_auto 的 P3 探活: `/api/tags` 200 **且** `models` 非空才算可用。
行为变化仅一种: 空 ollama 不再被 config router 当可用——正是想要的。

**Fix C — 兜底不再静默**（~5 行）
`generate()` 中 requested/default 后端缺失或不可用而改用兜底时,
`logging.warning("llm backend '%s' unavailable; falling back to '%s'", ...)`
（每 router 实例一次,防刷屏）。全部不可用时维持现有 RuntimeError（已是 fail-fast）。
死端点若是 default 本身,调用会抛 HTTP 错误向上传播——天然 fail-fast,不吞。

**Fix D — 用户配置建议**（非代码,user action）
live `~/.radiomind/config.toml`: `default_backend = "openai"` → `"dashscope"`;
`[llm.openai]`（TokenPlan,403 since April）加 `# DEPRECATED: dead endpoint` 注释或移除。

## 3. 测试方案（完成标准 ③,全确定性,mock urlopen）
1. config 含 `[llm.dashscope]` → `_backends` 出现 "dashscope",`generate(backend="dashscope")`
   路由到它（mock 断言 URL）;
2. `[llm.openrouter]` 同理;`[llm.models]`/`default_backend` 键不被误构建;
3. 既有 ollama/openai 构建行为逐字段回归（防破坏）;
4. `OllamaBackend.is_available`: `/api/tags → {"models": []}` = False;有模型 = True;
   连不上 = False;
5. fallback 警告: default=不存在的后端 → caplog 捕获 warning 且只发一次;default 在场
   → 零警告;
6. 全不可用 → RuntimeError（现行为锁定）。
归 pack 类目 `core:llm-router`。修完后回头跑 LoRAFuel CLI train smoke（同一副本 home,
期望与宿主模式同样 0→5）。

## 4. 不做 / 守住
不动解析链优先级（宿主→env→ollama→config 顺序不变）。不给 OpenAICompatBackend 加
活性 ping（成本/超时复杂度,fail-fast 已由异常传播保证）。不改 bench 的 llm_call
（多 provider 并行需求仍在;router 修好后 bench 迁移与否另议）。不动 LoRA。
