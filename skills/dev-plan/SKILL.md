---
name: dev-plan
description: Produce the planning artifacts for a change — technical design, test plan, risk analysis, spec delta, and a development plan split into testable units — without writing code, so a design can be agreed (and optionally reviewed) before implementation. Use when the user wants a plan/design only, or as the planning step before implementation. Do NOT use for trivial one-line changes (just do them under dev-tdd), or when a full codex-dev-loop is already running (its planning phase covers this).
---

# dev-plan — 规划五件套（可组合子 skill）

`codex-dev-loop` 家族的独立子 skill：只产出规划产物，不写代码。适合「先要方案，后决定是否实现」。

约定：`<core-dir>` = codex-dev-loop 主 skill 目录（Codex 默认 `~/.codex/skills/codex-dev-loop`）。

开始前运行 `python <core-dir>/scripts/dev_loop_harness.py version --require 0.7.1`；版本不足或核心缺失时停止并更新主 skill。

## 何时用 / 何时不用

- **用**：用户只要方案/设计；或作为实现前的规划环节（澄清之后、编码之前）。
- **不用**：一行就能改完的琐碎改动（直接 `dev-tdd`）；完整 `codex-dev-loop` 正在跑（它的 planning 阶段已覆盖）。

## 前置

需求不清先 `dev-clarify`。规划针对一份 Goal/AC 齐全的 spec 展开。

## 产物

在一个规划目录（建议 `.codex/plan/`）下产出，模板见 `<core-dir>/references/artifact-templates.md`：

- `technical-design.md` — 方案、文件范围、数据/接口变更、非目标。
- `test-plan.md` — 单元/集成/静态门/覆盖缺口。
- `risk-analysis.md` — 正确性/安全/数据迁移/架构/兼容/外部服务风险。
- `spec-delta.md` — 需求级 delta（capability 的 ADDED/MODIFIED/REMOVED，或有理由的 No Spec Impact）。格式见 `<core-dir>/references/spec-baseline.md`。
- `development-plan.md` — 拆成独立可测单元，每单元标 `- TDD: red|regression-only` 和 `- Dependencies:`。

同时建议先和用户确认**任务规模**（small/standard/large），写进设计的开头——它决定后续走微链还是完整 loop。

## 校验

```bash
python <core-dir>/scripts/validate_dev_loop_artifacts.py --root .codex/plan --profile plan-only
```

校验产物齐全、必需章节非空。（该校验器无 loop 状态时走独立模式，可直接用于本 skill。）

## 评审（可选但推荐）

要独立第二意见时，用 `dev-review --role plan-reviewer`，target 指向这些规划文件。

## 交付去向

- 只要方案：到此为止，把规划目录交给用户。
- 要接着实现：小任务 → `dev-tdd` 逐单元实现；标准/大任务 → 把这份规划作为完整 `codex-dev-loop` 的输入（loop 会重新纳入状态机与全闸门）。
