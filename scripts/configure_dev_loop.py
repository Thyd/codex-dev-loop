#!/usr/bin/env python3
"""First-run configuration wizard for codex-dev-loop."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


import os


def default_output() -> Path:
    override = os.environ.get("CODEX_DEV_LOOP_HOME", "").strip()
    home = Path(override).expanduser() if override else Path.home() / ".codex"
    return home / "config" / "codex-dev-loop.json"


DEFAULT_OUTPUT = default_output()
SCHEMA_VERSION = 5

# Advanced keys kept out of the five-question wizard on purpose; they get
# safe defaults here and can be edited in the JSON directly.
ADVANCED_DEFAULTS = {
    "default_scale": "standard",
    "spec_dir": "specs",
    "max_units": 8,
    "max_files_changed": 20,
    "max_test_retries_per_unit": 3,
    "max_review_iterations": 3,
    "max_quality_fix_rounds": 2,
    "max_diff_lines": 1200,
    "test_gate_script": "",
    "quality_gate_script": "",
    "evidence_dir": "",
}

QUESTIONS = {
    "automation_level": {
        "prompt": "1. 你希望自动化到哪一步？",
        "default": "pr_without_merge",
        "options": [
            ("pr_without_merge", "创建 PR 后停止", "自动规划、开发、测试、提交、推送、开 PR，但不自动合并。"),
            ("commit_only", "提交后停止", "自动开发和测试，但不推送、不创建 PR。"),
            ("planning_only", "只做规划", "只生成方案和评审，不写代码。"),
        ],
    },
    "source_types": {
        "prompt": "2. 需求来源主要是什么？",
        "default": "markdown_notion",
        "options": [
            ("markdown_notion", "Markdown + Notion", "同时支持本地 Markdown 和 Notion 页面。"),
            ("markdown", "只用 Markdown", "只从本地 Markdown 文档读取需求。"),
            ("notion", "只用 Notion", "只从 Notion 页面读取需求。"),
        ],
    },
    "quality_profile": {
        "prompt": "3. 质量门严格度选哪种？",
        "default": "standard",
        "options": [
            ("standard", "标准", "强制 lint、typecheck、test、ai-code-quality-gate 和 GitHub Actions；第三方 PR AI review 不默认强制。"),
            ("strict", "严格", "标准项 + Semgrep / CodeQL / Sonar / Qodana 可用时必须通过。"),
            ("light", "轻量", "只强制 test 和 ai-code-quality-gate。"),
        ],
    },
    "test_failure_limit": {
        "prompt": "4. 测试失败允许自动修复几次？",
        "default": "3",
        "options": [
            ("3", "3 次", "默认值，给自动修复留出空间。"),
            ("2", "2 次", "更快停止。"),
            ("1", "1 次", "非常保守。"),
            ("0", "失败就停止", "第一次失败就停下询问。"),
        ],
    },
    "ci_quota_policy": {
        "prompt": "5. GitHub Actions CI 额度不足时怎么办？",
        "default": "wait_for_payment",
        "options": [
            ("local_fallback", "降级为本地由当前 agent 补做测试", "确认是额度或计费限制后，执行对应本地检查并记录结果，按原自动化范围继续。"),
            ("wait_for_payment", "待用户付费后再按原计划继续", "保留进度，等待用户付费、恢复额度后重跑 GitHub CI。"),
        ],
    },
}

LABELS = {key: {value: label for value, label, _ in spec["options"]} for key, spec in QUESTIONS.items()}
SOURCE_MAP = {
    "markdown_notion": ["markdown", "notion"],
    "markdown": ["markdown"],
    "notion": ["notion"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure codex-dev-loop first-run preferences.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Config JSON path.")
    parser.add_argument("--non-interactive", action="store_true", help="Write defaults or supplied values without prompting.")
    parser.add_argument("--automation-level", choices=[value for value, _, _ in QUESTIONS["automation_level"]["options"]])
    parser.add_argument("--source-types", choices=[value for value, _, _ in QUESTIONS["source_types"]["options"]])
    parser.add_argument("--quality-profile", choices=[value for value, _, _ in QUESTIONS["quality_profile"]["options"]])
    parser.add_argument("--test-failure-limit", choices=[value for value, _, _ in QUESTIONS["test_failure_limit"]["options"]])
    parser.add_argument("--ci-quota-policy", choices=[value for value, _, _ in QUESTIONS["ci_quota_policy"]["options"]])
    parser.add_argument("--reconfigure", action="store_true", help="Ask all questions again; otherwise preserve existing answers and ask only missing ones.")
    return parser.parse_args()


def choose(key: str, supplied: str | None, non_interactive: bool) -> str:
    spec = QUESTIONS[key]
    if supplied:
        return supplied
    if non_interactive:
        return str(spec["default"])

    print()
    print(spec["prompt"])
    for index, (_value, label, description) in enumerate(spec["options"], start=1):
        suffix = "（默认）" if _value == spec["default"] else ""
        print(f"  {index}. {label}{suffix} - {description}")

    while True:
        raw = input("请选择序号，直接回车使用默认值：").strip()
        if not raw:
            return str(spec["default"])
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(spec["options"]):
                return str(spec["options"][index - 1][0])
        print("输入无效，请重新选择。")


def load_existing(output: Path) -> dict:
    """Preserve answers and extension settings when upgrading configuration."""
    if output.exists():
        try:
            existing = json.loads(output.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid config JSON: {output}: {exc}") from exc
        if isinstance(existing, dict):
            return existing
        raise SystemExit(f"Config must be a JSON object: {output}")
    return {}


def build_config(args: argparse.Namespace, output: Path) -> dict:
    existing = load_existing(output)
    choices = {}
    for key in QUESTIONS:
        supplied = getattr(args, key)
        if supplied is None and not args.reconfigure:
            saved = existing.get(key)
            if key == "source_types":
                saved = next((name for name, sources in SOURCE_MAP.items() if sources == saved), None)
            if key == "test_failure_limit":
                saved = existing.get("max_test_retries_per_unit", saved)
                if saved is not None and str(saved).isdigit():
                    # Advanced JSON may use a valid limit beyond the wizard's
                    # suggested 0..3 values. A policy-only update must retain it.
                    choices[key] = str(saved)
                    continue
            if saved is not None and str(saved) in LABELS[key]:
                supplied = str(saved)
        choices[key] = choose(key, supplied, args.non_interactive)
    config = {
        **ADVANCED_DEFAULTS,
        **existing,
        "schema_version": SCHEMA_VERSION,
        "automation_level": choices["automation_level"],
        "source_types": SOURCE_MAP[choices["source_types"]],
        "quality_profile": choices["quality_profile"],
        "test_failure_limit": int(choices["test_failure_limit"]),
        "max_test_retries_per_unit": int(choices["test_failure_limit"]),
        "ci_quota_policy": choices["ci_quota_policy"],
    }
    config.pop("risk_mode", None)
    if config != existing:
        config["configured_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return config


def source_label(config: dict) -> str:
    source_types = config["source_types"]
    if source_types == ["markdown", "notion"]:
        return "Markdown + Notion"
    if source_types == ["markdown"]:
        return "只用 Markdown"
    if source_types == ["notion"]:
        return "只用 Notion"
    return ", ".join(source_types)


def print_summary(config: dict, output: Path) -> None:
    print()
    print("已完成 codex-dev-loop 初始配置。")
    print()
    print("当前设置：")
    print(f"- 自动化范围：{LABELS['automation_level'][config['automation_level']]}")
    print(f"- 需求来源：{source_label(config)}")
    print(f"- 质量门严格度：{LABELS['quality_profile'][config['quality_profile']]}")
    limit = config["test_failure_limit"]
    limit_label = "失败就停止" if limit == 0 else f"{limit} 次"
    print(f"- 测试失败自动修复次数：{limit_label}")
    print(f"- CI 额度不足时：{LABELS['ci_quota_policy'][config['ci_quota_policy']]}")
    print("- 高风险处理方式：架构、安全、数据、凭证与质量门风险始终停止并询问")
    print()
    print(f"配置文件：{output}")
    print(
        f"自动化范围当前的设置是“{LABELS['automation_level'][config['automation_level']]}”；"
        "如后续需要调整自动化范围、需求来源、质量门严格度、测试重试次数或 CI 额度不足处理方式，也请随时告知我。"
    )
    print(
        f"高级选项（默认任务规模 default_scale={config['default_scale']}、规格基线目录 spec_dir={config['spec_dir']}、"
        f"预算 max_units={config['max_units']} / max_files_changed={config['max_files_changed']} / "
        f"max_review_iterations={config['max_review_iterations']} / max_quality_fix_rounds={config['max_quality_fix_rounds']} / "
        f"max_diff_lines={config['max_diff_lines']}、gate 脚本路径覆盖）可直接编辑配置文件调整。"
    )


def make_stdout_encoding_safe() -> None:
    """Prevent localized summaries from crashing on legacy Windows encodings."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="backslashreplace")


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser()
    config = build_config(args, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    make_stdout_encoding_safe()
    print_summary(config, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


