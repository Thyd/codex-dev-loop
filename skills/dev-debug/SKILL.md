---
name: dev-debug
description: Debug a failing test, crash, or wrong behavior by root cause, not by symptom — reproduce reliably, isolate the cause with evidence, fix the root cause, then lock it with a regression test. Use when something is broken and the cause is not yet understood. Do NOT use to add new features (use dev-tdd), and do NOT patch a symptom without identifying the underlying cause.
---

# dev-debug — 系统化调试（可组合子 skill）

`codex-dev-loop` 家族的独立方法论子 skill（借鉴 systematic-debugging）：按根因而非症状排障。它不改状态机，收尾时用 `dev-tdd` 的红绿把修复锁进回归测试。

约定：`<core>` = codex-dev-loop 主 skill 目录下的 `scripts/dev_loop_harness.py`。

开始前运行 `python <core> version --require 0.7.1`；版本不足或核心缺失时停止并更新主 skill。

## 何时用 / 何时不用

- **用**：有测试失败/崩溃/行为错误，且**根因未明**。
- **不用**：加新功能（用 `dev-tdd`）；已经定位根因、只差写实现（直接 `dev-tdd`）。绝不「哪里报错改哪里」地打症状补丁。

## 四阶段

1. **稳定复现**：找到能可靠触发问题的最小步骤/输入。无法稳定复现之前，不要动手改代码——先缩小到确定性重现。
2. **定位根因（带证据）**：二分、日志、断点、`git bisect` 缩小范围，直到能指着一处说「就是这里，因为 X」。区分「相关」与「因果」；用证据排除假设，不靠猜。
3. **修根因**：改导致问题的那一处，而不是掩盖症状的表层。若根因牵出设计问题、或触及敏感路径（`python <core> guard-check`），停下升链——这已超出「小修」。
4. **锁定回归**：把这个 bug 变成一个先失败的测试，再让修复使其转绿——用 `dev-tdd` 的红绿闸门：

```bash
python <core> standalone-test --label <bug-id> --stage red   --command "<能复现 bug 的失败测试>"
# 应用根因修复
python <core> standalone-test --label <bug-id> --stage green  --command "<同一个测试>"
```

红证据证明这个测试确实能抓住该 bug；绿证据证明修复有效。证据落 `<evidence_dir>/tdd/`。

## 反模式（明确避免）

- 症状补丁：吞异常、加重试、调超时来「让它过去」，而不查为什么。
- 换一堆东西碰运气：一次只验证一个假设。
- 复现不了就开改：没有确定性重现，无法确认修好了。

## 升链

根因指向架构/数据/安全问题，或修复范围明显扩大 → 升级到完整 `codex-dev-loop`（standard/large），走风险评审与质量门。

## 与交付衔接

修复要发 PR 时接 `dev-ship`，并把 bug label 传给 `ship-check --label <bug-id>`，确保「修复 + 回归测试」一起进 PR。
