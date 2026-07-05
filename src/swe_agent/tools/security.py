from pathlib import Path


class SecurityError(Exception):
    ...


def resolve_safe_path(base_dir: str, user_path: str) -> Path:
    base = Path(base_dir).resolve()
    target = (base / user_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise SecurityError(
            f"Path '{user_path}' resolves outside workspace '{base_dir}'"
        )
    return target
