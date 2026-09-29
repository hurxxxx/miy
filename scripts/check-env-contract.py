#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from re import Pattern

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE_PARTS = [
    Path("apps/api/src/mty_api/core/settings.py"),
    Path("apps/worker/src/mty_worker/settings.py"),
]
SETTINGS_FILES = [ROOT / part for part in SETTINGS_FILE_PARTS]
DEPLOY_ENV_KEYS: frozenset[str] = frozenset(
    {
        "MTY_APP_BIND_HOST",
        "MTY_APP_FORWARDED_ALLOW_IPS",
        "MTY_APP_PORT",
        "MTY_APP_PUBLIC_URL",
    }
)

FORBIDDEN_ENV_KEYS = frozenset(
    {
        "MTY_LLM_LOCAL_API_KEY",
        "MTY_LLM_LOCAL_BASE_URL",
        "MTY_LLM_LOCAL_PROVIDER",
        "MTY_AI_DEFAULT_EXTERNAL_LLM_PROVIDER",
        "MTY_AI_MANAGER_ENABLED",
        "MTY_AI_MANAGER_HOSTED_TOOLS_ENABLED",
        "MTY_AI_MANAGER_MAX_LOOPS",
        "MTY_AI_MANAGER_MODEL",
        "MTY_AI_MANAGER_PROVIDER",
        "MTY_AI_MANAGER_STORE_RESPONSE",
        "MTY_AI_MANAGER_TRACE_SENSITIVE_DATA",
        "MTY_API_RECORDING_CHUNK_SECONDS",
        "MTY_CUSTOMER_CODE",
        "MTY_ENABLED_EXTENSION_APPS",
        "MTY_INFERENCE_GATEWAY_ASR_CONCURRENCY",
        "MTY_INFERENCE_GATEWAY_ASR_ENABLED",
        "MTY_INFERENCE_GATEWAY_ASR_LANGUAGE",
        "MTY_INFERENCE_GATEWAY_ASR_MAX_NEW_TOKENS",
        "MTY_INFERENCE_GATEWAY_ASR_MODEL",
        "MTY_INFERENCE_GATEWAY_ASR_PUBLIC_MODEL",
        "MTY_INFERENCE_GATEWAY_ASR_REVISION",
        "MTY_INFERENCE_GATEWAY_DEVICE",
        "MTY_INFERENCE_GATEWAY_DOCLING_CONCURRENCY",
        "MTY_INFERENCE_GATEWAY_DOCLING_ENABLED",
        "MTY_INFERENCE_GATEWAY_DTYPE",
        "MTY_INFERENCE_GATEWAY_EMBEDDING_BATCH_SIZE",
        "MTY_INFERENCE_GATEWAY_EMBEDDING_CONCURRENCY",
        "MTY_INFERENCE_GATEWAY_EMBEDDING_ENABLED",
        "MTY_INFERENCE_GATEWAY_EMBEDDING_MODEL",
        "MTY_INFERENCE_GATEWAY_EMBEDDING_QUERY_PROMPT_NAME",
        "MTY_INFERENCE_GATEWAY_EMBEDDING_REVISION",
        "MTY_INFERENCE_GATEWAY_HF_TOKEN_FILE",
        "MTY_INFERENCE_GATEWAY_HOST",
        "MTY_INFERENCE_GATEWAY_MAX_EMBEDDING_INPUTS",
        "MTY_INFERENCE_GATEWAY_MAX_RERANK_DOCUMENTS",
        "MTY_INFERENCE_GATEWAY_MAX_TEXT_CHARS",
        "MTY_INFERENCE_GATEWAY_MAX_UPLOAD_BYTES",
        "MTY_INFERENCE_GATEWAY_PORT",
        "MTY_INFERENCE_GATEWAY_RERANKER_BATCH_SIZE",
        "MTY_INFERENCE_GATEWAY_RERANKER_CONCURRENCY",
        "MTY_INFERENCE_GATEWAY_RERANKER_ENABLED",
        "MTY_INFERENCE_GATEWAY_RERANKER_MODEL",
        "MTY_INFERENCE_GATEWAY_RERANKER_REVISION",
        "MTY_RAG_UI_ENABLED",
        "GOOGLE_CLOUD_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
    }
)

FORBIDDEN_ENV_PATTERNS = [
    re.compile(r"\bOPEN_WORK_HUB_[A-Z0-9_]*\b"),
    re.compile(r"(?<!MTY_)\bLOCAL_AI_[A-Z0-9_]*\b"),
    re.compile(r"\bAI_AGENT_MAX_[A-Z0-9_]*\b"),
    re.compile(r"\bAI_TOOL_CALLING_ENABLED\b"),
    re.compile(r"\bOPENAI_API_KEY\b"),
    re.compile(r"\bANTHROPIC_API_KEY\b"),
    re.compile(r"\bGEMINI_API_KEY\b"),
    re.compile(r"\bCOHERE_API_KEY\b"),
    re.compile(r"\bHUGGINGFACE_HUB_TOKEN\b"),
    re.compile(r"\bMTY_REDIS_URL\b"),
]

SKIP_DIRS = {
    ".dev",
    ".git",
    ".mypy_cache",
    ".nx",
    ".rag-validation",
    ".ruff_cache",
    ".runtime",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
SKIP_FILE_PARTS = (".backup",)
SKIP_SETTINGS_KEYS = {"MTY_API_MTY_DESKTOP_UPDATE_DIRS"}
SOURCE_FILE_SUFFIXES = {
    ".py",
    ".sh",
    ".mjs",
    ".mts",
    ".ts",
    ".tsx",
    ".js",
    ".cjs",
    ".yml",
    ".yaml",
    ".json",
    ".md",
    ".template",
    ".conf",
    ".toml",
    ".ini",
}
SOURCE_FILE_NAMES = {".env", ".env.example"}


@dataclass(frozen=True)
class EnvFileContent:
    name: str
    path: Path
    text: str | None


@dataclass(frozen=True)
class TextFileContent:
    path: Path
    text: str | None
    label: str | None = None

    @property
    def display_name(self) -> str:
        return self.label or str(self.path)


@dataclass(frozen=True)
class ParsedEnvFile:
    name: str
    path: Path
    keys: tuple[str, ...]
    key_lines: Mapping[str, tuple[int, ...]]
    missing: bool = False

    @property
    def key_set(self) -> frozenset[str]:
        return frozenset(self.keys)

    @property
    def duplicate_lines(self) -> dict[str, tuple[int, ...]]:
        return {key: refs for key, refs in self.key_lines.items() if len(refs) > 1}


@dataclass(frozen=True)
class SettingsFileScan:
    path: Path
    keys: frozenset[str]
    missing: bool = False
    parse_error: str | None = None


@dataclass(frozen=True)
class ForbiddenTokenHit:
    path: str
    pattern: str


@dataclass(frozen=True)
class EnvContractFailure:
    code: str
    message: str


@dataclass(frozen=True)
class EnvContractReport:
    current_env_name: str
    env_files: tuple[ParsedEnvFile, ...]
    settings_files: tuple[SettingsFileScan, ...]
    forbidden_hits: tuple[ForbiddenTokenHit, ...]
    failures: tuple[EnvContractFailure, ...]
    deploy_env_keys: frozenset[str]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def env_by_name(self) -> dict[str, ParsedEnvFile]:
        return {env_file.name: env_file for env_file in self.env_files}

    @property
    def settings_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for settings_file in self.settings_files:
            keys.update(settings_file.keys)
        keys.update(self.deploy_env_keys)
        return frozenset(keys)

    def success_message(self) -> str:
        base = self.env_by_name.get(self.current_env_name)
        base_key_count = len(base.key_set) if base else 0
        env_names = ", ".join(sorted(self.env_by_name))
        return (
            f"ok: {base_key_count} keys across {env_names}; "
            f"{len(self.settings_keys)} settings keys covered"
        )


def current_env_name(root: Path) -> str:
    return root.name if root.name in {"dev", "prod"} else "current"


def env_file_paths(root: Path, env_name: str) -> dict[str, Path]:
    env_files = {
        env_name: root / ".env",
        "example": root / ".env.example",
    }
    local_env = root / ".env.local"
    if local_env.exists():
        env_files["local"] = local_env
    return env_files


def settings_file_paths(
    root: Path, parts: Iterable[Path] = SETTINGS_FILE_PARTS
) -> tuple[Path, ...]:
    return tuple(root / part for part in parts)


def parse_env_text(text: str) -> tuple[tuple[str, ...], dict[str, tuple[int, ...]]]:
    keys: list[str] = []
    lines: dict[str, list[int]] = {}
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if not key:
            continue
        keys.append(key)
        lines.setdefault(key, []).append(line_number)
    return tuple(keys), {key: tuple(refs) for key, refs in lines.items()}


def parse_env(env_file: EnvFileContent) -> ParsedEnvFile:
    if env_file.text is None:
        return ParsedEnvFile(
            name=env_file.name,
            path=env_file.path,
            keys=(),
            key_lines={},
            missing=True,
        )
    keys, lines = parse_env_text(env_file.text)
    return ParsedEnvFile(
        name=env_file.name,
        path=env_file.path,
        keys=keys,
        key_lines=lines,
    )


def string_literals(node: ast.AST) -> list[str]:
    values: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        values.append(node.value)
    for child in ast.iter_child_nodes(node):
        values.extend(string_literals(child))
    return values


def env_prefix_from_model_config(stmt: ast.stmt) -> str | None:
    value: ast.AST | None = None
    target_name: str | None = None
    if (
        isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
    ):
        target_name = stmt.targets[0].id
        value = stmt.value
    elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        target_name = stmt.target.id
        value = stmt.value
    if target_name != "model_config" or not isinstance(value, ast.Call):
        return None
    for keyword in value.keywords:
        if (
            keyword.arg == "env_prefix"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return None


def uppercase_field_name(name: str) -> str:
    return name.upper()


def settings_env_keys_from_tree(
    tree: ast.AST, *, skip_settings_keys: Iterable[str] = SKIP_SETTINGS_KEYS
) -> frozenset[str]:
    keys: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Settings":
            continue
        env_prefix = ""
        for stmt in node.body:
            env_prefix = env_prefix_from_model_config(stmt) or env_prefix
        for stmt in node.body:
            field_name: str | None = None
            value: ast.AST | None = None
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                field_name = stmt.target.id
                value = stmt.value
            elif (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            ):
                field_name = stmt.targets[0].id
                value = stmt.value
            if not field_name or field_name.startswith("_") or field_name == "model_config":
                continue
            aliases: list[str] = []
            if isinstance(value, ast.Call):
                for keyword in value.keywords:
                    if keyword.arg == "validation_alias":
                        aliases.extend(
                            literal
                            for literal in string_literals(keyword.value)
                            if re.fullmatch(r"[A-Z][A-Z0-9_]*", literal)
                        )
            if aliases:
                keys.update(aliases)
            elif env_prefix:
                keys.add(env_prefix + uppercase_field_name(field_name))
    return frozenset(keys - set(skip_settings_keys))


def settings_env_keys_from_text(
    text: str,
    *,
    filename: str = "<settings>",
    skip_settings_keys: Iterable[str] = SKIP_SETTINGS_KEYS,
) -> frozenset[str]:
    tree = ast.parse(text, filename=filename)
    return settings_env_keys_from_tree(tree, skip_settings_keys=skip_settings_keys)


def settings_env_keys(path: Path) -> frozenset[str]:
    return settings_env_keys_from_text(path.read_text(encoding="utf-8"), filename=str(path))


def scan_settings_file(
    settings_file: TextFileContent, *, skip_settings_keys: Iterable[str] = SKIP_SETTINGS_KEYS
) -> SettingsFileScan:
    if settings_file.text is None:
        return SettingsFileScan(settings_file.path, frozenset(), missing=True)
    try:
        keys = settings_env_keys_from_text(
            settings_file.text,
            filename=settings_file.display_name,
            skip_settings_keys=skip_settings_keys,
        )
    except SyntaxError as exc:
        return SettingsFileScan(
            settings_file.path,
            frozenset(),
            parse_error=f"{exc.__class__.__name__}: {exc.msg}",
        )
    return SettingsFileScan(settings_file.path, keys)


def should_scan_source_file(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if any(part in path.name for part in SKIP_FILE_PARTS):
        return False
    return path.suffix in SOURCE_FILE_SUFFIXES or path.name in SOURCE_FILE_NAMES


def source_files(
    root: Path = ROOT,
    *,
    excluded_paths: Iterable[Path] = (),
) -> list[Path]:
    resolved_root = root.resolve()
    excluded = {path.resolve() for path in excluded_paths}
    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # A linked runtime config outside the checkout is not repository source.
        if not path.resolve().is_relative_to(resolved_root):
            continue
        if path.resolve() in excluded:
            continue
        if should_scan_source_file(path, root):
            result.append(path)
    return result


def scan_forbidden_tokens(
    source_file_contents: Iterable[TextFileContent],
    forbidden_patterns: Iterable[Pattern[str]],
) -> tuple[ForbiddenTokenHit, ...]:
    patterns = tuple(forbidden_patterns)
    hits: list[ForbiddenTokenHit] = []
    for source_file in source_file_contents:
        if source_file.text is None:
            continue
        for pattern in patterns:
            if pattern.search(source_file.text):
                hits.append(
                    ForbiddenTokenHit(
                        path=source_file.display_name,
                        pattern=pattern.pattern,
                    )
                )
                break
    return tuple(hits)


def evaluate_env_contract(
    env_files: Iterable[EnvFileContent],
    settings_files: Iterable[TextFileContent],
    source_file_contents: Iterable[TextFileContent],
    current_env_name: str,
    forbidden_patterns: Iterable[Pattern[str]],
    forbidden_env_keys: Iterable[str] = (),
    runtime_config_keys: Iterable[str] = (),
    deploy_env_keys: Iterable[str] = DEPLOY_ENV_KEYS,
    skip_settings_keys: Iterable[str] = SKIP_SETTINGS_KEYS,
) -> EnvContractReport:
    public_keys = frozenset(runtime_config_keys)
    deploy_keys = frozenset(deploy_env_keys)
    parsed_env_files = tuple(parse_env(env_file) for env_file in env_files)
    settings_scans = tuple(
        scan_settings_file(settings_file, skip_settings_keys=skip_settings_keys)
        for settings_file in settings_files
    )
    forbidden_hits = scan_forbidden_tokens(source_file_contents, forbidden_patterns)

    failures: list[EnvContractFailure] = []
    env_by_name = {env_file.name: env_file for env_file in parsed_env_files}

    for env_file in parsed_env_files:
        if env_file.missing:
            failures.append(
                EnvContractFailure(
                    code="missing_env_file",
                    message=f"{env_file.name}: missing env file at {env_file.path}",
                )
            )
            continue
        duplicates = env_file.duplicate_lines
        if duplicates:
            failures.append(
                EnvContractFailure(
                    code="duplicate_env_key",
                    message=(
                        f"{env_file.name}: duplicate keys: "
                        f"{', '.join(sorted(duplicates))}"
                    ),
                )
            )

    base = env_by_name.get(current_env_name)
    if base is None:
        failures.append(
            EnvContractFailure(
                code="missing_current_env",
                message=f"{current_env_name}: current env file was not provided",
            )
        )
    elif not base.missing:
        for env_file in parsed_env_files:
            if env_file.name == current_env_name or env_file.missing:
                continue
            missing = sorted(base.key_set - env_file.key_set - public_keys)
            extra = sorted(env_file.key_set - base.key_set - public_keys)
            if missing or extra:
                failures.append(
                    EnvContractFailure(
                        code="env_keyset_mismatch",
                        message=(
                            f"{env_file.name}: keyset mismatch against {current_env_name}; "
                            f"missing={len(missing)} extra={len(extra)}"
                        ),
                    )
                )
            elif tuple(key for key in env_file.keys if key not in public_keys) != tuple(
                key for key in base.keys if key not in public_keys
            ):
                failures.append(
                    EnvContractFailure(
                        code="env_key_order_mismatch",
                        message=(
                            f"{env_file.name}: key order mismatch against "
                            f"{current_env_name}"
                        ),
                    )
                )

        forbidden_keys_present = sorted(base.key_set.intersection(forbidden_env_keys))
        if forbidden_keys_present:
            failures.append(
                EnvContractFailure(
                    code="forbidden_env_key",
                    message=(
                        "env files contain retired or externally owned keys: "
                        + ", ".join(forbidden_keys_present)
                    ),
                )
            )

    for settings_scan in settings_scans:
        if settings_scan.missing:
            failures.append(
                EnvContractFailure(
                    code="missing_settings_file",
                    message=f"{settings_scan.path}: missing settings file",
                )
            )
        elif settings_scan.parse_error:
            failures.append(
                EnvContractFailure(
                    code="invalid_settings_file",
                    message=f"{settings_scan.path}: {settings_scan.parse_error}",
                )
            )

    settings_keys: set[str] = set(deploy_keys)
    for settings_scan in settings_scans:
        settings_keys.update(settings_scan.keys)
    unknown_public_keys = public_keys - settings_keys
    if unknown_public_keys:
        failures.append(EnvContractFailure(
            code="unknown_runtime_config_key",
            message="runtime config contains keys without typed settings: "
            + ", ".join(sorted(unknown_public_keys)),
        ))
    if base is not None and not base.missing:
        missing_settings_keys = sorted(settings_keys - base.key_set - public_keys)
        if missing_settings_keys:
            failures.append(
                EnvContractFailure(
                    code="missing_settings_key",
                    message=(
                        "env files are missing settings keys: "
                        + ", ".join(missing_settings_keys)
                    ),
                )
            )

    for hit in forbidden_hits:
        failures.append(
            EnvContractFailure(
                code="forbidden_env_token",
                message=f"{hit.path}: forbidden env token {hit.pattern}",
            )
        )

    return EnvContractReport(
        current_env_name=current_env_name,
        env_files=parsed_env_files,
        settings_files=settings_scans,
        forbidden_hits=forbidden_hits,
        failures=tuple(failures),
        deploy_env_keys=deploy_keys,
    )


def relative_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_text_maybe(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def load_env_file(name: str, path: Path) -> EnvFileContent:
    return EnvFileContent(name=name, path=path, text=read_text_maybe(path))


def load_text_file(path: Path, *, root: Path = ROOT) -> TextFileContent:
    return TextFileContent(
        path=path,
        text=read_text_maybe(path),
        label=relative_label(path, root),
    )


def _checkout_report(
    root: Path,
    *,
    forbidden_env_keys: Iterable[str],
    settings_parts: Iterable[Path] = SETTINGS_FILE_PARTS,
    deploy_env_keys: Iterable[str] = DEPLOY_ENV_KEYS,
    skip_settings_keys: Iterable[str] = SKIP_SETTINGS_KEYS,
    scan_sources: bool,
) -> EnvContractReport:
    sys.path.insert(0, str(ROOT / "apps/api/src"))
    from mty_api.core.runtime_config import (
        RuntimeConfigError,
        load_runtime_document,
    )

    config_failure = None
    try:
        runtime_document = load_runtime_document(root)
        public_keys = frozenset(runtime_document["defaults"])
    except RuntimeConfigError as error:
        public_keys = frozenset()
        config_failure = EnvContractFailure(code="invalid_runtime_config", message=str(error))
    env_name = current_env_name(root)
    env_files = tuple(
        load_env_file(name, path) for name, path in env_file_paths(root, env_name).items()
    )
    settings_files = tuple(
        load_text_file(path, root=root) for path in settings_file_paths(root, settings_parts)
    )
    source_file_contents = tuple(
        load_text_file(path, root=root)
        for path in source_files(root, excluded_paths={Path(__file__).resolve()})
    ) if scan_sources else ()
    report = evaluate_env_contract(
        env_files=env_files,
        settings_files=settings_files,
        source_file_contents=source_file_contents,
        current_env_name=env_name,
        forbidden_patterns=FORBIDDEN_ENV_PATTERNS,
        forbidden_env_keys=forbidden_env_keys,
        runtime_config_keys=public_keys,
        deploy_env_keys=deploy_env_keys,
        skip_settings_keys=skip_settings_keys,
    )
    if config_failure is not None:
        report = replace(report, failures=(*report.failures, config_failure))
    return report


def _checkout_assignment(tree: ast.Module, name: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            if node.value is not None:
                return node.value
    raise ValueError(f"Missing {name} contract")


def _checkout_string_set(tree: ast.Module, name: str) -> frozenset[str]:
    expression = _checkout_assignment(tree, name)
    if isinstance(expression, ast.Call):
        if not (
            isinstance(expression.func, ast.Name)
            and expression.func.id == "frozenset"
            and len(expression.args) == 1
            and not expression.keywords
        ):
            raise ValueError(f"Invalid {name} contract")
        expression = expression.args[0]
    values = ast.literal_eval(expression)
    if not isinstance(values, (set, tuple, list)) or not all(isinstance(v, str) for v in values):
        raise ValueError(f"Invalid {name} contract")
    return frozenset(values)


def _checkout_settings_parts(tree: ast.Module) -> tuple[Path, ...]:
    expression = _checkout_assignment(tree, "SETTINGS_FILE_PARTS")
    if not isinstance(expression, (ast.List, ast.Tuple)) or not expression.elts:
        raise ValueError("Invalid SETTINGS_FILE_PARTS contract")
    parts: list[Path] = []
    for element in expression.elts:
        if not (
            isinstance(element, ast.Call)
            and isinstance(element.func, ast.Name)
            and element.func.id == "Path"
            and len(element.args) == 1
            and not element.keywords
            and isinstance(element.args[0], ast.Constant)
            and isinstance(element.args[0].value, str)
        ):
            raise ValueError("Invalid SETTINGS_FILE_PARTS contract")
        part = Path(element.args[0].value)
        if part.is_absolute() or ".." in part.parts or part.suffix != ".py":
            raise ValueError("Invalid SETTINGS_FILE_PARTS path")
        parts.append(part)
    return tuple(parts)


def _checkout_peer_contract(
    root: Path,
) -> tuple[tuple[Path, ...], frozenset[str], frozenset[str], frozenset[str]]:
    """Read the peer release's declared contract without executing its code."""
    tree = ast.parse((root / "scripts/check-env-contract.py").read_text())
    return (
        _checkout_settings_parts(tree),
        _checkout_string_set(tree, "DEPLOY_ENV_KEYS"),
        _checkout_string_set(tree, "FORBIDDEN_ENV_KEYS"),
        _checkout_string_set(tree, "SKIP_SETTINGS_KEYS"),
    )


def build_report(root: Path = ROOT) -> EnvContractReport:
    report = _checkout_report(root, forbidden_env_keys=FORBIDDEN_ENV_KEYS, scan_sources=True)
    # Dev can be ahead of production. Validate both, each against the template,
    # typed settings, public defaults and retired keys shipped in that checkout.
    for name in ("dev", "prod"):
        peer = root.parent / name
        if peer.resolve() == root.resolve() or not (peer / ".env").exists():
            continue
        try:
            settings_parts, deploy_env_keys, retired_keys, skip_settings_keys = _checkout_peer_contract(peer)
            peer_report = _checkout_report(
                peer,
                forbidden_env_keys=retired_keys,
                settings_parts=settings_parts,
                deploy_env_keys=deploy_env_keys,
                skip_settings_keys=skip_settings_keys,
                scan_sources=False,
            )
        except (OSError, ValueError, SyntaxError):
            failure = EnvContractFailure(
                code="invalid_peer_env_contract",
                message=f"{name}: missing or invalid checkout environment contract",
            )
            report = replace(report, failures=(*report.failures, failure))
            continue
        report = replace(
            report,
            env_files=(*report.env_files, *(replace(item, name=name if item.name == name else f"{name}.{item.name}")
                        for item in peer_report.env_files)),
            settings_files=(*report.settings_files, *peer_report.settings_files),
            deploy_env_keys=report.deploy_env_keys | peer_report.deploy_env_keys,
            failures=(*report.failures, *(replace(item, message=f"{name}: {item.message}")
                       for item in peer_report.failures)),
        )
    return report


def format_report_lines(report: EnvContractReport) -> tuple[str, ...]:
    if report.failures:
        return tuple(f"[env-contract] {failure.message}" for failure in report.failures)
    return (f"[env-contract] {report.success_message()}",)


def main() -> int:
    report = build_report(ROOT)

    if not report.ok:
        for line in format_report_lines(report):
            print(line, file=sys.stderr)
        return 1

    for line in format_report_lines(report):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
