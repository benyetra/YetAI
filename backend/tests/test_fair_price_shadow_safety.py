"""Shadow flags stay out of anything users or auto-pick can see."""

import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PATTERN = re.compile(
    r"fair_price_shadow_flags|FairPriceShadowFlag|fair_price\.shadow"
    r"|fair_price import shadow|fair_price\.grade|fair_price\.report"
)
ALLOWED = {
    "app/models/predictions_models.py",
    "app/services/fair_price/shadow.py",
    "app/services/fair_price/grade.py",
    "app/services/fair_price/report.py",
    "app/services/fair_price/weights.py",
    "app/tasks/fair_price.py",
    "app/celery_app.py",
    "app/services/model_review_service.py",
}


def _files(root, suffixes):
    return [
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix in suffixes
        and "node_modules" not in p.parts
        and "__pycache__" not in p.parts
    ]


def test_only_allowed_files_reference_shadow_flags():
    hits = set()
    for root, sfx in (
        (BACKEND / "app", {".py"}),
        (BACKEND.parent / "frontend" / "src", {".ts", ".tsx", ".js", ".jsx"}),
    ):
        for p in _files(root, sfx):
            if PATTERN.search(p.read_text(errors="ignore")):
                hits.add(
                    str(
                        p.relative_to(
                            BACKEND.parent if "frontend" in p.parts else BACKEND
                        )
                    )
                )
    stray = {h for h in hits if h not in ALLOWED}
    assert not stray, stray
    assert not [
        h
        for h in hits
        if h.startswith(
            ("frontend/", "app/api/", "app/services/etl/", "app/services/auto_pick/")
        )
    ]


def test_auto_pick_never_imports_fair_price():
    files = list((BACKEND / "app/services/auto_pick").rglob("*.py")) + [
        BACKEND / "app/tasks/auto_pick.py"
    ]
    assert files
    for p in files:
        assert "app.services.fair_price" not in p.read_text(), p
        assert not re.search(
            r"from app\.services import[^\n]*fair_price", p.read_text()
        ), p
