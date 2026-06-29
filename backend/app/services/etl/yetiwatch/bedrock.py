"""AWS Bedrock client for YetiWatch LLM synthesis."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).with_name("synthesis_prompt.md")


def bedrock_enabled() -> bool:
    return bool(getattr(settings, "YETIWATCH_BEDROCK_ENABLED", False))


def _system_prompt() -> str:
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    start = text.find("```\nYou are YetiWatch")
    if start == -1:
        return text
    end = text.find("```", start + 4)
    block = text[start + 4 : end]
    return block.strip()


def _build_user_message(
    *,
    player_name: str,
    player_id: str | int,
    team_id: str | int,
    opponent_id: str | int | None,
    game_start_iso: str,
    home_or_away: str,
    b2b_bool: bool,
    run_id: str,
    as_of_iso: str,
    baseline_role: str,
    items: list[dict[str, Any]],
) -> str:
    lines = [
        f"PLAYER: {player_name} (id: {player_id}, team: {team_id})",
        f"GAME: vs {opponent_id} | tip {game_start_iso} | {home_or_away} | back-to-back: {b2b_bool}",
        f"RUN: {run_id} | as_of: {as_of_iso}",
        f"BASELINE ROLE: {baseline_role}",
        "",
        "CANDIDATE ITEMS (deduped, from multiple sources — synthesize, do not quote):",
    ]
    for item in items:
        lines.append(
            f"- [tier: {item['tier']} | {item['source_label']} | {item['item_ts_iso']}] {item['text']}"
        )
    lines.append("")
    lines.append(
        "If CANDIDATE ITEMS is empty or none are material to this game, return the neutral state."
    )
    lines.append("Return ONLY the JSON object.")
    return "\n".join(lines)


def invoke_bedrock_json(
    *,
    player_name: str,
    player_id: str | int,
    team_id: str | int,
    opponent_id: str | int | None,
    game_start_iso: str,
    home_or_away: str,
    b2b_bool: bool,
    run_id: str,
    as_of_iso: str,
    baseline_role: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    import boto3

    model_id = getattr(
        settings,
        "YETIWATCH_BEDROCK_MODEL_ID",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
    )
    region = getattr(settings, "YETIWATCH_BEDROCK_REGION", "us-east-1")
    client = boto3.client("bedrock-runtime", region_name=region)
    user_message = _build_user_message(
        player_name=player_name,
        player_id=player_id,
        team_id=team_id,
        opponent_id=opponent_id,
        game_start_iso=game_start_iso,
        home_or_away=home_or_away,
        b2b_bool=b2b_bool,
        run_id=run_id,
        as_of_iso=as_of_iso,
        baseline_role=baseline_role,
        items=items,
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1200,
        "temperature": 0.2,
        "system": _system_prompt(),
        "messages": [{"role": "user", "content": user_message}],
    }
    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(response["body"].read())
    text = ""
    for block in payload.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())
