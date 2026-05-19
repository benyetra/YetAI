# ---- offsets.py (or tuck near your projection helpers) ----
from datetime import date
from sqlalchemy import text
from app.services.etl.mlb._db import db_session
import pandas as pd
import math

V2_START = date(2025, 8, 1)

def _read_df(sql: str) -> pd.DataFrame:
    res = db_session.execute(text(sql))
    return pd.DataFrame(res.fetchall(), columns=res.keys())

def get_global_offsets():
    sql = f"""
    SELECT
      p.date, p.pitcher_id,
      p.projected_strikeouts, a.actual_strikeouts,
      p.projected_innings_pitched, a.actual_innings_pitched
    FROM strikeout_projections p
    JOIN strikeout_actuals a
      ON p.date=a.date AND p.pitcher_id=a.pitcher_id
    WHERE p.date >= '{V2_START}'
    """
    df = _read_df(sql)
    if df.empty:
        return 0.0, 0.0
    k_off = (df["actual_strikeouts"] - df["projected_strikeouts"]).mean()
    ip_off = (df["actual_innings_pitched"] - df["projected_innings_pitched"]).mean()
    return float(k_off), float(ip_off)

def get_pitcher_offsets(pitcher_id: str, n_last: int = 4):
    sql = f"""
    SELECT
      p.date,
      p.projected_strikeouts, a.actual_strikeouts,
      p.projected_innings_pitched, a.actual_innings_pitched
    FROM strikeout_projections p
    JOIN strikeout_actuals a
      ON p.date=a.date AND p.pitcher_id=a.pitcher_id
    WHERE p.pitcher_id = :pid AND p.date >= '{V2_START}'
    ORDER BY p.date DESC
    """
    result = db_session.execute(text(sql), {"pid": str(pitcher_id)})
    df = pd.DataFrame(result.fetchall(), columns=result.keys())
    if df.empty:
        return 0.0, 0.0, 0  # k_off, ip_off, count
    df = df.head(n_last)
    k_off = (df["actual_strikeouts"] - df["projected_strikeouts"]).mean()
    ip_off = (df["actual_innings_pitched"] - df["projected_innings_pitched"]).mean()
    return float(k_off), float(ip_off), int(len(df))

def apply_shrunk_offsets(proj_k, proj_ip, pid):
    gk, gip = get_global_offsets()
    pk, pip, n = get_pitcher_offsets(pid)

    # Empirical-Bayes style shrinkage toward global:
    # weight pitcher offset more as we have more starts (τ = 3 is a good prior strength)
    tau = 3.0
    w = n / (n + tau)

    k_bias = w * pk + (1 - w) * gk
    ip_bias = w * pip + (1 - w) * gip

    adj_k  = proj_k  + k_bias
    adj_ip = proj_ip + ip_bias

    # keep things sane
    adj_k  = max(0.0, adj_k)
    adj_ip = min(9.0, max(1.0, adj_ip))
    return adj_k, adj_ip, {"k_bias": k_bias, "ip_bias": ip_bias, "n": n}
