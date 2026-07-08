# Codex Dev Loop — 可组合化路线图（0.5.0 方向）

> 面向实现者的设计文档。目标读者是接手这项工作的 agent 或开发者。
> 阅读本文即可获得全部背景，不需要依赖任何历史对话。
> 本文描述的是 **0.4.0 之后的下一步演进**，尚未实现；实现前请先与用户确认「待定决策」一节。

---

## 0. 背景与当前状态

`codex-dev-loop` 当前（0.4.0）是一条 **单体自动开发流水线**：一个 SKILL.md 驱动一个 Python 状态机（`scripts/dev_loop_harness.py`），从需求澄清一路走到 PR。它的核心竞争力是 **harness 强制的证据链**——每个阶段闸门都要求可验证的证据（命令、日志、指纹、时间戳），没有证据不能进入下一阶段。这是它区别于 OpenSpec（无门禁）和 Superpowers（靠提示词自觉）的根本。

0.4.0 已经落地的能力（本路线图会复用这些资产）：

- **阶段状态机**：`intake → planning → plan_review → branch → implementation → implementation_review → risk_review → quality_gate → pr → cloud_checks → complete`
- **需求澄清**：`intake` 阶段 + `clarification-log.md`，Goal/AC 为空拒绝进 planning
- **TDD 红绿闸门**：`run-test --stage red|green`，无红证据拒绝记录绿
- **worktree 并行**：`record-test --worktree`、`verify-units`
- **规格基线**：`spec-delta.md` + `record-spec-merge`，合并进仓库 `specs/<capability>.md`
- **三档 scale**：`--scale small|standard|large` + `set-scale` + 敏感路径硬护栏（`sensitive_changed_paths()`）
- **内置 gate fallback**：`scripts/test_gate.py`、`scripts/quality_gate_fallback.py`
- **多助手适配**：`adapters/claude-code/SKILL.md`、`CODEX_DEV_LOOP_HOME` 环境变量
- **配置 schema v2**：`default_scale`、`spec_dir`、`test_gate_script`、`quality_gate_script`
- **证据指纹机制**：`plan_fingerprint`（核心产物哈希）、`workspace_fingerprint`（工作区文件哈希），改文件即失效下游证据

### 这次要解决的问题

借鉴 Superpowers 的 **可组合性**：Superpowers 把 TDD、systematic-debugging、worktree 等做成能独立触发的小 skill；codex-dev-loop 现在是「要么走全套流水线，要么不用」。小任务（改一个函数、修一个 bug）用不上完整 loop 时，用户无法只调用其中一段。

**目标**：把各阶段拆成可单独调用的子 skill，让小任务能只用其中一段；同时**不丢掉证据链**这个核心差异。

---

## 1. 首要设计原则（不可违背）

> **拆的是「技能（皮）」，不是「状态机（核）」。**

如果把流水线拆成 N 个各自独立的小 skill、每个自带一套逻辑，就退化成了 Superpowers 那种「靠模型自觉」的模式，等于亲手丢掉最大的差异化。因此架构必须是：

**一个共享的 harness core + N 个薄皮子 skill + 一个变薄的编排器。**

三条铁律：

1. **单一 harness**：所有子 skill 都调用同一个 `dev_loop_harness.py`，绝不各自实现闸门逻辑。
2. **单一事实源**：任一时刻，一个工作区只有一处证据记录。存在活动 loop（`loop-state.json` 存在且 `phase != complete`）时，子 skill 必须以 loop 模式接入状态机，禁止 standalone，防止证据分叉。
3. **证据底线**：即使是最小的独立调用，也必须留下与 loop 内一致格式的证据（命令、日志、指纹、时间戳）。可组合 ≠ 裸奔。

---

## 2. 目标架构

```
┌─────────────────────────────────────────────────────────┐
│  harness core: scripts/dev_loop_harness.py               │
│  （状态机 + 闸门 + 指纹 + 证据格式；唯一事实源）          │
│  + 内置 fallback: test_gate.py / quality_gate_fallback.py│
└─────────────────────────────────────────────────────────┘
      ▲            ▲            ▲            ▲
      │ 调用同一 core（loop 模式 或 standalone 模式）
      │            │            │            │
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  … 薄皮子 skill
│ dev-tdd  │ │dev-review│ │dev-spec  │ │ dev-ship │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
      ▲
      │ 完整流程时被编排
┌─────────────────────────────────────────────────────────┐
│  codex-dev-loop（编排器）：SKILL.md                       │
│  各阶段改为「调用 $dev-xxx（loop 模式）」；状态机不变     │
└─────────────────────────────────────────────────────────┘
```

**两种运行模式**（由 harness 自动判定，子 skill 不需要关心）：

| 模式 | 触发条件 | 证据写到 | 闸门 |
|---|---|---|---|
| **loop 模式** | 存在活动 `loop-state.json` | `.codex/dev-loop/`（现状） | 全阶段门 |
| **standalone 模式** | 无 loop 状态 | 证据目录（默认 `.codex/evidence/<skill>/`，可按宿主配置，见 4.1） | 只有该技能自身的证据要求（无跨阶段门） |

**分发方式**：monorepo。子 skill 是只含 `SKILL.md`（必要时加一两个 reference）的薄目录，脚本统一引用 `<loop-home>/skills/codex-dev-loop/scripts/`（延续现有伴随 skill 的路径约定）。新增 `scripts/install_skills.py` 把各薄目录复制/软链到 skills 目录。

---

## 3. 子 skill 清单

命名统一用 `dev-` 前缀（**待用户确认，见第 7 节**）。

| Skill | 独立触发场景 | 复用的现有资产 | 需要新增 |
|---|---|---|---|
| **dev-clarify** 需求澄清 | 「我有个想法」→ 产出 Goal/AC/约束齐全的 spec 文档，可喂给任何后续链 | intake 阶段指令、`clarification-log.md` 模板 | harness `check-spec --file` standalone 校验命令 |
| **dev-plan** 规划五件套 | 只要方案不要代码（把现在的 `planning_only` 抽出）；产出设计/测试计划/风险/spec-delta/开发计划 + scale 建议 | artifact-templates.md、`validate_dev_loop_artifacts.py` | 无（纯指令皮，standalone 走 dev-review 校验） |
| **dev-review** 独立评审 | 对标 Superpowers `requesting-code-review`：「用独立 reviewer 审这个方案 / 这个 diff」，报告带指纹 | subagent-review-loop.md 三角色提示词、`record-review` | standalone 评审记录（指纹绑定被评审文件而非 loop） |
| **dev-tdd** 单元 TDD | 对标 `test-driven-development`：「用 TDD 修这个 bug」——红→绿→重构，证据留档 | `test_gate.py`（已可独立跑）、红绿闸门逻辑 | run-test 红绿逻辑支持 standalone（证据写 `.codex/evidence/tdd/`） |
| **dev-parallel** worktree 并行 | 对标 `using-git-worktrees` + `subagent-driven-development`：多个独立小任务并行开发 | tdd-parallel-units.md、`record-test`/`verify-units`、unit-implementer 提示词 | 依赖 dev-tdd；standalone 编排指令 |
| **dev-spec** 规格基线 | 三动作：**bootstrap（老仓库从代码反推初始 `specs/` 基线——全新能力，补 brownfield 缺口）**、delta 撰写、merge 校验 | spec-baseline.md、`record-spec-merge` | bootstrap 指令 + merge 的 standalone 模式 |
| **dev-ship** 交付 PR | 任何本地改动 → 规范化 branch→commit→push→PR→盯 CI，证据齐全 | git-pr-flow.md、github-actions-cloud.md、`record-branch/commit/pr/cloud` | standalone 模式（保护分支规则照旧生效） |

已有的两个伴随 skill 保持不动：

- **automated-dev-executor**：测试闸门执行器（内置 `test_gate.py` 兜底）
- **ai-code-quality-gate**：质量门（内置 `quality_gate_fallback.py` 兜底）

**编排器 codex-dev-loop 本体**：SKILL.md 各阶段改为「调用 `$dev-xxx`（loop 模式）」，harness 状态机原封不动。scale 决定哪些子 skill 进链（small 跳 risk 角色，已实现）。

---

## 4. harness core 需要的改动（工程量主要在这里）

按依赖顺序：

1. **standalone 证据模式**
   - 命令检测不到 `loop-state.json` 时，证据写入证据目录（见下方「证据目录解析」），格式与 loop 内**完全一致**（命令、日志路径、指纹、时间戳）。
   - 指纹在 standalone 下绑定「被操作的具体文件」（如被评审的 spec、被测的单元），而非 loop 计划产物。
   - **证据目录解析**（决策 3）：新增 config 键 `evidence_dir`。解析顺序：① config 显式配置的 `evidence_dir` → ② 自动识别宿主：`CODEX_DEV_LOOP_HOME` 未设置（即 Codex，默认 `~/.codex`）→ 用默认 `.codex/evidence/<skill>/`；已设置（如 Claude Code 指向 `~/.claude`）→ agent 在首次 standalone 调用时选择工作区内的证据目录（默认建议 `.dev-loop/evidence/`，可询问用户），并写回 config 固化。核心不变量：证据目录必须是**工作区相对路径**、随仓库可见、且一个工作区只有一个。

2. **单一事实源守卫**
   - 检测到活动 loop（`loop-state.json` 存在且 `phase != complete`）时，子 skill 的 standalone 入口必须拒绝，提示「检测到进行中的 loop，请以 loop 模式操作」。防止证据分叉。

3. **`guard-check` 命令**
   - 把现有的 `sensitive_changed_paths()` 暴露成 CLI subcommand，输出命中的敏感路径列表。供路由预检和微链 tripwire 复用。**这个函数已经写好，只差一个 subcommand 包装。**

4. **`adopt-evidence` 命令（二期）**
   - 启动完整 loop 时吸收此前 standalone 证据，**指纹匹配才收**。用户先用 dev-tdd 修了一半、发现要升级成全流程时，红绿证据不作废。

5. **版本握手**
   - 子 skill 声明 `requires core >= 0.5.0`；harness 加 `--version` 输出与最低版本校验。

6. **self_test 扩展**
   - 覆盖 standalone 模式各命令、单一事实源守卫拒绝、guard-check 输出、（二期）adopt-evidence 指纹匹配。现有 self_test 已是 hermetic（用内置 gate + `CODEX_DEV_LOOP_HOME` 指向空目录），沿用同一套 fixture。

---

## 5. 场景路由逻辑（调用判断）

路由逻辑放三处，**不做独立 router skill**（多一层间接 + 双份维护）：

- **各子 skill 的 `description`** 写清互斥触发条件（`Use when… / Do NOT use when…`）。Codex 和 Claude Code 都靠 description 匹配触发，这是防误触发的第一道防线。
- **编排器 SKILL.md** 持有「升级阶梯」。
- **一份共享 `references/routing.md`** 放决策树，所有 skill 指向它。

### 5.1 决策树

```
用户请求
│
├─ ① 用户显式点名某 skill？ → 直接用
│      （若存在活动 loop → 强制以 loop 模式接入）
│
├─ ② 不改代码？
│      需求梳理 / 写 spec ............... dev-clarify
│      评审方案或 diff ................. dev-review（单角色）
│      只要方案不要实现 ............... dev-clarify(如需) → dev-plan → dev-review(plan)
│      老仓库想引入规格管理 ........... dev-spec bootstrap
│
└─ ③ 要改代码 → 两步预检后选链：
       a. 需求清楚吗？不清楚 → 先 dev-clarify（任何链之前）
       b. 跑 harness guard-check + 估计单元数 / 是否要 PR
       │
       ├─ micro   1 单元、非敏感、不发 PR
       │          → dev-tdd
       │
       ├─ small   1-2 单元、非敏感、要 PR
       │          → dev-tdd → dev-spec(delta+merge) → quality-gate(light) → dev-ship
       │
       ├─ standard 3+ 单元 或 跨模块
       │          → 完整 codex-dev-loop（scale=standard，独立单元用 dev-parallel）
       │
       └─ large   命中敏感路径 / 迁移 / 高风险
                  → 完整 codex-dev-loop（scale=large，risk review 不可跳）
```

### 5.2 运行中的升链触发线（tripwire）

微链 / 短链执行途中命中任何一条，**停下、告知用户、升级到更重的链**（已有证据凭指纹带走，见 `adopt-evidence`）：

| 触发线 | 检测方式 |
|---|---|
| 变更触及敏感路径 | `guard-check`（每次提交证据前顺带跑） |
| 实际单元数超预估 ×2 或 > 5 | 对照 dev plan |
| 测试连续失败达配置上限 | 现有失败计数器 |
| 任一 reviewer 给出 `block` | 现有评审记录 |
| diff 超出声明的文件 scope | implementation review |

### 5.3 底线闸门集（任何链，含 micro，都不可省）

- 测试证据（至少 regression 绿）
- 不碰保护分支（`main`/`master`/`develop`/`release/*`，已实现）
- 变更留档到 `.codex/evidence/`

> 这是和 Superpowers 拉开差距的地方：**可组合，但每一段都有证据。「拆开用」不等于「裸奔」。**

---

## 6. 分期实施建议

| 阶段 | 内容 | 特点 | 状态 |
|---|---|---|---|
| **P1** | harness 加 standalone 模式 + `guard-check` + `check-spec`；抽出三个最高频子 skill：**dev-tdd、dev-review、dev-clarify** | 纯增量，不动现有 loop；先验证「薄皮 + core」模式，只放三个技能便于把触发边界调准 | ✅ 已完成（2026-07-07） |
| **P2** | **dev-ship、dev-spec（含 bootstrap）、dev-plan** + `references/routing.md` | bootstrap 是唯一的全新功能点 | ✅ 已完成（2026-07-07） |
| **P3** | 编排器 SKILL.md 重写为组合调用；`adopt-evidence` 证据吸收；self_test 覆盖 standalone 与升链 | 收口，单体 → 组合的正式切换 | ✅ 已完成（2026-07-07） |
| **P4（可选）** | 借鉴 Superpowers 新增 systematic-debugging（loop 之外的独立方法论技能）；`install_skills.py` | 生态扩展 | 待开始 |

### P1 落地记录（2026-07-07）

harness core 新增命令：`version`（`--require` 版本握手，`CORE_VERSION=0.5.0-dev`）、`guard-check`（暴露 `sensitive_changed_paths()`）、`check-spec`（Goal/AC 校验，dev-clarify 用）、`standalone-fingerprint`、`standalone-test`（红绿证据，红先于绿；证据落 `<evidence_dir>/tdd/ledger.json`）、`standalone-review`（绑定 target 指纹，被审文件改动即失效；落 `<evidence_dir>/review/`）。config schema 加 `evidence_dir`（空=auto，Codex 用 `.codex/evidence/`）。单一事实源守卫 `assert_no_active_loop()`：`.codex/dev-loop/loop-state.json` 存在且 phase≠complete 时拒绝所有 standalone 写入命令（guard-check/check-spec 只读，不受限）。loop 状态机代码零改动。子 skill：`skills/dev-clarify`、`skills/dev-tdd`、`skills/dev-review`（薄皮，仅调用 harness 命令，无独立闸门逻辑）。self_test 扩展覆盖以上全部，全绿。

### P2 落地记录（2026-07-07）

harness core 新增：`standalone-test --mode red|regression-only`（regression-only 记录绿而不要求红，对应 loop 的 regression-only 单元豁免，证据如实标注 mode）；`ship-check`（dev-ship 底线闸门：git 仓库 + 非保护分支 + TDD ledger 有针对**当前树**的绿证据，指纹匹配才放行）；`check-spec-delta`（standalone 规格 delta 校验，与 loop 的 `record-spec-merge` 共用抽出的 `spec_delta_baseline_problems()`）。子 skill：`skills/dev-plan`（复用 `validate_dev_loop_artifacts.py` 独立校验，无新 harness 逻辑）、`skills/dev-spec`（bootstrap 引导 + delta + check-spec-delta）、`skills/dev-ship`（ship-check + git/gh 交付）。新增 `references/routing.md`（决策树 + tripwire + 底线闸门集 + 单一事实源，所有 skill 共享）。self_test 扩展覆盖 regression-only、ship-check 四态、check-spec-delta 三态，全绿。

### P3 落地记录（2026-07-07）

harness core 新增 `adopt-evidence`（loop implementation 阶段吸收 standalone dev-tdd 证据）：仅收 standalone green 的 workspace 指纹 == 当前 loop 工作区指纹的单元（树未变才收），red 模式单元连带导入失败的红证据并重新绑定当前 plan 指纹，使红先于绿门被诚实满足；无当前 standalone 绿的单元留待正常跑。编排器 [SKILL.md](../SKILL.md) 新增「Composition」段：各阶段方法论指向对应 `dev-*` 子 skill 作为单一来源（方法论在子 skill、强制在 harness），loop 始终用 loop 模式命令而非 `standalone-*`，并说明升级路径用 `adopt-evidence`。self_test 新增完整升链路径测试（standalone dev-tdd → 启动 loop → adopt-evidence → 满足单元门 → 吸收后改树使证据失效），全绿。至此单体 → 组合的切换收口。

**每个阶段的完成标准**：`python scripts/self_test.py` 全绿；`codex-dev-loop-0.x.0-changes.patch` 能干净地打在上一版 zip 上并复跑 self_test 通过（沿用 0.4.0 的交付验证流程）。

---

## 7. 已确认的决策（2026-07-07）

以下 5 点已与用户敲定，实现时按此执行：

1. **子 skill 命名前缀**：`dev-*`。（如 `dev-tdd`、`dev-review`。）
2. **分发形态**：monorepo 单仓多薄皮目录 + `install_skills.py`（可选择性安装子集）。不拆独立仓——理由见第 8 节风险表与「独立仓的代价」备注。
3. **standalone 证据目录**：默认 `.codex/evidence/<skill>/`；但目录可由 agent 依宿主环境选择（识别到 Codex → 用默认；非 Codex 如 Claude Code → agent 选工作区内目录并写回 config 固化）。实现细节见第 4.1 节「证据目录解析」。
4. **P1 范围**：先抽 `dev-tdd` / `dev-review` / `dev-clarify`。
5. **dev-spec bootstrap 的边界**：采用「扫描 → 提议 → 用户确认 → 落盘」的引导式流程，详见 7.1。

### 7.1 dev-spec bootstrap 设计（决策 5）

bootstrap = 老仓库从现有代码反推出初始 `specs/` 基线。它是**每仓一次性**的稀有操作，不是每次开发都跑。设计原则：

- **提议后确认，不逐条盘问**：agent 扫描代码，先产出一份「能力地图」（文件/模块 → capability → 草稿 requirement 列表）给用户，用户在**地图层面**整体编辑/批准后才落盘。逐条 requirement 确认在大仓上会把人累垮——批量在地图层确认是正确粒度。
- **扫描范围有默认、可收窄**：默认尊重 `.gitignore`，扫源码目录，跳过 tests/vendor/build/node_modules。用户可用路径参数收窄。不盲扫全仓。
- **粒度粗优先**：默认「每个顶层模块/目录一个 capability」，每个公共入口/行为一条 `#### Requirement:`。这只是**提议**，用户可重组。粗到细易（拆分简单），细到粗难（且会喷出几百条 requirement 淹没用户）。
- **幂等 / 增量**：对已有部分 `specs/` 的仓库，bootstrap 只补缺口（检测已存在的 capability 文件），不覆盖。
- **产出显式标记为草稿**：反推的 requirement 打标记（如 `<!-- draft: reverse-engineered, unreviewed -->`），让后续 loop 知道这些未经正常评审门，可在首次正式变更时补审。

### 7.2 弹性预设：哪些进安装向导，哪些留到运行时（回应用户建议）

用户的直觉是对的——不同人工作习惯不同，应该用弹性预设让用户选。但**放错地方会适得其反**。判定规则：

> **持久的个人习惯 → 进安装向导（`configure_dev_loop.json`，全局）。**
> **每仓/每任务才能定的决策 → 运行时智能默认 + 确认，不进向导。**

- bootstrap 的扫描范围、粒度**属于后者**（同一个用户在小 CLI 和大 monorepo 上的选择完全不同）→ 不进向导，走 7.1 的运行时引导。
- 现有向导已是这套哲学的范例（5 问）。可**克制地**再加 1–2 个持久预设，不要无限加旋钮（旋钮越多 = 决策疲劳 + 测试路径爆炸；把现有 5 问当上限来敬畏）。

建议新增的持久预设（候选，实现前再与用户确认取舍）：

| 候选预设 | 轴 | 说明 | 是否推荐 |
|---|---|---|---|
| `chain_autonomy` | 自动 vs 确认 | 短链是否自动跑，还是「执行前先把选好的链念给我确认」 | 推荐（习惯差异最大的一个轴） |
| `evidence_dir` | 证据落盘位置 | 非 Codex 宿主的证据目录（决策 3） | 推荐（已定，随安装固化） |
| `installed_skills` | 安装子集 | `install_skills.py` 装哪些子 skill | 推荐（有人只要 dev-tdd） |
| `default_entry_granularity` | 默认入口粒度 | 用户平时多做微修还是整特性，作为路由**平局时的倾向**——绝不覆盖对具体任务的分析 | 谨慎（易被误用成硬偏置） |

关键护栏：任何预设都只能是**路由的默认/平局倾向**，不能覆盖第 5 节决策树对**具体任务**的判断，更不能关掉第 5.3 节的底线闸门集。预设让流程贴合习惯，但证据链不容协商。

---

## 8. 风险登记

| 风险 | 缓解 |
|---|---|
| 多 skill description 之间**误触发**（该触发 A 却触发了 B） | P1 只放三个技能，先把触发边界与 `Do NOT use when` 调准，再扩 |
| **维护成本**上升（一个 core + N 薄皮 = 改一处要顾全局） | 逻辑全部收在 harness core；子 skill 只是指令皮，无独立闸门代码；self_test 扩到 standalone 兜底 |
| standalone 与 loop 证据**分叉**（同一工作区两处记录） | 单一事实源守卫（第 4.2 节）硬性拒绝活动 loop 下的 standalone |
| 升链时**证据作废**导致用户重跑 | `adopt-evidence` 指纹匹配吸收（P3） |
| 用户绕过底线闸门（micro 链裸奔） | 底线闸门集（第 5.3 节）在所有链强制，包括 micro |

**为什么不拆独立仓（决策 2 的依据）**：子 skill 与 core 紧耦合共享同一状态机、指纹算法与证据格式。独立仓会导致 ① core 要么被 N 份拷贝（必然漂移，破坏「单一 harness」）要么变成 N+1 仓依赖矩阵；② 版本兼容矩阵爆炸（改一次证据格式要跨仓协调发版）；③ 跨切面改动从一个 PR 变成多仓协同 PR；④ hermetic self_test 无法整链测试；⑤ 安装/更新体验退化（clone × N、`git pull` × N）。「独立**可触发**」由 monorepo 薄皮目录 + `install_skills.py` 即可满足，无需「独立**发版**」。

---

## 9. 关键文件与命令速查（给实现者）

- 状态机与全部命令：`scripts/dev_loop_harness.py`
- 敏感路径判定（guard-check 的现成逻辑）：`sensitive_changed_paths()` in `dev_loop_harness.py`
- 证据指纹：`plan_fingerprint()` / `workspace_fingerprint()` / `evidence_fingerprint()`
- 内置 gate（standalone 默认执行器）：`scripts/test_gate.py`、`scripts/quality_gate_fallback.py`
- 三角色评审提示词：`references/subagent-review-loop.md`
- TDD / worktree 编排 + unit-implementer 提示词：`references/tdd-parallel-units.md`
- 规格基线格式与合并规则：`references/spec-baseline.md`
- 产物模板：`references/artifact-templates.md`
- Claude Code 适配范式：`adapters/claude-code/SKILL.md`
- 自测（hermetic，扩展时的样板）：`scripts/self_test.py`
- home 重定位：环境变量 `CODEX_DEV_LOOP_HOME`（也用于宿主识别：未设置=Codex）
- 配置 schema：0.5.0 需新增键 `evidence_dir`、`chain_autonomy`、`installed_skills`（向 v2 追加，v2/v1 自动迁移；沿用 `configure_dev_loop.py` 的固化写回模式）

> 实现顺序建议：先做 harness core 改动（第 4 节）并让 self_test 覆盖，再写薄皮子 skill；子 skill 不应包含任何闸门判断逻辑——所有判断都是对 harness 命令的调用。
