"""
读取 Notion 页面
找到对应版本块
解析 JSON contract
检查 Dockerfile / requirements.txt / docker-compose.yml / .dockerignore
检查 docker-compose.yml 是否使用 DOCKER_IMAGE / DOCKER_TAG
检查 Dockerfile base image 是否和 Notion 一致
计算配置 hash
检查 Docker Hub 是否已有 image:tag
生成 .docker_review/precheck.json
生成 .docker_review/docker.env
生成 .docker_review/comment.md
输出 GitHub Actions outputs
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


ROOT = Path.cwd()
REVIEW_DIR = ROOT / ".docker_review"

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = os.getenv("NOTION_VERSION", "2026-03-11")

COMMENT_MARKER = "<!-- bioforge-docker-contract-precheck -->"

REQUIRED_CONTRACT_FIELDS = [
    "schema_version",
    "version",
    "status",
    "image",
    "tag",
    "image_type",
    "base_image",
    "dockerfile",
    "compose_file",
    "requirements_file",
]


@dataclass
class VersionSection:
    version: str
    heading_block: dict[str, Any]
    blocks: list[dict[str, Any]]
    status_block: dict[str, Any] | None
    contract_block: dict[str, Any] | None
    feedback_heading_block: dict[str, Any] | None


class PrecheckError(Exception):
    pass


def env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise PrecheckError(f"Missing required environment variable: {name}")
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
    url = f"{NOTION_API_BASE}{path}"
    response = requests.request(
        method,
        url,
        headers=notion_headers(api_key),
        params=params,
        json=payload,
        timeout=30,
    )

    if response.status_code >= 400:
        raise PrecheckError(
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
    return bool(re.match(r"^v?\d+\.\d+\.\d+([-.+][A-Za-z0-9_.-]+)?$", text))


def parse_json_contract_from_code_block(block: dict[str, Any]) -> dict[str, Any]:
    if block.get("type") != "code":
        raise PrecheckError("Contract block is not a Notion code block.")

    code = block.get("code", {})
    language = code.get("language", "")
    content = rich_text_to_plain(code.get("rich_text")).strip()

    if language and language.lower() != "json":
        raise PrecheckError(f"Contract code block language should be json, got: {language}")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PrecheckError(f"Invalid JSON contract: {exc}") from exc

    if not isinstance(parsed, dict):
        raise PrecheckError("JSON contract must be an object.")

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

        if language == "json":
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


def find_version_sections(page_blocks: list[dict[str, Any]]) -> list[VersionSection]:
    sections: list[VersionSection] = []

    version_indices = [
        index for index, block in enumerate(page_blocks) if is_version_heading(block)
    ]

    for pos, start_index in enumerate(version_indices):
        end_index = version_indices[pos + 1] if pos + 1 < len(version_indices) else len(page_blocks)

        heading_block = page_blocks[start_index]
        section_blocks = page_blocks[start_index + 1 : end_index]
        version = normalize_version(block_text(heading_block))

        sections.append(
            VersionSection(
                version=version,
                heading_block=heading_block,
                blocks=section_blocks,
                status_block=find_status_block(section_blocks),
                contract_block=find_contract_block(section_blocks),
                feedback_heading_block=find_feedback_heading(section_blocks),
            )
        )

    return sections


def choose_version_section(
    sections: list[VersionSection],
    requested_version: str | None,
) -> VersionSection:
    if not sections:
        raise PrecheckError("No version section found. Expected heading like: ## v0.1.0")

    if requested_version:
        target = normalize_version(requested_version)
        matches = [section for section in sections if normalize_version(section.version) == target]
        if not matches:
            available = ", ".join(f"v{section.version}" for section in sections)
            raise PrecheckError(
                f"Version v{target} not found in Notion page. Available: {available}"
            )
        return matches[-1]

    pending_sections: list[VersionSection] = []

    for section in sections:
        if not section.contract_block:
            continue
        try:
            contract = parse_json_contract_from_code_block(section.contract_block)
        except PrecheckError:
            continue

        status = str(contract.get("status", "")).strip().lower()
        if status == "pending":
            pending_sections.append(section)

    if pending_sections:
        return pending_sections[-1]

    return sections[-1]


def validate_contract(contract: dict[str, Any], heading_version: str) -> list[str]:
    issues: list[str] = []

    for field in REQUIRED_CONTRACT_FIELDS:
        if field not in contract or contract[field] in (None, ""):
            issues.append(f"Missing required contract field: `{field}`")

    if "version" in contract:
        contract_version = normalize_version(str(contract["version"]))
        if contract_version != normalize_version(heading_version):
            issues.append(
                f"Contract version `{contract['version']}` does not match heading `v{heading_version}`."
            )

    if str(contract.get("image_type", "")).strip() != "environment":
        issues.append("`image_type` should be `environment` for the current workflow.")

    image = str(contract.get("image", "")).strip()
    if image and image_has_embedded_tag(image):
        issues.append("`image` should not include a tag. Put the tag in the `tag` field.")

    return issues


def image_has_embedded_tag(image: str) -> bool:
    last = image.rsplit("/", 1)[-1]
    return ":" in last


def clean_image_name(image: str) -> str:
    image = image.strip()

    if image_has_embedded_tag(image):
        image = image.rsplit(":", 1)[0]

    if image.startswith("docker.io/"):
        image = image[len("docker.io/") :]

    if image.startswith("registry-1.docker.io/"):
        image = image[len("registry-1.docker.io/") :]

    return image


def full_image_name(image: str, tag: str) -> str:
    return f"{clean_image_name(image)}:{tag}"


def dockerhub_repository_path(image: str) -> str:
    image = clean_image_name(image)

    first_part = image.split("/", 1)[0]
    if "." in first_part or ":" in first_part:
        raise PrecheckError(
            f"Only Docker Hub images are supported by this precheck, got image: {image}"
        )

    if "/" not in image:
        return f"library/{image}"

    return image


def dockerhub_tag_exists(image: str, tag: str) -> tuple[bool, str]:
    repo_path = dockerhub_repository_path(image)

    username = os.getenv("DOCKERHUB_USERNAME")
    token_or_password = os.getenv("DOCKERHUB_TOKEN")

    auth = None
    if username and token_or_password:
        auth = (username, token_or_password)

    token_response = requests.get(
        "https://auth.docker.io/token",
        params={
            "service": "registry.docker.io",
            "scope": f"repository:{repo_path}:pull",
        },
        auth=auth,
        timeout=30,
    )

    if token_response.status_code >= 400:
        return False, (
            f"Failed to get Docker registry token for `{repo_path}`: "
            f"{token_response.status_code} {token_response.text[:500]}"
        )

    registry_token = token_response.json().get("token")
    if not registry_token:
        return False, f"Failed to get Docker registry token for `{repo_path}`."

    manifest_url = f"https://registry-1.docker.io/v2/{repo_path}/manifests/{tag}"
    manifest_response = requests.head(
        manifest_url,
        headers={
            "Authorization": f"Bearer {registry_token}",
            "Accept": (
                "application/vnd.docker.distribution.manifest.v2+json,"
                "application/vnd.docker.distribution.manifest.list.v2+json,"
                "application/vnd.oci.image.manifest.v1+json,"
                "application/vnd.oci.image.index.v1+json"
            ),
        },
        timeout=30,
    )

    if manifest_response.status_code == 200:
        return True, "Docker Hub tag exists."

    if manifest_response.status_code == 404:
        return False, "Docker Hub tag does not exist."

    return False, (
        f"Unexpected Docker Hub manifest response for `{repo_path}:{tag}`: "
        f"{manifest_response.status_code} {manifest_response.text[:500]}"
    )


def read_file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_config_hash(paths: list[Path]) -> str:
    hasher = hashlib.sha256()

    for path in sorted(paths, key=lambda p: str(p)):
        if not path.exists():
            continue

        relative = path.relative_to(ROOT)
        hasher.update(str(relative).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")

    return hasher.hexdigest()


def extract_dockerfile_base_images(dockerfile_text: str) -> list[str]:
    images: list[str] = []

    for line in dockerfile_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        match = re.match(r"^FROM\s+([^\s]+)", line, flags=re.IGNORECASE)
        if match:
            images.append(match.group(1))

    return images


def find_unpinned_requirements(requirements_text: str) -> list[str]:
    unpinned: list[str] = []

    for raw_line in requirements_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith(("-r ", "--requirement", "-c ", "--constraint", "--extra-index-url", "--index-url")):
            continue

        if "==" in line or " @ " in line:
            continue

        unpinned.append(line)

    return unpinned


def validate_local_files(contract: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    issues: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    dockerfile_path = ROOT / str(contract.get("dockerfile", "Dockerfile"))
    compose_path = ROOT / str(contract.get("compose_file", "docker-compose.yml"))
    requirements_path = ROOT / str(contract.get("requirements_file", "requirements.txt"))
    dockerignore_path = ROOT / ".dockerignore"

    details["paths"] = {
        "dockerfile": str(dockerfile_path.relative_to(ROOT)) if dockerfile_path.exists() else str(dockerfile_path),
        "compose_file": str(compose_path.relative_to(ROOT)) if compose_path.exists() else str(compose_path),
        "requirements_file": str(requirements_path.relative_to(ROOT)) if requirements_path.exists() else str(requirements_path),
        "dockerignore": ".dockerignore",
    }

    for label, path in [
        ("Dockerfile", dockerfile_path),
        ("docker-compose.yml", compose_path),
        ("requirements.txt", requirements_path),
    ]:
        if not path.exists():
            issues.append(f"{label} not found at `{path}`.")

    if not dockerignore_path.exists():
        warnings.append("`.dockerignore` not found. This is allowed but not recommended.")

    if dockerfile_path.exists():
        dockerfile_text = read_file_text(dockerfile_path)
        base_images = extract_dockerfile_base_images(dockerfile_text)
        details["base_images_in_dockerfile"] = base_images

        expected_base_image = str(contract.get("base_image", "")).strip()
        if expected_base_image and expected_base_image not in base_images:
            issues.append(
                f"Dockerfile base image mismatch. Notion expects `{expected_base_image}`, "
                f"but Dockerfile has: {base_images or 'no FROM found'}."
            )

    if compose_path.exists():
        compose_text = read_file_text(compose_path)
        if "DOCKER_IMAGE" not in compose_text or "DOCKER_TAG" not in compose_text:
            issues.append(
                "`docker-compose.yml` should use `${DOCKER_IMAGE}:${DOCKER_TAG}` "
                "instead of a hard-coded image tag."
            )

    if requirements_path.exists():
        requirements_text = read_file_text(requirements_path)
        details["requirements_hash"] = sha256_file(requirements_path)

        package_policy = contract.get("package_policy", {})
        allow_unpinned = True
        if isinstance(package_policy, dict):
            allow_unpinned = bool(package_policy.get("allow_unpinned", True))

        unpinned = find_unpinned_requirements(requirements_text)
        details["unpinned_requirements"] = unpinned

        if unpinned and not allow_unpinned:
            issues.append(
                "Unpinned requirements found while `package_policy.allow_unpinned=false`: "
                + ", ".join(f"`{item}`" for item in unpinned[:20])
            )
        elif unpinned:
            warnings.append(
                "Unpinned requirements found. Allowed in current policy, but final image should record resolved versions."
            )

    hash_paths = [dockerfile_path, compose_path, requirements_path, dockerignore_path]
    details["docker_config_hash"] = compute_config_hash(hash_paths)

    file_hashes: dict[str, str] = {}
    for path in hash_paths:
        if path.exists():
            file_hashes[str(path.relative_to(ROOT))] = sha256_file(path)

    details["file_hashes"] = file_hashes

    return issues, warnings, details


def make_rich_text(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": content[:2000]}}]


def write_github_output(name: str, value: str | int | bool) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    normalized = str(value).lower() if isinstance(value, bool) else str(value)

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"{name}={normalized}\n")


def append_step_summary(markdown: str) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(markdown)
        f.write("\n")


def write_docker_env(image: str, tag: str) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    env_path = REVIEW_DIR / "docker.env"
    env_path.write_text(
        f"DOCKER_IMAGE={clean_image_name(image)}\nDOCKER_TAG={tag}\n",
        encoding="utf-8",
    )


def render_comment(result: dict[str, Any]) -> str:
    passed = result["passed"]
    should_build = result["should_build"]
    tag_exists = result["tag_exists"]

    if not passed:
        title = "Docker Notion precheck ❌"
        status = "precheck_failed"
    elif tag_exists:
        title = "Docker Notion precheck ✅"
        status = "skipped_exists"
    elif should_build:
        title = "Docker Notion precheck ✅"
        status = "ready_to_build"
    else:
        title = "Docker Notion precheck ✅"
        status = "passed"

    lines: list[str] = [
        COMMENT_MARKER,
        f"# {title}",
        "",
        f"Status: **{status}**",
        "",
        "This check compares the Notion Docker environment record with repository Docker configuration.",
        "",
        "## Summary",
        "",
        f"- Version: `v{result.get('version', '')}`",
        f"- Image: `{result.get('full_image', '')}`",
        f"- Precheck passed: **{str(passed).lower()}**",
        f"- Docker Hub tag exists: **{str(tag_exists).lower()}**",
        f"- Should build: **{str(should_build).lower()}**",
        f"- Docker config hash: `{result.get('docker_config_hash', '')}`",
        "",
    ]

    if result.get("issues"):
        lines.append("## Issues")
        lines.append("")
        for item in result["issues"]:
            lines.append(f"- {item}")
        lines.append("")

    if result.get("warnings"):
        lines.append("## Warnings")
        lines.append("")
        for item in result["warnings"]:
            lines.append(f"- {item}")
        lines.append("")

    lines.extend(
        [
            "## Generated files",
            "",
            "- `.docker_review/precheck.json`",
            "- `.docker_review/docker.env`",
            "- `.docker_review/comment.md`",
            "",
        ]
    )

    return "\n".join(lines)


def write_outputs(result: dict[str, Any]) -> None:
    write_github_output("passed", result["passed"])
    write_github_output("should_build", result["should_build"])
    write_github_output("tag_exists", result["tag_exists"])
    write_github_output("version", result.get("version", ""))
    write_github_output("image", result.get("image", ""))
    write_github_output("tag", result.get("tag", ""))
    write_github_output("full_image", result.get("full_image", ""))
    write_github_output("docker_config_hash", result.get("docker_config_hash", ""))
    write_github_output("notion_version_block_id", result.get("notion_version_block_id", ""))
    write_github_output("notion_status_block_id", result.get("notion_status_block_id", ""))
    write_github_output("notion_contract_block_id", result.get("notion_contract_block_id", ""))
    write_github_output("notion_feedback_heading_block_id", result.get("notion_feedback_heading_block_id", ""))


def run_precheck() -> dict[str, Any]:
    api_key = env_required("NOTION_API_KEY")
    page_id = env_required("NOTION_DOCKER_PAGE_ID")
    requested_version = os.getenv("DOCKER_ENV_VERSION") or os.getenv("DOCKER_VERSION")

    page_blocks = retrieve_all_children(page_id, api_key)
    sections = find_version_sections(page_blocks)
    section = choose_version_section(sections, requested_version)

    if not section.contract_block:
        raise PrecheckError(f"No JSON contract block found under version `v{section.version}`.")

    contract = parse_json_contract_from_code_block(section.contract_block)

    issues: list[str] = []
    warnings: list[str] = []

    issues.extend(validate_contract(contract, section.version))

    local_issues, local_warnings, local_details = validate_local_files(contract)
    issues.extend(local_issues)
    warnings.extend(local_warnings)

    image = str(contract.get("image", "")).strip()
    tag = str(contract.get("tag", "")).strip()
    full_image = full_image_name(image, tag) if image and tag else ""

    tag_exists = False
    dockerhub_check_message = ""

    if image and tag:
        tag_exists, dockerhub_check_message = dockerhub_tag_exists(image, tag)
        if dockerhub_check_message.startswith("Unexpected") or dockerhub_check_message.startswith("Failed"):
            issues.append(dockerhub_check_message)

    passed = len(issues) == 0
    should_build = bool(passed and not tag_exists)

    result: dict[str, Any] = {
        "passed": passed,
        "should_build": should_build,
        "tag_exists": tag_exists,
        "version": normalize_version(str(contract.get("version", section.version))),
        "image": clean_image_name(image) if image else "",
        "tag": tag,
        "full_image": full_image,
        "contract": contract,
        "issues": issues,
        "warnings": warnings,
        "dockerhub_check_message": dockerhub_check_message,
        "docker_config_hash": local_details.get("docker_config_hash", ""),
        "details": local_details,
        "notion_page_id": page_id,
        "notion_version_block_id": section.heading_block.get("id", ""),
        "notion_status_block_id": section.status_block.get("id", "") if section.status_block else "",
        "notion_contract_block_id": section.contract_block.get("id", "") if section.contract_block else "",
        "notion_feedback_heading_block_id": section.feedback_heading_block.get("id", "") if section.feedback_heading_block else "",
        "github": {
            "event_name": os.getenv("GITHUB_EVENT_NAME", ""),
            "repository": os.getenv("GITHUB_REPOSITORY", ""),
            "sha": os.getenv("GITHUB_SHA", ""),
            "run_id": os.getenv("GITHUB_RUN_ID", ""),
            "run_number": os.getenv("GITHUB_RUN_NUMBER", ""),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
            "server_url": os.getenv("GITHUB_SERVER_URL", "https://github.com"),
        },
    }

    return result


def main() -> int:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        result = run_precheck()
    except Exception as exc:
        result = {
            "passed": False,
            "should_build": False,
            "tag_exists": False,
            "version": os.getenv("DOCKER_ENV_VERSION") or os.getenv("DOCKER_VERSION") or "",
            "image": "",
            "tag": "",
            "full_image": "",
            "issues": [str(exc)],
            "warnings": [],
            "docker_config_hash": "",
            "notion_page_id": os.getenv("NOTION_DOCKER_PAGE_ID", ""),
            "notion_version_block_id": "",
            "notion_status_block_id": "",
            "notion_contract_block_id": "",
            "notion_feedback_heading_block_id": "",
        }

    if result.get("image") and result.get("tag"):
        write_docker_env(str(result["image"]), str(result["tag"]))

    comment = render_comment(result)

    (REVIEW_DIR / "precheck.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (REVIEW_DIR / "comment.md").write_text(comment, encoding="utf-8")

    write_outputs(result)
    append_step_summary(comment)

    if os.getenv("PRECHECK_EXIT_ON_FAIL", "false").lower() == "true" and not result["passed"]:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
