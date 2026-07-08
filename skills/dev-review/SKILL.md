---
name: dev-review
description: Get an independent, fingerprinted review of a plan document or a code change from a fresh reviewer subagent, with the verdict and evidence recorded so it cannot be silently reused after the reviewed files change. Use when you want a second opinion on a design/plan or a diff without running the full development loop. Do NOT use as a substitute for the full loop's mandatory reviews when a loop is running (use its own record-review), and do NOT let the author and reviewer be the same reasoning pass.
---

# dev-review — 独立评审（可组合子 skill）

`codex-dev-loop` 家族的独立子 skill：请一个**独立的** reviewer subagent 审一份方案或一段 diff，结论绑定被审文件的指纹——被审文件一改，旧评审自动失效，不能被静默复用。

约定：`<core>` = codex-dev-loop 主 skill 目录下的 `scripts/dev_loop_harness.py`。

## 何时用 / 何时不用

- **用**：想对一份设计/计划、或一段改动拿一个独立的第二意见，但不需要跑完整 loop。
- **不用**：完整 loop 正在跑时，别用它替代 loop 强制的评审（用 loop 自己的 `record-review`）；绝不让「作者」和「评审者」是同一个推理过程——必须新开一个 subagent。

## 角色

复用主 skill `references/subagent-review-loop.md` 的三个角色提示词，按需选一个：

- `plan-reviewer`：审方案/计划（技术设计、测试计划、风险）。
- `implementation-reviewer`：审 diff 是否实现了目标、测试是否覆盖。
- `risk-reviewer`：独立找架构/安全/数据/迁移/外部服务风险。

## 流程

1. **取目标指纹**：列出被审的工作区文件（计划文档，或本次改动涉及的源文件）：

```bash
python <core> standalone-fingerprint --target <file1,file2,...>
```

得到 `TARGET_FINGERPRINT=<hash>`。

2. **开独立 subagent**：用对应角色的提示词，只给它原始材料（被审文件、diff、测试证据），**不要给你的结论或期望**。要求报告顶部回显：

```text
Agent ID: <subagent 的 id>
Target Fingerprint: <上一步的 hash>

Decision: pass | needs-revision | needs-human-review | block
<角色要求的各章节>
```

3. **记录评审**（harness 校验章节完整、Agent ID 一致、Target Fingerprint 与当前文件匹配）：

```bash
python <core> standalone-review --role <role> --agent-id <id> --report <report.md> --target <file1,file2,...>
```

`pass` 返回 0；其它决策返回非 0 并留档。被审文件改动后必须重取指纹、重审。证据落在 `<evidence_dir>/review/`（默认 `.codex/evidence/review/`）。

## 独立性要求

- reviewer 必须是与作者不同的 subagent；同一会话里「自己审自己」等于没审。
- `--agent-id` 用 subagent 的真实会话 id（≥ 12 字符），作为 provenance。

## 升链

evaluator 给出 `block` 或发现范围外风险时，停下交用户决策；若牵出的问题需要成体系地改，建议升级到完整 `codex-dev-loop`。
