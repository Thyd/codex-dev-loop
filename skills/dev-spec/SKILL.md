---
name: dev-spec
description: Manage a repository's living specification baseline under specs/ — bootstrap an initial baseline by reverse-engineering existing code, author a spec delta for a change, or merge and mechanically validate a delta into the baseline. Use when introducing spec-driven docs to an existing (brownfield) repo, or when a change needs its requirement-level updates consolidated into specs/. Do NOT use for code that has no requirement-level impact, or when a full codex-dev-loop is running (its record-spec-merge handles the merge).
---

# dev-spec — 规格基线管理（可组合子 skill）

`codex-dev-loop` 家族的独立子 skill：维护仓库的活规格基线 `specs/`。三个动作——**bootstrap（反推初始基线）**、写 delta、合并校验。

约定：`<core-dir>` = codex-dev-loop 主 skill 目录；`<core>` = `<core-dir>/scripts/dev_loop_harness.py`。基线格式与 delta 格式见 `<core-dir>/references/spec-baseline.md`。

开始前运行 `python <core> version --require 0.7.0`；版本不足或核心缺失时停止并更新主 skill。

## 何时用 / 何时不用

- **用**：老仓库首次引入规格管理（bootstrap）；某次改动需要把需求级更新沉淀进 `specs/`。
- **不用**：改动无需求级影响；完整 `codex-dev-loop` 正在跑（它的 `record-spec-merge` 负责合并）。

## 动作 A：bootstrap（老仓库反推初始基线）

**每仓一次性**操作。原则：**扫描 → 提议 → 用户在「地图层」确认 → 落盘**。粗粒度优先、幂等增量、草稿显式标记。

1. **扫描**：默认尊重 `.gitignore`，扫源码目录，跳过 tests/vendor/build/node_modules。用户可指定收窄路径。
2. **提议能力地图**：产出一张「模块/目录 → capability（kebab-case）→ 草稿 requirement 列表」的地图，**先给用户整体审阅**。默认每个顶层模块一个 capability，每个公共入口/行为一条 `#### Requirement:`。不要逐条盘问——在地图层批量确认。
3. **用户确认后落盘**：为每个 capability 写 `specs/<capability>.md`，首行 `# <capability> Specification`；反推的 requirement 打草稿标记：

   ```markdown
   #### Requirement: <title>

   <!-- draft: reverse-engineered, unreviewed -->
   <行为描述，SHALL/MUST 表述绑定部分>

   - Acceptance: <如何验证>
   ```

4. **幂等**：已存在的 `specs/<capability>.md` 只补缺口，不覆盖。
5. 草稿标记提示后续 loop：这些 requirement 未过正常评审门，可在首次正式变更时补审。

## 动作 B：写 delta（某次改动的需求级变更）

在 `spec-delta.md` 里按 capability 声明 ADDED/MODIFIED/REMOVED 的 `#### Requirement:`，或在 `## No Spec Impact` 下写明无影响理由（二者恰选其一）。格式见 spec-baseline.md。

## 动作 C：合并并校验

1. 把 delta 应用到 `specs/<capability>.md`（新增/替换/删除对应 requirement 块）。
2. 机械校验（每个 ADDED/MODIFIED requirement 正文与基线一致、无重复标题、每个 REMOVED 标题已消失）：

```bash
python <core> check-spec-delta --delta spec-delta.md --spec-dir specs
```

`No Spec Impact` 的 delta 直接通过、无需改基线。

## 与其它 skill 的衔接

- bootstrap 完成后，仓库就具备了 `specs/` 基线，后续任何改动都能用动作 B/C 保持同步。
- 在完整 `codex-dev-loop` 里不用本 skill：loop 的 `record-spec-merge` 会做同样的校验并绑定 loop 指纹。
- standalone 短链要发 PR 时，`dev-ship` 会把 `specs/` 的改动随代码一起提交进同一个 PR。
