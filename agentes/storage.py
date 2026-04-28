from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml


STORE_DIRNAME = ".agentes"
OBJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class StoreNotFound(RuntimeError):
    pass


class Store:
    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()
        self.root = self.project_root / STORE_DIRNAME

    @property
    def db_path(self) -> Path:
        return self.root / "agentes.db"

    @property
    def objects(self) -> Path:
        return self.root / "objects"

    @property
    def runs(self) -> Path:
        return self.objects / "runs"

    @property
    def traces(self) -> Path:
        return self.objects / "traces"

    @property
    def evidence(self) -> Path:
        return self.objects / "evidence"

    @property
    def experiences(self) -> Path:
        return self.objects / "experiences"

    @property
    def blobs(self) -> Path:
        return self.objects / "blobs"

    @property
    def skills(self) -> Path:
        return self.objects / "skills"

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.project_root).as_posix()


def find_store(start: Optional[Path] = None) -> Store:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / STORE_DIRNAME).is_dir():
            return Store(candidate)
    raise StoreNotFound("No .agentes store found. Run `agentes init` first.")


def store_for_init(path: Optional[Path] = None) -> Store:
    return Store((path or Path.cwd()).resolve())


def ensure_dirs(store: Store) -> None:
    dirs = [
        store.root,
        store.runs,
        store.traces,
        store.evidence,
        store.experiences,
        store.blobs / "stdout",
        store.blobs / "stderr",
        store.blobs / "diffs",
        store.skills,
        store.root / "inbox" / "unreviewed_experiences",
        store.root / "tmp",
    ]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)


def validate_object_id(object_id: str, label: str = "object id") -> str:
    if not OBJECT_ID_RE.fullmatch(object_id):
        raise ValueError(
            f"Invalid {label}: {object_id!r}. Use letters, numbers, '.', '_' or '-', "
            "and start with a letter or number."
        )
    return object_id


def safe_child(base: Path, object_id: str, label: str = "object id") -> Path:
    validate_object_id(object_id, label)
    base_resolved = base.resolve()
    target = (base / object_id).resolve()
    try:
        target.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: path escapes {base}") from exc
    return target


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML document must be a mapping: {path}")
    return data


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            data,
            fh,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def copy_blob(
    store: Store,
    source: Optional[Path],
    blob_kind: str,
    object_id: str,
    extension: str,
) -> Optional[str]:
    if source is None:
        return None
    src = source.expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"Blob source does not exist: {source}")
    target = store.blobs / blob_kind / f"{object_id}{extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    return store.rel(target)


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)


def flatten_text(value: Any) -> str:
    parts: list[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)
        else:
            parts.append(str(node))

    walk(value)
    return "\n".join(parts)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    return [str(value)]


def list_to_markdown(items: Iterable[str], empty: str = "None") -> str:
    values = [item for item in items if item]
    if not values:
        return f"- {empty}\n"
    return "".join(f"- {item}\n" for item in values)
