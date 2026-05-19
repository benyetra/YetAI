#!/usr/bin/env python3
import argparse
import logging
import sys
from datetime import datetime
import pandas as pd
import requests
import statsapi

# ------ S3 CSV SUPPORT (write and read) ------
import boto3
from io import StringIO, BytesIO

def smart_to_csv(df, path, **kwargs):
    """Write a DataFrame to S3 or local file depending on path."""
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, **kwargs)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=csv_buffer.getvalue())
        logging.info(f"Uploaded {len(df)} rows → s3://{bucket}/{key}")
    else:
        df.to_csv(path, index=False, **kwargs)
        logging.info(f"Wrote {len(df)} rows → {path}")
# ---------------------------------------------

def fetch_player_name_and_hand(pid):
    try:
        ppl = statsapi.get("people", {"personIds": pid}).get("people", [])
        if ppl:
            name = ppl[0].get("fullName", "")
            hand = ppl[0].get("pitchHand", {}).get("code")
            if hand:
                return name, hand
    except Exception as e:
        pass
    try:
        lk = statsapi.lookup_player(pid)
        if lk and "fullName" in lk[0]:
            name = lk[0]["fullName"]
            hand = lk[0].get("pitchHand", {}).get("code")
            return name, hand or "UNK"
        if name and not hand:
            hand = fetch_hand_by_name(name)
        return name, hand or "UNK"
    except Exception:
        pass
    return "", "UNK"

def fetch_hand_by_name(name):
    matches = statsapi.lookup_player(name)
    if matches and "pitchHand" in matches[0]:
        return matches[0]["pitchHand"].get("code", "UNK")
    return "UNK"

def resolve_pitcher_id(pitcher):
    if pitcher is None or pitcher == "":
        return None
    try:
        return int(pitcher)
    except Exception:
        pass
    try:
        matches = statsapi.lookup_player(str(pitcher))
        if matches and "id" in matches[0]:
            return matches[0]["id"]
    except Exception:
        pass
    return None

def get_game_starters(game):
    home_pitcher = game.get("home_probable_pitcher")
    away_pitcher = game.get("away_probable_pitcher")

    home_pid = resolve_pitcher_id(home_pitcher)
    away_pid = resolve_pitcher_id(away_pitcher)

    if not home_pid or not away_pid:
        try:
            box = statsapi.get("game", {"gamePk": game["game_id"]})["liveData"]["boxscore"]["teams"]
            for side, key in [("home", "home"), ("away", "away")]:
                if (side == "home" and not home_pid) or (side == "away" and not away_pid):
                    team = box.get(side, {})
                    for pid_str, info in team.get("players", {}).items():
                        person = info.get("person", {})
                        pos = person.get("primaryPosition", {}).get("code")
                        if pos == "1":
                            pid = person.get("id")
                            if side == "home" and not home_pid:
                                home_pid = pid
                            if side == "away" and not away_pid:
                                away_pid = pid
        except Exception as e:
            print(f"DEBUG: Fallback to boxscore failed for {game['game_id']} — {e}")

    return home_pid, away_pid

def get_batters(game_id):
    game_data = statsapi.get("game", {"gamePk": game_id})
    batters = []
    orders = {}
    if "liveData" in game_data and "boxscore" in game_data["liveData"]:
        box = game_data["liveData"]["boxscore"]
        for side in ("home", "away"):
            for pid_str, info in box["teams"][side]["players"].items():
                pid = int(pid_str.replace("ID", ""))
                bo = info.get("battingOrder")
                if bo is not None:
                    orders[pid] = int(bo)
        for pid, bo in orders.items():
            resp = statsapi.get("people", {"personIds": pid})
            people = resp.get("people", [])
            if not people:
                continue
            p = people[0]
            if p.get("primaryPosition", {}).get("code") == "1":
                continue
            side = None
            for s in ("home", "away"):
                ids = {int(x.replace("ID", "")) for x in box["teams"][s]["players"]}
                if pid in ids:
                    side = s
                    break
            if not side:
                continue
            bat_side = p.get("batSide", {}).get("code")
            if bat_side not in ("L", "R", "S"):
                continue
            batters.append({
                "id":           pid,
                "fullName":     p.get("fullName", ""),
                "batSide":      bat_side,
                "team":         box["teams"][side]["team"]["name"],
                "battingOrder": bo
            })
    return batters

def get_probable_batters(game_id, home_name, away_name):
    url = (
        f"https://bdfed.stitch.mlbinfra.com/bdfed/matchup/{game_id}"
        "?statList=avg&statList=atBats&statList=homeRuns&statList=rbi&statList=ops"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        resp = r.json()
    except Exception as e:
        logging.warning(f"Game {game_id}: probable lineup fetch failed → {e}")
        return []
    batters = []
    for side_key, team_label in [("home", home_name), ("away", away_name)]:
        lst = resp.get(side_key, []) or resp.get("matchup", {}).get(side_key, [])
        for ent in lst:
            obj = ent.get("player", ent)
            pid = obj.get("id") or obj.get("playerId")
            if not pid:
                continue
            ppl = statsapi.get("people", {"personIds": pid}).get("people", [])
            if not ppl:
                continue
            p = ppl[0]
            bat_side = p.get("batSide", {}).get("code")
            if bat_side not in ("L", "R", "S"):
                continue
            bo = ent.get("batOrder") or ent.get("lineupSlot") or None
            batters.append({
                "id":           pid,
                "fullName":     p.get("fullName", ""),
                "batSide":      bat_side,
                "team":         team_label,
                "battingOrder": bo
            })
    return batters

def get_todays_games():
    today = datetime.today().strftime("%Y-%m-%d")
    sched = statsapi.schedule(date=today)
    return [{
        "game_id":   g["game_id"],
        "home_name": g["home_name"],
        "away_name": g["away_name"],
        "home_id":   g["home_id"],
        "away_id":   g["away_id"],
        "game_date": g.get("game_date"),
        "home_probable_pitcher": g.get("home_probable_pitcher"),
        "away_probable_pitcher": g.get("away_probable_pitcher"),
    } for g in sched]

def build_today_lineup(output_csv):
    games = get_todays_games()
    if not games:
        logging.error("No games scheduled for today.")
        sys.exit(1)

    rows = []
    for g in games:
        gid = g["game_id"]
        home_nm = g["home_name"]
        away_nm = g["away_name"]
        game_date = g["game_date"]

        home_pid, away_pid = get_game_starters(g)
        if not home_pid or not away_pid:
            logging.warning(f"{gid}: missing starter(s) after all attempts. "
                            f"Schedule home_prob: {g.get('home_probable_pitcher')} "
                            f"away_prob: {g.get('away_probable_pitcher')}")
            continue

        hname, hh = fetch_player_name_and_hand(home_pid) if home_pid else ("", "")
        aname, ah = fetch_player_name_and_hand(away_pid) if away_pid else ("", "")

        if not hname:
            hname = g.get("home_probable_pitcher", "") or ""
        if not aname:
            aname = g.get("away_probable_pitcher", "") or ""

        if not home_pid:
            logging.warning(f"{gid}: missing home starter, will mark as unknown")
        if not away_pid:
            logging.warning(f"{gid}: missing away starter, will mark as unknown")

        tinfo = statsapi.get("team", {"teamId": g["home_id"]}).get("teams", [{}])[0]
        park_id = tinfo.get("abbreviation", "").lower()
        park_nm = statsapi.get("game", {"gamePk": gid}) \
                          .get("gameData", {}).get("venue", {}).get("name", "")
        if not park_id or not park_nm:
            logging.warning(f"{gid}: missing park info → skipping")
            continue

        bats = get_batters(gid)
        if len(bats) < 7:
            logging.info(f"{gid}: official <7, trying probable")
            prob = get_probable_batters(gid, home_nm, away_nm)
            if len(prob) >= 7:
                bats = prob
            else:
                logging.warning(f"{gid}: still <7 batters → skipping")
                continue

        for b in bats:
            bid = b["id"]
            if b["team"] == home_nm:
                opp_id, opp_name, opp_hand = away_pid, aname, ah
            else:
                opp_id, opp_name, opp_hand = home_pid, hname, hh

            rows.append({
                "batter_name":  b["fullName"],
                "batter_hand":  b["batSide"],
                "batter_id":    bid,
                "pitcher_id":   opp_id or '',
                "pitcher_name": opp_name or '',
                "pitcher_hand": opp_hand or 'UNK',
                "park_id":      park_id,
                "park_name":    park_nm,
                "game_date":    game_date,
            })

        if not home_pid or not away_pid:
            logging.warning(
                f"{gid}: missing starter(s) — home: {home_nm}, away: {away_nm}, home_pid: {home_pid}, away_pid: {away_pid}"
            )
            continue

    df = pd.DataFrame(rows)
    if df.empty or df["batter_id"].isna().any():
        logging.error("Lineup CSV missing batter_id values or is empty → abort")
        sys.exit(1)

    final_cols = [
        "batter_name", "batter_hand", "batter_id",
        "pitcher_id", "pitcher_name", "pitcher_hand",
        "park_id", "park_name", "game_date"
    ]
    df = df[final_cols]
    smart_to_csv(df, output_csv)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s — %(levelname)s — %(message)s",
        datefmt="%Y%m%d %H:%M:%S"
    )
    p = argparse.ArgumentParser(description="Fetch today’s lineups → CSV with batter_id & game_date")
    p.add_argument("--output", default="today_lineup.csv", help="Output CSV path or s3://bucket/key.csv")
    args = p.parse_args()
    build_today_lineup(args.output)
