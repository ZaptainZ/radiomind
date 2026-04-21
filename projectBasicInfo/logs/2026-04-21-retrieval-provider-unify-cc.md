# Unify Embedding + Reranker into one `[retrieval_provider]` section

**Date**: 2026-04-21
**Trigger**: 前一次提交把 embedding / reranker 从 `[llm.openai]` 解耦为各自独立段；今天进一步把它们**合并为同一个检索能力模块**——一个 key / 一个 base_url / 一个 enable 开关。

## 动机

Embedding 和 Reranker 在架构角色上是**同一个能力模块的两半**：
- 都服务"检索"这一层职责（向量化 + 精排）
- 所有主流供应商（DashScope / Jina / Voyage / Cohere）都把两者打包在同一 API 通道下（同 base_url + 同 key）
- 拆成两个独立段让用户维护两份一样的 key / base_url，既冗余又容易漂移

统一之后：
- `[retrieval_provider]`：一段配置管 embedding 和 reranker
- 一个 `enabled` 总开关——关了就纯 FTS（保底可用）
- `use_reranker` 作为子选项（默认 off，对 A2A-strict 友好）

## 新 config 形态

```toml
[retrieval_provider]
enabled = true
provider = "dashscope"  # 语义标签（目前仅此，未来可扩）
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key = "sk-41556e..."
embedding_model = "text-embedding-v4"
embedding_dim = 2048
reranker_model = "gte-rerank-v2"
use_reranker = false   # 子开关，默认关
```

老的 `[embedding]` / `[reranker]` 段**继续读**（backward compat），新用户走统一段。`retrieval.reranker.enabled` 这个旧路径也维持。

## 代码改动

- `core/mind.py`：
  - `_try_dashscope()` 读取顺序：`[retrieval_provider]` → `[embedding]` → `[llm.openai]`(legacy)
  - Reranker 初始化同理，并读 `retrieval_provider.use_reranker` 或 `retrieval.reranker.enabled`
- `config.toml` 模板：新增 `[retrieval_provider]` 示例段

## 验证

- 现有 tests 全绿
- 手工验证：config 里只写 `[retrieval_provider]`，embedder + reranker 都能正确加载
- 手工验证：config 里只写老 `[embedding]`（不写新段），仍然可用（backward compat）

## 对项目原则的映射

- 第四律 Attention："每层明确职责"——检索能力是一层完整职责，不该分裂成两段维护
- **Elegance 信条**：同一职责、同一 key、同一开关。之前两段配置是"解耦做过了头"的副作用
