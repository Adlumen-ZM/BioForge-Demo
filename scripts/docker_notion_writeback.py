"""
读取 .docker_review/precheck.json
读取 .docker_review/build_result.json，如果存在
重新定位 Notion 中对应版本块
更新状态行：状态：xxx
更新 JSON contract 里的 status
追加 GitHub Action 反馈日志
生成 .docker_review/writeback.json

优先级顺序判断：
precheck 没通过                  → precheck_failed
precheck 通过但 Docker Hub 已有 tag → skipped_exists
build_result 里 pushed=true       → pushed
build_result 里 build_failed=true → build_failed
其他情况                         → ready_to_build / unknown
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path.cwd()
REVIEW_DIR = ROOT / ".docker_review"

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = os.getenv("NOTION_VERSION", "2026-03-11")


class WritebackError(Exception):
    pass


def env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise WritebackError(f"Missing required environment variable: {name}")
    return value


def notion_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notion_request(
    method: str,
    path: str,
    api_key: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = requests.request(
        method,
        f"{NOTION_API_BASE}{path}",
        headers=notion_headers(api_key),
        params=params,
        json=payload,
        timeout=30,
    )

    if response.status_code >= 400:
        raise WritebackError(
            f"Notion API error {response.status_code}: {response.text[:1000]}"
        )

    return response.json()


def retrieve_all_children(block_id: str, api_key: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    start_cursor: str | None = None

    while True:
        params: dict[str, Any] = {"page_size": 100}
        if start_cursor:
            params["start_cursor"] = start_cursor

        data = notion_request(
            "GET",
            f"/blocks/{block_id}/children",
            api_key,
            params=params,
        )

        blocks.extend(data.get("results", []))

        if not data.get("has_more"):
            break

        start_cursor = data.get("next_cursor")
        if not start_cursor:
            break

    return blocks


def rich_text_to_plain(rich_text: list[dict[str, Any]] | None) -> str:
    if not rich_text:
        return ""
    return "".join(item.get("plain_text", "") for item in rich_text)


def block_text(block: dict[str, Any]) -> str:
    block_type = block.get("type")
    if not block_type:
        return ""

    payload = block.get(block_type, {})
    if not isinstance(payload, dict):
        return ""

    return rich_text_to_plain(payload.get("rich_text"))


def normalize_version(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("version "):
        value = value[8:].strip()
    return value[1:] if value.startswith("v") else value


def is_version_heading(block: dict[str, Any]) -> bool:
    if block.get("type") != "heading_2":
        return False

    text = block_text(block).strip()
    return text.startswith("v") and len(text) >= 2


def parse_json_contract_from_code_block(block: dict[str, Any]) -> dict[str, Any]:
    if block.get("type") != "code":
        raise WritebackError("Contract block is not a Notion code block.")

    code = block.get("code", {})
    content = rich_text_to_plain(code.get("rich_text")).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise WritebackError(f"Invalid JSON contract: {exc}") from exc

    if not isinstance(parsed, dict):
        raise WritebackError("JSON contract must be an object.")

    return parsed


def find_status_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in blocks:
        text = block_text(block).strip()
        if text.startswith("状态：") or text.startswith("状态:"):
            return block
        if text.lower().startswith("status:"):
            return block
    return None


def find_contract_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in blocks:
        if block.get("type") != "code":
            continue

        code = block.get("code", {})
        language = str(code.get("language", "")).lower()
        content = rich_text_to_plain(code.get("rich_text")).strip()

        if language != "json":
            continue

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            continue

        if isinstance(data, dict) and "version" in data and "image" in data and "tag" in data:
            return block

    return None


def find_feedback_heading(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for block in blocks:
        if block.get("type") not in {"heading_3", "heading_2", "paragraph"}:
            continue
        text = block_text(block).strip()
        if "GitHub Action 反馈" in text or "GitHub Actions 反馈" in text:
            return block
    return None


def find_version_section(
    page_blocks: list[dict[str, Any]],
    version: str,
) -> dict[str, Any]:
    target = normalize_version(version)

    version_indices = [
        index for index, block in enumerate(page_blocks) if block.get("type") == "heading_2"
    ]

    for pos, start_index in enumerate(version_indices):
        heading = page_blocks[start_index]
        heading_text = block_text(heading).strip()

        if normalize_version(heading_text) != target:
            continue

        end_index = version_indices[pos + 1] if pos + 1 < len(version_indices) else len(page_blocks)
        blocks = page_blocks[start_index + 1 : end_index]

        return {
            "version": target,
            "heading_block": heading,
            "blocks": blocks,
            "status_block": find_status_block(blocks),
            "contract_block": find_contract_block(blocks),
            "feedback_heading_block": find_feedback_heading(blocks),
            "last_block": page_blocks[end_index - 1] if end_index > start_index else heading,
        }

    available = ", ".join(block_text(page_blocks[i]).strip() for i in version_indices)
    raise WritebackError(f"Version v{target} not found in Notion page. Available: {available}")


def make_text(content: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": {"content": content[i:i + 2000]}}
        for i in range(0, len(content), 2000)
    ]


def update_paragraph_block(block_id: str, text: str, api_key: str) -> None:
    notion_request(
        "PATCH",
        f"/blocks/{block_id}",
        api_key,
        payload={
            "paragraph": {
                "rich_text": make_text(text),
            }
        },
    )


def update_code_block_json(block_id: str, data: dict[str, Any], api_key: str) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2)

    notion_request(
        "PATCH",
        f"/blocks/{block_id}",
        api_key,
        payload={
            "code": {
                "rich_text": make_text(content),
                "language": "json",
            }
        },
    )


def append_children(
    parent_block_id: str,
    children: list[dict[str, Any]],
    api_key: str,
    *,
    after: str | None = None,
) -> None:
    for start in range(0, len(children), 100):
        chunk = children[start : start + 100]
        payload: dict[str, Any] = {"children": chunk}
        if after:
            payload["after"] = after

        response = notion_request(
            "PATCH",
            f"/blocks/{parent_block_id}/children",
            api_key,
            payload=payload,
        )

        results = response.get("results", [])
        if results:
            after = results[-1].get("id", after)


def paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": make_text(text),
        },
    }


def heading_3_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": make_text(text),
        },
    }


def bulleted_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": make_text(text),
        },
    }


def code_block(text: str, language: str = "plain text") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": make_text(text),
            "language": language,
        },
    }


def divider_block() -> dict[str, Any]:
    return {
        "object": "block",
        "type": "divider",
        "divider": {},
    }


def read_json_file(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return default
    return json.loads(text)


def now_utc_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def github_run_url(precheck: dict[str, Any]) -> str:
    github = precheck.get("github", {})
    server_url = github.get("server_url") or os.getenv("GITHUB_SERVER_URL") or "https://github.com"
    repository = github.get("repository") or os.getenv("GITHUB_REPOSITORY") or ""
    run_id = github.get("run_id") or os.getenv("GITHUB_RUN_ID") or ""

    if repository and run_id:
        return f"{server_url}/{repository}/actions/runs/{run_id}"

    return ""


def determine_status(precheck: dict[str, Any], build_result: dict[str, Any] | None) -> str:
    if not precheck.get("passed", False):
        return "precheck_failed"

    if build_result:
        if build_result.get("pushed") is True:
            return "pushed"

        if build_result.get("build_failed") is True or build_result.get("error"):
            return "build_failed"

        if build_result.get("skipped") is True:
            return "skipped_exists"

    if precheck.get("tag_exists", False):
        return "skipped_exists"

    if precheck.get("should_build", False):
        return "ready_to_build"

    return "unknown"


def build_feedback_blocks(
    status: str,
    precheck: dict[str, Any],
    build_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    version = precheck.get("version", "")
    full_image = (
        (build_result or {}).get("full_image")
        or precheck.get("full_image")
        or ""
    )
    digest = (build_result or {}).get("digest", "")
    run_url = (build_result or {}).get("run_url") or github_run_url(precheck)
    commit_sha = (build_result or {}).get("sha") or precheck.get("github", {}).get("sha") or os.getenv("GITHUB_SHA", "")
    docker_config_hash = precheck.get("docker_config_hash", "")
    run_id = precheck.get("github", {}).get("run_id") or os.getenv("GITHUB_RUN_ID", "")

    if status == "precheck_failed":
        summary = "Notion 备案与仓库 Docker 配置不一致，未构建镜像。"
    elif status == "skipped_exists":
        summary = "Notion precheck 通过，但 Docker Hub 已存在相同 tag，已跳过构建。"
    elif status == "pushed":
        summary = "Notion precheck 通过，Docker 环境镜像已构建并推送到 Docker Hub。"
    elif status == "build_failed":
        summary = "Notion precheck 通过，但 Docker build 或 push 失败。"
    elif status == "ready_to_build":
        summary = "Notion precheck 通过，镜像可构建；当前未发现 build_result.json。"
    else:
        summary = "GitHub Action 已执行，但状态无法明确归类。"

    blocks: list[dict[str, Any]] = [
        divider_block(),
        heading_3_block(f"GitHub Action run {now_utc_text()}"),
        bulleted_block(f"结果：{status}"),
        bulleted_block(f"版本：v{version}"),
        bulleted_block(f"Image：{full_image}"),
        bulleted_block(f"Digest：{digest or 'N/A'}"),
        bulleted_block(f"Commit：{commit_sha or 'N/A'}"),
        bulleted_block(f"Run ID：{run_id or 'N/A'}"),
        bulleted_block(f"Run URL：{run_url or 'N/A'}"),
        bulleted_block(f"Docker config hash：{docker_config_hash or 'N/A'}"),
        paragraph_block(f"说明：{summary}"),
    ]

    issues = precheck.get("issues") or []
    if issues:
        blocks.append(paragraph_block("Precheck issues:"))
        for issue in issues[:30]:
            blocks.append(bulleted_block(str(issue)))

    warnings = precheck.get("warnings") or []
    if warnings:
        blocks.append(paragraph_block("Precheck warnings:"))
        for warning in warnings[:30]:
            blocks.append(bulleted_block(str(warning)))

    if build_result and build_result.get("error"):
        blocks.append(paragraph_block("Build error:"))
        blocks.append(code_block(str(build_result["error"])[:1900], "plain text"))

    pip_freeze = ""
    if build_result:
        pip_freeze = str(build_result.get("pip_freeze", "") or "")

    if pip_freeze:
        blocks.append(paragraph_block("Resolved packages:"))
        for chunk in split_text(pip_freeze, 1900):
            blocks.append(code_block(chunk, "plain text"))

    return blocks


def split_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines():
        extra = len(line) + 1
        if current and current_len + extra > max_len:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

        current.append(line)
        current_len += extra

    if current:
        chunks.append("\n".join(current))

    return chunks


def section_contains_run_id(section_blocks: list[dict[str, Any]], run_id: str) -> bool:
    if not run_id:
        return False

    needle = f"Run ID：{run_id}"
    alt_needle = f"Run ID: {run_id}"

    for block in section_blocks:
        text = block_text(block)
        if needle in text or alt_needle in text:
            return True

    return False


def update_status_blocks(
    section: dict[str, Any],
    status: str,
    api_key: str,
) -> None:
    status_block = section.get("status_block")
    if status_block:
        update_paragraph_block(status_block["id"], f"状态：{status}", api_key)

    contract_block = section.get("contract_block")
    if not contract_block:
        raise WritebackError("No JSON contract block found in version section.")

    contract = parse_json_contract_from_code_block(contract_block)
    contract["status"] = status
    contract.setdefault("github_action", {})
    contract["github_action"]["last_writeback_at"] = now_utc_text()

    update_code_block_json(contract_block["id"], contract, api_key)


def ensure_feedback_heading(
    page_id: str,
    section: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    existing = section.get("feedback_heading_block")
    if existing:
        return existing

    after_id = section["last_block"]["id"]

    payload = {
        "children": [
            heading_3_block("GitHub Action 反馈"),
        ],
        "after": after_id,
    }

    response = notion_request(
        "PATCH",
        f"/blocks/{page_id}/children",
        api_key,
        payload=payload,
    )

    results = response.get("results", [])
    if not results:
        raise WritebackError("Failed to create GitHub Action feedback heading.")

    return results[-1]


def writeback() -> dict[str, Any]:
    api_key = env_required("NOTION_API_KEY")
    page_id = env_required("NOTION_DOCKER_PAGE_ID")

    precheck_path = REVIEW_DIR / "precheck.json"
    build_result_path = REVIEW_DIR / "build_result.json"

    precheck = read_json_file(precheck_path)
    if not isinstance(precheck, dict):
        raise WritebackError(f"Missing or invalid precheck file: {precheck_path}")

    build_result = read_json_file(build_result_path)
    if build_result is not None and not isinstance(build_result, dict):
        raise WritebackError(f"Invalid build result file: {build_result_path}")

    version = str(precheck.get("version") or "").strip()
    if not version:
        raise WritebackError("precheck.json does not contain `version`.")

    page_blocks = retrieve_all_children(page_id, api_key)
    section = find_version_section(page_blocks, version)

    status = determine_status(precheck, build_result)

    update_status_blocks(section, status, api_key)

    run_id = precheck.get("github", {}).get("run_id") or os.getenv("GITHUB_RUN_ID", "")
    duplicate = section_contains_run_id(section["blocks"], str(run_id))

    feedback_heading = ensure_feedback_heading(page_id, section, api_key)

    appended = False
    if not duplicate:
        feedback_blocks = build_feedback_blocks(status, precheck, build_result)
        append_children(
            page_id,
            feedback_blocks,
            api_key,
            after=section["last_block"]["id"],
        )
        appended = True

    result = {
        "ok": True,
        "status": status,
        "version": version,
        "appended_feedback": appended,
        "duplicate_run_id": bool(duplicate),
        "notion_page_id": page_id,
        "notion_version_block_id": section["heading_block"]["id"],
        "notion_feedback_heading_block_id": feedback_heading["id"],
        "run_id": run_id,
        "written_at": now_utc_text(),
    }

    return result


def main() -> int:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        result = writeback()
        exit_code = 0
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "written_at": now_utc_text(),
        }
        exit_code = 1

    (REVIEW_DIR / "writeback.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
