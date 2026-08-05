# 2026-08-05 落地第 3 步：micpro 工具化 + 全链路闭环跑通

> 方案：HackWare `projectBasicInfo/lifelog-identity-design.md`。工具代码在 HackWare `micpro-audio/`，
> RadioMind 侧本次新增 `speakers export` / `set-wearer`。

## 做了什么

**micpro 变成无状态工具**（`micpro.py` + `src/diarize.py`）：
- `manual` 自描述 + 健康自报（分工/coverage/health/recommended_actions，纯本地不触网）
- `preprocess` 录音 → turns（向量 base64、绝对时间戳、`snr_db`、region）
- `observe` turns → 观察文本（带 `--dry-run`，因为它会把音频送云端）

**依赖上的收获**：整条路走 sherpa-onnx / ONNX Runtime，**不再需要 PyTorch** ——
目标机 RK3576 上 `import torch` 直接 SIGILL，这条路本来就走不通。

**RadioMind 侧补齐闭环**：`speakers export`（导出质心给工具，只给质心不给身份）
和 `speakers set-wearer`。

## 全链路实测（真实 30 分钟录音，未上传任何音频）

`audio_260804_192530`（19:25–19:55）→ preprocess → 291 turns / 359KB →
`speakers put-turns --payload-file` → **系统自己长出 3 个身份**：

| 身份 | turns | 语音 | 与标定注册向量的余弦 |
|---|---|---|---|
| spk_002 | 148 | 707s | **0.874 ← 就是佩戴者本人** |
| spk_001 | 37 | 134s | 0.428 |
| spk_003 | 23 | 72s | 0.186 |

**它独立地把 owner 认了出来**——注册向量完全没参与入库判定，是事后比对才发现最大的那个簇就是本人。
三人均为 pending（只出现 1 天），符合"跨 ≥2 天才晋升"的设计。

`manual` 的 `calibrated` 现在按**完整模型指纹**判定：真实库（campplus@f682b514）报 `true`，
旧的 eres2net 库报 `false`。阈值绑定的是具体权重，不是模型名——换权重就是换了量具。

## ★最值得记的坑：摘要全绿、功能已死

第一版 `preprocess` 把 region 写成"与佩戴者相似→conversation，否则→media"。真实录音跑出来
**指标非常漂亮**：291 turn、149 段绑定、干净地只长出一个身份、零告警。

但 **103 段同伴语音被归进 media 丢弃**——女朋友和朋友的声音永远进不了声纹库，于是
"认出反复出现的人"和"主动问这是谁"**永远不会触发**。核心功能已经死了，而所有可见指标都正常。

改成时间区域后（以佩戴者说话为锚 ±30s，区内所有人都算对话）：289 conversation / 2 media，
**3 个身份浮现**。判准：★**"不是佩戴者" ≠ "不是生活"**★；凡是按"像不像某人"给整段打标签的地方，
都要回头问它是不是把同伴一起筛掉了。

## 待办
- `observe` 只做了 `--dry-run` 验证（真跑会把第三方语音送 DashScope，需先取得授权）。
- 对话区膨胀 30s 在"整段都在聊天"的文件上会吞掉几乎全部（289/291），需要在安静时段的文件上复核。
- 非佩戴者之间的阈值仍未标定；spk_001（cos 0.428，落在灰区）可能是佩戴者在别的声学条件下被拆开，
  也可能真是另一个人——等跨天数据积累后由 merge 提议或 owner 确认。
