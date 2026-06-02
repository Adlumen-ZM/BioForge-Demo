"""
docker_notion_precheck.py

用途：
    这是 Docker 环境镜像发布前的 Notion precheck 脚本。

整体流程：
    1. 从 Notion 页面读取 Docker 环境版本记录；
    2. 找到当前要检查的版本块，例如 ## v0.1.0；
    3. 解析版本块中的 JSON contract；
    4. 检查本地 Docker 配置文件：
       - Dockerfile
       - docker-compose.yml
       - requirements.txt
       - .dockerignore
    5. 检查 Dockerfile 的 base image 是否和 Notion 备案一致；
    6. 检查 docker-compose.yml 是否使用 ${DOCKER_IMAGE}:${DOCKER_TAG}；
    7. 计算 Docker 配置 hash；
    8. 检查当前目标 Docker Hub image:tag 是否已经存在；
    9. 如果 JSON 里 previous 不为 null：
       - 拉取上一版 Docker 镜像；
       - 优先读取上一版镜像中的 /app/requirements.txt；
       - 如果读不到，则退回到 python -m pip freeze；
       - 对比上一版依赖、当前 requirements.txt、package_changes；
    10. 生成以下运行产物：
       - .docker_review/precheck.json
       - .docker_review/docker.env
       - .docker_review/comment.md
    11. 输出 GitHub Actions outputs，供 docker-push.yml 后续 job 使用。

注意：
    - 机器读取的 Notion JSON 代码块必须是合法 JSON，不能有 // 或 # 注释。
    - 如果这是第一个 Docker 环境版本，Notion JSON 里的 previous 应写为 null。
    - 如果不是第一个版本，previous 应写为：
      {
        "version": "0.0.9",
        "image": "bioforge/pepclaw",
        "tag": "0.0.9"
      }
    - 为了让上一版依赖对比更准确，Dockerfile 最终运行阶段应保留：
      COPY requirements.txt /app/requirements.txt
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


# ============================================================
# 全局常量
# ============================================================

# 当前 GitHub Actions checkout 后的仓库根目录。
ROOT = Path.cwd()

# 本脚本所有临时产物都放在 .docker_review/ 下。
# 该目录应该被 .gitignore 忽略，不进入仓库。
REVIEW_DIR = ROOT / ".docker_review"

# Notion API 基础地址。
NOTION_API_BASE = "https://api.notion.com/v1"

# Notion API version。
# workflow 里也会传 NOTION_VERSION="2022-06-28"。
NOTION_VERSION = os.getenv("NOTION_VERSION", "2022-06-28")

# PR comment 里的隐藏标记。
# github-script 会用这个 marker 判断是新建 comment，还是更新旧 comment。
COMMENT_MARKER = "<!-- bioforge-docker-contract-precheck -->"

# Notion JSON contract 中当前要求存在的字段。
# previous 单独检查，因为它允许为 null。
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
    "package_changes",
    "package_policy",
]

# requirements.txt 中一些不是包依赖本身的选项行。
# 这些行在解析包名时会跳过。
REQUIREMENT_OPTION_PREFIXES = (
    "-r ",
    "--requirement",
    "-c ",
    "--constraint",
    "--extra-index-url",
    "--index-url",
    "--find-links",
    "-f ",
    "--trusted-host",
    "--pre",
)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class VersionSection:
    """
    表示 Notion 页面中的一个版本块。

    例如 Notion 页面中：

        ## v0.1.0

        状态：pending

        ```json
        {...}
        ```

        ### GitHub Action 反馈

    这个 heading_2 到下一个 heading_2 之间，就是一个 VersionSection。
    """

    version: str
    heading_block: dict[str, Any]
    blocks: list[dict[str, Any]]
    status_block: dict[str, Any] | None
    contract_block: dict[str, Any] | None
    feedback_heading_block: dict[str, Any] | None


@dataclass
class RequirementEntry:
    """
    表示 requirements.txt 或 pip freeze 中解析出的一条依赖。

    例如：
        docling>=0.5.0

    会解析成：
        name = "docling"
        normalized_name = "docling"
        requirement = "docling>=0.5.0"

    normalized_name 用于比较。
    因为 Python 包名中 -、_、. 经常混用，所以统一归一化。
    """

    name: str
    normalized_name: str
    requirement: str


class PrecheckError(Exception):
    """precheck 过程中的可预期错误。"""

    pass


# ============================================================
# 通用工具函数
# ============================================================

def env_required(name: str) -> str:
    """
    读取必需的环境变量。

    如果缺失，直接抛出 PrecheckError。
    例如 NOTION_API_KEY、NOTION_DOCKER_PAGE_ID 必须存在。
    """

    value = os.getenv(name)
    if not value:
        raise PrecheckError(f"Missing required environment variable: {name}")
    return value


def normalize_version(value: str) -> str:
    """
    规范化版本号。

    支持：
        v0.1.0 -> 0.1.0
        0.1.0  -> 0.1.0

    这样 Notion 标题 ## v0.1.0 和 JSON 里的 "version": "0.1.0"
    可以正常比较。
    """

    value = value.strip()
    if value.lower().startswith("version "):
        value = value[8:].strip()
    return value[1:] if value.startswith("v") else value


def normalize_package_name(name: str) -> str:
    """
    规范化 Python 包名。

    Python 包名比较时，常见规则是把 -, _, . 视为相近分隔符。
    例如：
        langchain_community
        langchain-community

    统一转成：
        langchain-community
    """

    return re.sub(r"[-_.]+", "-", name).lower().strip()


def image_has_embedded_tag(image: str) -> bool:
    """
    判断 image 字段里是否错误地带了 tag。

    正确：
        "image": "bioforge/pepclaw"
        "tag": "0.1.0"

    错误：
        "image": "bioforge/pepclaw:0.1.0"
    """

    last = image.rsplit("/", 1)[-1]
    return ":" in last


def clean_image_name(image: str) -> str:
    """
    清理 Docker image 名。

    支持把：
        docker.io/bioforge/pepclaw
        registry-1.docker.io/bioforge/pepclaw

    统一成：
        bioforge/pepclaw
    """

    image = image.strip()

    if image_has_embedded_tag(image):
        image = image.rsplit(":", 1)[0]

    if image.startswith("docker.io/"):
        image = image[len("docker.io/") :]

    if image.startswith("registry-1.docker.io/"):
        image = image[len("registry-1.docker.io/") :]

    return image


def full_image_name(image: str, tag: str) -> str:
    """
    拼接完整 Docker 镜像名。

    例如：
        image = bioforge/pepclaw
        tag   = 0.1.0

    返回：
        bioforge/pepclaw:0.1.0
    """

    return f"{clean_image_name(image)}:{tag}"


def read_file_text(path: Path) -> str:
    """读取文本文件，遇到异常字符时尽量替换而不是失败。"""

    return path.read_text(encoding="utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    """计算文件 sha256。用于记录 Docker 配置文件 hash。"""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_config_hash(paths: list[Path]) -> str:
    """
    计算 Docker 环境配置整体 hash。

    纳入 hash 的文件通常包括：
        Dockerfile
        docker-compose.yml
        requirements.txt
        .dockerignore

    这个 hash 会写回 Notion，方便追踪某次镜像构建对应的配置。
    """

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


# ============================================================
# Notion API 相关函数
# ============================================================

def notion_headers(api_key: str) -> dict[str, str]:
    """构造 Notion API 请求头。"""

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
    """
    封装 Notion API 请求。

    method:
        GET / PATCH 等。

    path:
        例如 /blocks/{page_id}/children。

    如果 Notion 返回 4xx/5xx，则抛出 PrecheckError。
    """

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
    """
    读取某个 Notion block/page 的所有直接子 block。

    Notion block children API 是分页的，所以需要循环读取。
    """

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
    """
    把 Notion rich_text 数组转成纯文本。

    Notion 的 paragraph、heading、code 内容都是 rich_text 结构。
    """

    if not rich_text:
        return ""
    return "".join(item.get("plain_text", "") for item in rich_text)


def block_text(block: dict[str, Any]) -> str:
    """
    读取一个 Notion block 的文本内容。

    支持 paragraph、heading、code 等有 rich_text 的 block。
    """

    block_type = block.get("type")
    if not block_type:
        return ""

    payload = block.get(block_type, {})
    if not isinstance(payload, dict):
        return ""

    return rich_text_to_plain(payload.get("rich_text"))


def is_version_heading(block: dict[str, Any]) -> bool:
    """
    判断一个 block 是否为版本标题。

    要求是 heading_2，且文本类似：
        v0.1.0
        0.1.0
        v0.1.0-beta.1
    """

    if block.get("type") != "heading_2":
        return False

    text = block_text(block).strip()
    return bool(re.match(r"^v?\d+\.\d+\.\d+([-.+][A-Za-z0-9_.-]+)?$", text))


def parse_json_contract_from_code_block(block: dict[str, Any]) -> dict[str, Any]:
    """
    从 Notion code block 中解析 JSON contract。

    要求：
        block 类型是 code；
        language 最好是 json；
        内容必须是合法 JSON。

    注意：
        JSON 里不能写 // 或 # 注释。
    """

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
    """
    在版本块里找到状态行。

    支持：
        状态：pending
        状态: pending
        status: pending
    """

    for block in blocks:
        text = block_text(block).strip()
        if text.startswith("状态：") or text.startswith("状态:"):
            return block
        if text.lower().startswith("status:"):
            return block
    return None


def find_contract_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    在版本块里找到 JSON contract code block。

    判断标准：
        - block 类型是 code；
        - language 是 json；
        - 内容可以 json.loads；
        - JSON 里有 version、image、tag。
    """

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
    """
    找到 GitHub Action 反馈标题。

    当前 precheck 脚本只读取它的 block id，真正写回由 docker_notion_writeback.py 负责。
    """

    for block in blocks:
        if block.get("type") not in {"heading_3", "heading_2", "paragraph"}:
            continue
        text = block_text(block).strip()
        if "GitHub Action 反馈" in text or "GitHub Actions 反馈" in text:
            return block
    return None


def find_version_sections(page_blocks: list[dict[str, Any]]) -> list[VersionSection]:
    """
    把 Notion 页面切分成多个版本块。

    每个 heading_2 版本标题到下一个 heading_2 之间，视为一个版本块。
    """

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
    """
    选择本次要检查的 Notion 版本块。

    优先级：
        1. 如果 workflow 传了 DOCKER_ENV_VERSION，则使用指定版本；
        2. 否则选择最后一个 status=pending 的版本块；
        3. 如果没有 pending，则选择最后一个版本块。
    """

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


# ============================================================
# JSON contract 校验
# ============================================================

def validate_contract(contract: dict[str, Any], heading_version: str) -> list[str]:
    """
    校验 Notion JSON contract 的基本结构。

    这里只检查字段结构和明显错误。
    更深入的文件检查、package_changes 检查会在后续函数里做。
    """

    issues: list[str] = []

    for field in REQUIRED_CONTRACT_FIELDS:
        if field not in contract or contract[field] == "":
            issues.append(f"Missing required contract field: `{field}`")

    # previous 是必需字段，但允许为 null。
    # 这是为了让机器明确知道：这是第一个版本，还是需要和上一版本比较。
    if "previous" not in contract:
        issues.append(
            "Missing required contract field: `previous`. "
            "Use `null` for the first Docker environment version."
        )

    # JSON 里的 version 要和 Notion 标题一致。
    if "version" in contract:
        contract_version = normalize_version(str(contract["version"]))
        if contract_version != normalize_version(heading_version):
            issues.append(
                f"Contract version `{contract['version']}` does not match heading `v{heading_version}`."
            )

    # 当前 workflow 只处理 environment image。
    if str(contract.get("image_type", "")).strip() != "environment":
        issues.append("`image_type` should be `environment` for the current workflow.")

    # image 不能带 tag。
    image = str(contract.get("image", "")).strip()
    if image and image_has_embedded_tag(image):
        issues.append("`image` should not include a tag. Put the tag in the `tag` field.")

    # previous 可以是 null，也可以是对象。
    previous = contract.get("previous")
    if previous is not None:
        if not isinstance(previous, dict):
            issues.append("`previous` must be an object or null.")
        else:
            for field in ["version", "image", "tag"]:
                if not previous.get(field):
                    issues.append(f"Missing required previous field: `previous.{field}`")

            previous_image = str(previous.get("image", "")).strip()
            if previous_image and image_has_embedded_tag(previous_image):
                issues.append("`previous.image` should not include a tag. Put the tag in `previous.tag`.")

    # package_changes 必须包含 added / removed / updated 三个数组。
    package_changes = contract.get("package_changes")
    if not isinstance(package_changes, dict):
        issues.append("`package_changes` must be an object with `added`, `removed`, and `updated` arrays.")
    else:
        for key in ["added", "removed", "updated"]:
            if key not in package_changes:
                issues.append(f"`package_changes.{key}` is required and should be an array.")
            elif not isinstance(package_changes[key], list):
                issues.append(f"`package_changes.{key}` should be an array.")

    return issues


# ============================================================
# Docker Hub manifest 检查
# ============================================================

def dockerhub_repository_path(image: str) -> str:
    """
    把 image 转成 Docker Hub registry API 使用的 repository path。

    例如：
        bioforge/pepclaw -> bioforge/pepclaw
        python           -> library/python
    """

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
    """
    检查 Docker Hub 上 image:tag 是否已经存在。

    返回：
        (True,  "Docker Hub tag exists.")
        (False, "Docker Hub tag does not exist.")

    如果 registry API 返回异常状态，会把错误信息作为 message 返回。
    """

    repo_path = dockerhub_repository_path(image)

    username = os.getenv("DOCKERHUB_USERNAME")
    token_or_password = os.getenv("DOCKERHUB_TOKEN")

    auth = None
    if username and token_or_password:
        auth = (username, token_or_password)

    # 先向 Docker registry auth 服务申请 pull token。
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

    # 用 HEAD manifest 判断 tag 是否存在。
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


# ============================================================
# Dockerfile / requirements.txt / compose 文件检查
# ============================================================

def extract_dockerfile_base_images(dockerfile_text: str) -> list[str]:
    """
    从 Dockerfile 中提取所有 FROM 镜像。

    支持多阶段构建，例如：
        FROM python:3.11-slim AS builder
        FROM python:3.11-slim
    """

    images: list[str] = []

    for line in dockerfile_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        match = re.match(r"^FROM\s+([^\s]+)", line, flags=re.IGNORECASE)
        if match:
            images.append(match.group(1))

    return images


def strip_inline_comment(line: str) -> str:
    """
    去掉 requirements 行中的简单行内注释。

    例如：
        docling>=0.5.0  # PDF parser

    转成：
        docling>=0.5.0
    """

    if " #" in line:
        return line.split(" #", 1)[0].rstrip()
    return line


def is_requirement_option(line: str) -> bool:
    """判断 requirements.txt 中某一行是否是 pip 选项，而不是包依赖。"""

    return line.startswith(REQUIREMENT_OPTION_PREFIXES)


def parse_requirement_name(requirement: str) -> str | None:
    """
    从一条 requirement 字符串中解析包名。

    支持：
        docling
        docling>=0.5.0
        docling==0.5.0
        docling[all]>=0.5.0
        docling @ https://...

    对 git+、http://、https:// 这类复杂依赖，当前先不解析。
    """

    line = strip_inline_comment(requirement.strip())
    if not line or line.startswith("#") or is_requirement_option(line):
        return None

    if line.startswith(("git+", "http://", "https://")):
        return None

    direct_match = re.match(r"^\s*([A-Za-z0-9_.-]+)\s*(?:\[[^\]]+\])?\s+@", line)
    if direct_match:
        return direct_match.group(1)

    normal_match = re.match(
        r"^\s*([A-Za-z0-9_.-]+)\s*(?:\[[^\]]+\])?\s*(?:===|==|~=|!=|<=|>=|<|>|$)",
        line,
    )
    if normal_match:
        return normal_match.group(1)

    return None


def parse_requirements_text(text: str) -> tuple[dict[str, RequirementEntry], list[str]]:
    """
    解析 requirements 文本。

    返回：
        entries:
            key 是 normalized package name；
            value 是 RequirementEntry。

        unparsed:
            无法解析的依赖行。

    注意：
        如果同一个包出现多次，后面的会覆盖前面的。
    """

    entries: dict[str, RequirementEntry] = {}
    unparsed: list[str] = []

    for raw_line in text.splitlines():
        line = strip_inline_comment(raw_line.strip())
        if not line or line.startswith("#"):
            continue

        if is_requirement_option(line):
            continue

        name = parse_requirement_name(line)
        if not name:
            unparsed.append(line)
            continue

        normalized_name = normalize_package_name(name)
        entries[normalized_name] = RequirementEntry(
            name=name,
            normalized_name=normalized_name,
            requirement=line,
        )

    return entries, unparsed


def find_unpinned_requirements(requirements_text: str) -> list[str]:
    """
    找出未固定版本的依赖。

    当前判断比较简单：
        包含 == 或 @ 的认为已固定；
        其他认为 unpinned。

    例如：
        docling           -> unpinned
        docling>=0.5.0    -> unpinned
        docling==0.5.0    -> pinned
    """

    unpinned: list[str] = []

    for raw_line in requirements_text.splitlines():
        line = strip_inline_comment(raw_line.strip())
        if not line or line.startswith("#"):
            continue

        if is_requirement_option(line):
            continue

        if "==" in line or " @ " in line:
            continue

        unpinned.append(line)

    return unpinned


def validate_local_files(contract: dict[str, Any]) -> tuple[list[str], list[str], dict[str, Any]]:
    """
    检查本地 Docker 环境相关文件。

    主要检查：
        1. Dockerfile 是否存在；
        2. docker-compose.yml 是否存在；
        3. requirements.txt 是否存在；
        4. .dockerignore 是否存在；
        5. Dockerfile FROM 是否包含 Notion base_image；
        6. Dockerfile 最终镜像是否保留 /app/requirements.txt；
        7. compose 是否使用 DOCKER_IMAGE / DOCKER_TAG；
        8. requirements 是否符合 package_policy。
    """

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

    requirements_text = ""

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

        # 这里先作为 warning，而不是 issue。
        # 因为旧镜像可能还没有这个文件，但从现在起建议加上。
        if "COPY requirements.txt /app/requirements.txt" not in dockerfile_text:
            warnings.append(
                "Dockerfile should copy `requirements.txt` into the final image as "
                "`/app/requirements.txt`, so future prechecks can compare direct dependencies."
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

        current_requirements, current_unparsed = parse_requirements_text(requirements_text)
        details["current_requirements"] = {
            name: entry.requirement for name, entry in sorted(current_requirements.items())
        }
        details["current_unparsed_requirements"] = current_unparsed

        if current_unparsed:
            warnings.append(
                "Some requirement lines could not be parsed for package-change validation: "
                + ", ".join(f"`{item}`" for item in current_unparsed[:20])
            )

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

    # 计算配置 hash。
    hash_paths = [dockerfile_path, compose_path, requirements_path, dockerignore_path]
    details["docker_config_hash"] = compute_config_hash(hash_paths)

    file_hashes: dict[str, str] = {}
    for path in hash_paths:
        if path.exists():
            file_hashes[str(path.relative_to(ROOT))] = sha256_file(path)

    details["file_hashes"] = file_hashes

    # 后续 previous 依赖差异检查需要当前 requirements 文本。
    details["requirements_text"] = requirements_text

    return issues, warnings, details


# ============================================================
# Docker CLI 相关函数：拉取 previous 镜像并读取依赖
# ============================================================

def run_command(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = False,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """
    执行命令行命令。

    这里用于：
        docker login
        docker pull
        docker run
    """

    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        timeout=timeout,
    )


def docker_login_if_credentials() -> tuple[bool, str]:
    """
    如果提供了 Docker Hub 账号和 token，则先 docker login。

    GitHub Actions 里：
        DOCKERHUB_USERNAME 实际由 secrets.DOCKER_USERNAME 映射过来；
        DOCKERHUB_TOKEN 来自 secrets.DOCKERHUB_TOKEN。

    如果没有凭证，则尝试匿名 pull。
    """

    username = os.getenv("DOCKERHUB_USERNAME")
    token = os.getenv("DOCKERHUB_TOKEN")

    if not username or not token:
        return False, "Docker Hub credentials not provided; will try anonymous pull."

    result = run_command(
        ["docker", "login", "-u", username, "--password-stdin"],
        input_text=token,
        timeout=60,
    )

    if result.returncode != 0:
        return False, f"Docker login failed: {result.stderr.strip()[:500]}"

    return True, "Docker login succeeded."


def docker_pull(image: str) -> tuple[bool, str]:
    """拉取 Docker 镜像。"""

    result = run_command(["docker", "pull", image], timeout=600)

    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()

    return True, result.stdout.strip()


def docker_run_capture(
    image: str,
    command: list[str],
    *,
    timeout: int = 120,
) -> tuple[bool, str, str]:
    """
    在 Docker 镜像里执行命令并捕获 stdout/stderr。

    例如：
        docker run --rm bioforge/pepclaw:0.0.9 cat /app/requirements.txt
    """

    result = run_command(["docker", "run", "--rm", image, *command], timeout=timeout)
    return result.returncode == 0, result.stdout, result.stderr


def get_previous_requirements_from_image(
    previous_full_image: str,
) -> tuple[str, dict[str, Any], list[str], list[str]]:
    """
    从上一版 Docker 镜像中读取依赖信息。

    优先级：
        1. 读取 /app/requirements.txt
           这是直接依赖，最适合和当前 requirements.txt 做严格对比。

        2. 如果 /app/requirements.txt 不存在，则执行 python -m pip freeze
           这是最终安装结果，会包含传递依赖。
           因此只能做较宽松的校验，避免误报。

    返回：
        previous_requirements_text
        source_details
        issues
        warnings
    """

    issues: list[str] = []
    warnings: list[str] = []

    source_details: dict[str, Any] = {
        "previous_full_image": previous_full_image,
        "source": "",
        "docker_login": "",
        "docker_pull": "",
    }

    logged_in, login_message = docker_login_if_credentials()
    source_details["docker_login"] = login_message
    if not logged_in and "failed" in login_message.lower():
        warnings.append(login_message)

    pulled, pull_message = docker_pull(previous_full_image)
    source_details["docker_pull"] = pull_message[:2000]

    if not pulled:
        issues.append(
            f"Failed to pull previous Docker image `{previous_full_image}`: {pull_message[:800]}"
        )
        return "", source_details, issues, warnings

    # 优先读取上一版镜像中的 /app/requirements.txt。
    ok, stdout, stderr = docker_run_capture(
        previous_full_image,
        ["sh", "-lc", "cat /app/requirements.txt"],
        timeout=120,
    )

    if ok and stdout.strip():
        source_details["source"] = "requirements"
        source_details["path"] = "/app/requirements.txt"
        source_details["requirements_hash"] = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        return stdout, source_details, issues, warnings

    # 如果上一版镜像没有 /app/requirements.txt，则退回 pip freeze。
    warnings.append(
        f"Could not read `/app/requirements.txt` from previous image `{previous_full_image}`. "
        "Falling back to `python -m pip freeze`; this may include transitive dependencies."
    )
    source_details["requirements_read_error"] = stderr.strip()[:1000]

    ok, stdout, stderr = docker_run_capture(
        previous_full_image,
        ["python", "-m", "pip", "freeze"],
        timeout=120,
    )

    if ok and stdout.strip():
        source_details["source"] = "pip_freeze"
        source_details["requirements_hash"] = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        return stdout, source_details, issues, warnings

    issues.append(
        f"Could not read requirements or pip freeze from previous image `{previous_full_image}`. "
        f"Last error: {stderr.strip()[:800]}"
    )
    source_details["pip_freeze_error"] = stderr.strip()[:1000]

    return "", source_details, issues, warnings


# ============================================================
# package_changes 校验
# ============================================================

def get_item_text(item: dict[str, Any], key: str) -> str:
    """
    安全读取 package_changes 中某个字段的字符串值。

    None 会转为空字符串。
    """

    value = item.get(key)
    if value is None:
        return ""
    return str(value).strip()


def validate_package_change_item_shape(package_changes: dict[str, Any]) -> list[str]:
    """
    校验 package_changes 内部每一项的字段结构。

    规则：
        added:
            必填 name, requirement

        removed:
            必填 name, requirement

        updated:
            必填 name, from, to
    """

    issues: list[str] = []

    for item in package_changes.get("added", []):
        if not isinstance(item, dict):
            issues.append("Each item in `package_changes.added` must be an object.")
            continue
        for field in ["name", "requirement"]:
            if not get_item_text(item, field):
                issues.append(f"`package_changes.added` item is missing required field `{field}`.")

    for item in package_changes.get("removed", []):
        if not isinstance(item, dict):
            issues.append("Each item in `package_changes.removed` must be an object.")
            continue
        for field in ["name", "requirement"]:
            if not get_item_text(item, field):
                issues.append(f"`package_changes.removed` item is missing required field `{field}`.")

    for item in package_changes.get("updated", []):
        if not isinstance(item, dict):
            issues.append("Each item in `package_changes.updated` must be an object.")
            continue
        for field in ["name", "from", "to"]:
            if not get_item_text(item, field):
                issues.append(f"`package_changes.updated` item is missing required field `{field}`.")

    return issues


def validate_package_changes(
    contract: dict[str, Any],
    current_requirements: dict[str, RequirementEntry],
    previous_requirements: dict[str, RequirementEntry],
    *,
    previous_source: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """
    校验 package_changes 是否和真实依赖差异一致。

    输入：
        current_requirements:
            当前 PR 中 requirements.txt 解析结果。

        previous_requirements:
            上一版镜像中的 /app/requirements.txt 或 pip freeze 解析结果。

        previous_source:
            requirements 或 pip_freeze。

    严格模式：
        如果 previous_source == "requirements"：
            说明上一版有直接依赖文件，可以严格比较 added/removed/updated。

    宽松模式：
        如果 previous_source == "pip_freeze"：
            pip freeze 包含传递依赖，不适合严格判断所有增删改。
            此时只校验声明项，不做完整 undeclared diff 阻断。
    """

    issues: list[str] = []
    warnings: list[str] = []

    package_changes = contract.get("package_changes", {})
    if not isinstance(package_changes, dict):
        return ["`package_changes` must be an object."], warnings, {}

    issues.extend(validate_package_change_item_shape(package_changes))

    declared_added: set[str] = set()
    declared_removed: set[str] = set()
    declared_updated: set[str] = set()

    added_details: list[dict[str, Any]] = []
    removed_details: list[dict[str, Any]] = []
    updated_details: list[dict[str, Any]] = []

    # ----------------------------
    # 校验 added
    # ----------------------------
    for item in package_changes.get("added", []):
        if not isinstance(item, dict):
            continue

        raw_name = get_item_text(item, "name")
        requirement = get_item_text(item, "requirement")
        normalized_name = normalize_package_name(raw_name)
        declared_added.add(normalized_name)

        current_entry = current_requirements.get(normalized_name)
        previous_entry = previous_requirements.get(normalized_name)

        added_details.append(
            {
                "name": raw_name,
                "requirement": requirement,
                "current_requirement": current_entry.requirement if current_entry else "",
                "previous_requirement": previous_entry.requirement if previous_entry else "",
            }
        )

        if not current_entry:
            issues.append(
                f"Declared added package `{raw_name}` is not found in current requirements.txt."
            )
        elif current_entry.requirement != requirement:
            issues.append(
                f"Declared added package `{raw_name}` has requirement `{requirement}`, "
                f"but current requirements.txt has `{current_entry.requirement}`."
            )

        if previous_entry:
            issues.append(
                f"Declared added package `{raw_name}` already exists in previous environment "
                f"as `{previous_entry.requirement}`. Use `updated` if its version constraint changed."
            )

    # ----------------------------
    # 校验 removed
    # ----------------------------
    for item in package_changes.get("removed", []):
        if not isinstance(item, dict):
            continue

        raw_name = get_item_text(item, "name")
        requirement = get_item_text(item, "requirement")
        normalized_name = normalize_package_name(raw_name)
        declared_removed.add(normalized_name)

        current_entry = current_requirements.get(normalized_name)
        previous_entry = previous_requirements.get(normalized_name)

        removed_details.append(
            {
                "name": raw_name,
                "requirement": requirement,
                "current_requirement": current_entry.requirement if current_entry else "",
                "previous_requirement": previous_entry.requirement if previous_entry else "",
            }
        )

        if current_entry:
            issues.append(
                f"Declared removed package `{raw_name}` still exists in current requirements.txt "
                f"as `{current_entry.requirement}`."
            )

        if not previous_entry:
            issues.append(
                f"Declared removed package `{raw_name}` is not found in previous environment."
            )
        elif previous_source == "requirements" and previous_entry.requirement != requirement:
            issues.append(
                f"Declared removed package `{raw_name}` has previous requirement `{requirement}`, "
                f"but previous requirements has `{previous_entry.requirement}`."
            )
        elif previous_source == "pip_freeze" and previous_entry.requirement != requirement:
            warnings.append(
                f"Declared removed package `{raw_name}` uses requirement `{requirement}`, "
                f"but previous pip freeze has `{previous_entry.requirement}`. "
                "This is only a warning because previous source is pip freeze."
            )

        replacement = item.get("replacement")
        if replacement:
            replacement_name = parse_requirement_name(str(replacement))
            if replacement_name:
                replacement_normalized = normalize_package_name(replacement_name)
                if replacement_normalized not in current_requirements:
                    issues.append(
                        f"Replacement `{replacement}` for removed package `{raw_name}` "
                        "is not found in current requirements.txt."
                    )

    # ----------------------------
    # 校验 updated
    # ----------------------------
    for item in package_changes.get("updated", []):
        if not isinstance(item, dict):
            continue

        raw_name = get_item_text(item, "name")
        from_requirement = get_item_text(item, "from")
        to_requirement = get_item_text(item, "to")
        normalized_name = normalize_package_name(raw_name)
        declared_updated.add(normalized_name)

        current_entry = current_requirements.get(normalized_name)
        previous_entry = previous_requirements.get(normalized_name)

        updated_details.append(
            {
                "name": raw_name,
                "from": from_requirement,
                "to": to_requirement,
                "current_requirement": current_entry.requirement if current_entry else "",
                "previous_requirement": previous_entry.requirement if previous_entry else "",
            }
        )

        if not current_entry:
            issues.append(
                f"Declared updated package `{raw_name}` is not found in current requirements.txt."
            )
        elif current_entry.requirement != to_requirement:
            issues.append(
                f"Declared updated package `{raw_name}` has target `{to_requirement}`, "
                f"but current requirements.txt has `{current_entry.requirement}`."
            )

        if not previous_entry:
            issues.append(
                f"Declared updated package `{raw_name}` is not found in previous environment."
            )
        elif previous_source == "requirements" and previous_entry.requirement != from_requirement:
            issues.append(
                f"Declared updated package `{raw_name}` has previous requirement `{from_requirement}`, "
                f"but previous requirements has `{previous_entry.requirement}`."
            )
        elif previous_source == "pip_freeze" and previous_entry.requirement != from_requirement:
            warnings.append(
                f"Declared updated package `{raw_name}` uses previous requirement `{from_requirement}`, "
                f"but previous pip freeze has `{previous_entry.requirement}`. "
                "This is only a warning because previous source is pip freeze."
            )

    # 同一个包不能同时出现在 added / removed / updated 多个分类。
    duplicate_declared = (
        declared_added & declared_removed
        | declared_added & declared_updated
        | declared_removed & declared_updated
    )
    if duplicate_declared:
        issues.append(
            "A package should appear in only one package_changes category: "
            + ", ".join(f"`{name}`" for name in sorted(duplicate_declared))
        )

    # 计算真实差异。
    actual_added = set(current_requirements) - set(previous_requirements)
    actual_removed = set(previous_requirements) - set(current_requirements)
    actual_updated = {
        name
        for name in set(current_requirements) & set(previous_requirements)
        if current_requirements[name].requirement != previous_requirements[name].requirement
    }

    # 如果上一版来源是 /app/requirements.txt，可以严格检查有没有漏声明。
    if previous_source == "requirements":
        undeclared_added = actual_added - declared_added
        undeclared_removed = actual_removed - declared_removed
        undeclared_updated = actual_updated - declared_updated

        overdeclared_added = declared_added - actual_added
        overdeclared_removed = declared_removed - actual_removed
        overdeclared_updated = declared_updated - actual_updated

        if undeclared_added:
            issues.append(
                "Current requirements.txt has packages newly added from previous version "
                "but not declared in `package_changes.added`: "
                + ", ".join(f"`{current_requirements[name].requirement}`" for name in sorted(undeclared_added))
            )

        if undeclared_removed:
            issues.append(
                "Previous requirements has packages removed in current version "
                "but not declared in `package_changes.removed`: "
                + ", ".join(f"`{previous_requirements[name].requirement}`" for name in sorted(undeclared_removed))
            )

        if undeclared_updated:
            issues.append(
                "Requirements changed version constraints but not declared in `package_changes.updated`: "
                + ", ".join(
                    f"`{previous_requirements[name].requirement}` -> `{current_requirements[name].requirement}`"
                    for name in sorted(undeclared_updated)
                )
            )

        if overdeclared_added:
            issues.append(
                "`package_changes.added` declares packages that are not actual additions: "
                + ", ".join(f"`{name}`" for name in sorted(overdeclared_added))
            )

        if overdeclared_removed:
            issues.append(
                "`package_changes.removed` declares packages that are not actual removals: "
                + ", ".join(f"`{name}`" for name in sorted(overdeclared_removed))
            )

        if overdeclared_updated:
            issues.append(
                "`package_changes.updated` declares packages that are not actual version-constraint updates: "
                + ", ".join(f"`{name}`" for name in sorted(overdeclared_updated))
            )
    else:
        warnings.append(
            "Previous dependency source is `pip_freeze`, not `/app/requirements.txt`; "
            "strict undeclared added/removed/updated validation is skipped to avoid false positives from transitive dependencies."
        )

    details = {
        "previous_source": previous_source,
        "declared": {
            "added": sorted(declared_added),
            "removed": sorted(declared_removed),
            "updated": sorted(declared_updated),
        },
        "actual": {
            "added": sorted(actual_added),
            "removed": sorted(actual_removed),
            "updated": sorted(actual_updated),
        },
        "items": {
            "added": added_details,
            "removed": removed_details,
            "updated": updated_details,
        },
    }

    return issues, warnings, details


def validate_previous_dependency_changes(
    contract: dict[str, Any],
    current_requirements_text: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """
    根据 contract.previous 校验当前版本相对上一版本的包变化。

    如果 previous 为 null：
        跳过上一版本差异校验。

    如果 previous 不为 null：
        1. 拉取 previous.image:previous.tag；
        2. 读取上一版 /app/requirements.txt；
        3. 如果读不到，退回 pip freeze；
        4. 对比 package_changes。
    """

    issues: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {
        "enabled": False,
        "previous": contract.get("previous"),
    }

    current_requirements, current_unparsed = parse_requirements_text(current_requirements_text)
    details["current_requirements"] = {
        name: entry.requirement for name, entry in sorted(current_requirements.items())
    }
    details["current_unparsed"] = current_unparsed

    previous = contract.get("previous")

    if previous is None:
        warnings.append(
            "`previous` is null. Previous-image dependency diff validation is skipped."
        )
        details["enabled"] = False
        return issues, warnings, details

    if not isinstance(previous, dict):
        issues.append("`previous` must be an object or null.")
        return issues, warnings, details

    previous_image = str(previous.get("image", "")).strip()
    previous_tag = str(previous.get("tag", "")).strip()
    if not previous_image or not previous_tag:
        issues.append("`previous.image` and `previous.tag` are required when `previous` is not null.")
        return issues, warnings, details

    previous_full_image = full_image_name(previous_image, previous_tag)
    details["enabled"] = True
    details["previous_full_image"] = previous_full_image

    (
        previous_requirements_text,
        source_details,
        previous_issues,
        previous_warnings,
    ) = get_previous_requirements_from_image(previous_full_image)

    details["previous_source_details"] = source_details
    issues.extend(previous_issues)
    warnings.extend(previous_warnings)

    if not previous_requirements_text:
        return issues, warnings, details

    previous_requirements, previous_unparsed = parse_requirements_text(previous_requirements_text)
    previous_source = str(source_details.get("source") or "unknown")

    details["previous_requirements"] = {
        name: entry.requirement for name, entry in sorted(previous_requirements.items())
    }
    details["previous_unparsed"] = previous_unparsed

    if previous_unparsed:
        warnings.append(
            "Some previous dependency lines could not be parsed: "
            + ", ".join(f"`{item}`" for item in previous_unparsed[:20])
        )

    change_issues, change_warnings, change_details = validate_package_changes(
        contract,
        current_requirements,
        previous_requirements,
        previous_source=previous_source,
    )
    issues.extend(change_issues)
    warnings.extend(change_warnings)
    details["package_change_validation"] = change_details

    return issues, warnings, details


# ============================================================
# GitHub Actions 输出和 PR comment
# ============================================================

def write_github_output(name: str, value: str | int | bool) -> None:
    """
    写入 GitHub Actions output。

    后续 job 可以通过：
        needs.notion_precheck.outputs.full_image
    读取这里输出的值。
    """

    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    normalized = str(value).lower() if isinstance(value, bool) else str(value)

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"{name}={normalized}\n")


def append_step_summary(markdown: str) -> None:
    """
    写入 GitHub Actions step summary。

    这个内容会显示在 GitHub Actions run 页面。
    """

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(markdown)
        f.write("\n")


def write_docker_env(image: str, tag: str) -> None:
    """
    生成 .docker_review/docker.env。

    该文件可用于 docker compose：
        DOCKER_IMAGE=bioforge/pepclaw
        DOCKER_TAG=0.1.0
    """

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    env_path = REVIEW_DIR / "docker.env"
    env_path.write_text(
        f"DOCKER_IMAGE={clean_image_name(image)}\nDOCKER_TAG={tag}\n",
        encoding="utf-8",
    )


def render_comment(result: dict[str, Any]) -> str:
    """
    渲染 PR comment 内容。

    这个 comment 会被 docker-push.yml 中的 github-script 写入 PR。
    """

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

    previous_details = result.get("details", {}).get("previous_dependency_diff", {})
    previous_enabled = previous_details.get("enabled")
    previous_full_image = previous_details.get("previous_full_image", "")

    lines: list[str] = [
        COMMENT_MARKER,
        f"# {title}",
        "",
        f"Status: **{status}**",
        "",
        "This check compares the Notion Docker environment record with repository Docker configuration and package-change declarations.",
        "",
        "## Summary",
        "",
        f"- Version: `v{result.get('version', '')}`",
        f"- Image: `{result.get('full_image', '')}`",
        f"- Precheck passed: **{str(passed).lower()}**",
        f"- Docker Hub tag exists: **{str(tag_exists).lower()}**",
        f"- Should build: **{str(should_build).lower()}**",
        f"- Docker config hash: `{result.get('docker_config_hash', '')}`",
        f"- Previous dependency diff enabled: **{str(bool(previous_enabled)).lower()}**",
    ]

    if previous_full_image:
        lines.append(f"- Previous image: `{previous_full_image}`")

    lines.append("")

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

    package_validation = previous_details.get("package_change_validation", {})
    if package_validation:
        actual = package_validation.get("actual", {})
        declared = package_validation.get("declared", {})
        lines.extend(
            [
                "## Package changes",
                "",
                f"- Declared added: `{', '.join(declared.get('added', [])) or 'none'}`",
                f"- Declared removed: `{', '.join(declared.get('removed', [])) or 'none'}`",
                f"- Declared updated: `{', '.join(declared.get('updated', [])) or 'none'}`",
                f"- Actual added: `{', '.join(actual.get('added', [])) or 'none'}`",
                f"- Actual removed: `{', '.join(actual.get('removed', [])) or 'none'}`",
                f"- Actual updated: `{', '.join(actual.get('updated', [])) or 'none'}`",
                "",
            ]
        )

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
    """把 precheck 结果写成 GitHub Actions outputs。"""

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


# ============================================================
# 主 precheck 流程
# ============================================================

def run_precheck() -> dict[str, Any]:
    """
    执行完整 precheck。

    这是本脚本最核心的函数。
    """

    # 1. 读取 GitHub Actions 传入的 Notion 配置。
    api_key = env_required("NOTION_API_KEY")
    page_id = env_required("NOTION_DOCKER_PAGE_ID")

    # 可选：强制指定 Notion 版本块。
    requested_version = os.getenv("DOCKER_ENV_VERSION") or os.getenv("DOCKER_VERSION")

    # 2. 从 Notion 页面读取所有顶层 blocks，并切分版本块。
    page_blocks = retrieve_all_children(page_id, api_key)
    sections = find_version_sections(page_blocks)
    section = choose_version_section(sections, requested_version)

    if not section.contract_block:
        raise PrecheckError(f"No JSON contract block found under version `v{section.version}`.")

    # 3. 解析 JSON contract。
    contract = parse_json_contract_from_code_block(section.contract_block)

    issues: list[str] = []
    warnings: list[str] = []

    # 4. 校验 JSON contract 基本结构。
    issues.extend(validate_contract(contract, section.version))

    # 5. 校验本地 Docker 配置文件。
    local_issues, local_warnings, local_details = validate_local_files(contract)
    issues.extend(local_issues)
    warnings.extend(local_warnings)

    # 6. 如果存在 requirements.txt，则进一步做 previous/package_changes 对比。
    requirements_text = str(local_details.get("requirements_text", "") or "")
    if requirements_text:
        previous_issues, previous_warnings, previous_details = validate_previous_dependency_changes(
            contract,
            requirements_text,
        )
        issues.extend(previous_issues)
        warnings.extend(previous_warnings)
        local_details["previous_dependency_diff"] = previous_details

    # 7. 读取当前目标 image/tag。
    image = str(contract.get("image", "")).strip()
    tag = str(contract.get("tag", "")).strip()
    full_image = full_image_name(image, tag) if image and tag else ""

    # 8. 检查当前目标 image:tag 是否已经存在于 Docker Hub。
    tag_exists = False
    dockerhub_check_message = ""

    if image and tag:
        tag_exists, dockerhub_check_message = dockerhub_tag_exists(image, tag)
        if dockerhub_check_message.startswith("Unexpected") or dockerhub_check_message.startswith("Failed"):
            issues.append(dockerhub_check_message)

    # 9. 根据 issues 决定 precheck 是否通过。
    passed = len(issues) == 0

    # 10. 如果 precheck 通过且目标 tag 不存在，则需要 build。
    should_build = bool(passed and not tag_exists)

    # 11. 汇总 result，后面会写入 precheck.json、comment.md、GitHub outputs。
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
    """
    脚本入口。

    即使 precheck 失败，也尽量生成：
        .docker_review/precheck.json
        .docker_review/comment.md

    这样 workflow 可以先评论、上传 artifact，再决定是否 fail。
    """

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    try:
        result = run_precheck()
    except Exception as exc:
        # 如果出现任何未捕获异常，也转成标准 result，
        # 避免 GitHub Action 完全没有产物可读。
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

    # 如果已经成功解析出 image/tag，就生成 docker.env。
    if result.get("image") and result.get("tag"):
        write_docker_env(str(result["image"]), str(result["tag"]))

    # 渲染 PR comment。
    comment = render_comment(result)

    # 写 precheck 结构化结果。
    (REVIEW_DIR / "precheck.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 写 PR comment markdown。
    (REVIEW_DIR / "comment.md").write_text(comment, encoding="utf-8")

    # 写 GitHub Actions outputs。
    write_outputs(result)

    # 写 GitHub Actions summary。
    append_step_summary(comment)

    # 默认不在脚本里直接 exit 1。
    # 是否 fail 由 docker-push.yml 的后续 step 控制。
    #
    # 如果本地调试想让脚本失败时直接返回非 0，
    # 可以设置 PRECHECK_EXIT_ON_FAIL=true。
    if os.getenv("PRECHECK_EXIT_ON_FAIL", "false").lower() == "true" and not result["passed"]:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
