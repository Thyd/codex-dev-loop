# Routing — 选哪条链 / 哪个子 skill

`codex-dev-loop` 是「一个 harness core + 一组 `dev-*` 薄皮子 skill + 编排器」。本文件是所有 skill 共享的路由决策依据。核心原则：**可组合，但每一段都有证据。「拆开用」不等于「裸奔」。**

约定：`<core>` = `<codex-dev-loop 目录>/scripts/dev_loop_harness.py`。

## 子 skill 速览

| skill | 干什么 | 独立触发场景 |
|---|---|---|
| `dev-clarify` | 把模糊需求聊成 Goal/AC 齐全的 spec | 「我有个想法」 |
| `dev-debug` | 复现并定位未知根因，再用回归测试锁定修复 | 测试失败、崩溃或错误行为且根因未明 |
| `dev-plan` | 产出规划五件套，不写代码 | 只要方案不要实现 |
| `dev-review` | 独立 reviewer 审方案/diff，绑定指纹 | 要个第二意见 |
| `dev-tdd` | 单元内红绿 TDD，红先于绿 | 修一个 bug / 加一个小行为 |
| `dev-spec` | 规格基线 bootstrap / delta / 合并校验 | 老仓库引入规格管理；沉淀需求变更 |
| `dev-ship` | 底线闸门 + branch/commit/push/PR/CI | 小改动发 PR |
| `codex-dev-loop`（编排器） | 完整状态机全闸门流水线 | 标准/大型/高风险任务 |

## 决策树

```
用户请求
│
├─ ① 用户显式点名某 skill？ → 直接用
│      （若存在活动 loop：loop-state.json 存在且 phase≠complete → 只能以 loop 模式接入，
│        standalone 写入命令会被 harness 拒绝）
│
├─ ② 不改代码？
│      需求梳理 / 写 spec ............... dev-clarify
│      评审方案或 diff ................. dev-review（单角色）
│      只要方案不要实现 ............... dev-clarify(如需) → dev-plan → dev-review(plan)
│      老仓库想引入规格管理 ........... dev-spec（bootstrap）
│      仅替换图片/文案/静态资产 ......... 轻量资产通道：用 regression-only 记录
│                                      完整性 + 引用 + 受影响界面/构建校验
│                                      （默认不跑代码全量测试）
│
└─ ③ 要改代码 → 两步预检后选链：
       a. 需求清楚吗？不清楚 → 先 dev-clarify
       b. 是未知根因的故障吗？是 → dev-debug → dev-tdd
       c. python <core> guard-check + 估计单元数 / 是否要 PR
       d. 按 validation-selection.md 选择 artifact / targeted / impacted / full
       │
       ├─ micro   1 单元、非敏感、不发 PR
       │          → dev-tdd
       │
       ├─ small   1-2 单元、非敏感、要 PR
       │          → dev-tdd →（如有规格变更）dev-spec(delta+合并) → dev-ship
       │
       ├─ standard 3+ 单元 或 跨模块
       │          → 完整 codex-dev-loop（scale=standard；独立单元用 worktree 并行）
       │
       └─ large   命中敏感路径 / 迁移 / 高风险
                  → 完整 codex-dev-loop（scale=large，risk review 不可跳）
```

## 运行中的升链触发线（tripwire）

微链 / 短链执行途中命中任一条：**停下、告知用户、升级到更重的链**（已有 standalone 证据凭指纹可被完整 loop 吸收——`adopt-evidence`，P3 提供）。

| 触发线 | 检测 |
|---|---|
| 变更触及敏感路径 | `python <core> guard-check`（每次提交证据前顺带跑） |
| 实际单元数超预估 ×2 或 > 5 | 对照规划 |
| 测试连续失败达配置上限 | 失败计数器 |
| 任一 reviewer 给出 `block` | `dev-review` / loop 评审 |
| diff 超出声明的文件 scope | 实现评审 |

## 底线闸门集（任何链，含轻量资产通道，都不可省）

- **验证证据**：代码行为的每个 behavior label 都必须有针对当前树的最新绿测（`dev-tdd` 红绿，或诚实的 `regression-only`）；非行为型资产变更必须有完整性、引用和受影响表面的校验证据。验证范围按 [validation-selection.md](validation-selection.md) 选择；不得把“不跑全量”变成“不验证”。`dev-ship` 的 `ship-check --label ...` 会强制代码行为证据。
- **不碰保护分支**：`main`/`master`/`develop`/`release/*`。`ship-check` 会强制。
- **变更留档**：证据落 `<evidence_dir>/`（默认 `.codex/evidence/`）。

## 单一事实源

一个工作区任一时刻只有一处证据记录：

- 无活动 loop → 子 skill 走 standalone，证据落 `.codex/evidence/`。
- 有活动 loop（phase≠complete）→ 子 skill 的 standalone 写入命令被 harness 拒绝；改用 loop 自身命令，证据落 `.codex/dev-loop/`。

`guard-check`、`check-spec`、`check-spec-delta`、`standalone-fingerprint` 是只读的，任何时候都能用。
