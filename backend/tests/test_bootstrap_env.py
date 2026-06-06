from pathlib import Path

from scripts._bootstrap_env import is_placeholder_database_url, resolve_database_url


def test_is_placeholder_database_url_detects_template_tokens() -> None:
    assert is_placeholder_database_url("postgresql://user:pass@host:port/db")
    assert (
        is_placeholder_database_url("postgresql://user:pass@db.example.com:5432/db")
        is False
    )
    assert is_placeholder_database_url("") is True


def test_resolve_database_url_prefers_local_env_over_production_template(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.production").write_text(
        'DATABASE_URL="postgresql://user:pass@host:port/railway"\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        'DATABASE_URL="postgresql://local:secret@127.0.0.1:5433/yetai"\n',
        encoding="utf-8",
    )

    resolved = resolve_database_url(backend_root=tmp_path)

    assert resolved == "postgresql://local:secret@127.0.0.1:5433/yetai"


def test_resolve_database_url_keeps_valid_shell_export(tmp_path: Path) -> None:
    (tmp_path / ".env.production").write_text(
        'DATABASE_URL="postgresql://user:pass@host:port/railway"\n',
        encoding="utf-8",
    )

    resolved = resolve_database_url(
        shell_database_url="postgresql://shell:secret@db.example.com:5432/prod",
        backend_root=tmp_path,
    )

    assert resolved == "postgresql://shell:secret@db.example.com:5432/prod"
