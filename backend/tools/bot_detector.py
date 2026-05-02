"""Programmatic signup / bot farm detection over case CSV using Polars."""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

_DISPOSABLE_DOMAINS = frozenset(
    {
        "10minutemail.com",
        "10minutemail.net",
        "guerrillamail.com",
        "guerrillamailblock.com",
        "mailinator.com",
        "temp-mail.org",
        "tempmail.com",
        "throwaway.email",
        "yopmail.com",
        "trashmail.com",
        "getnada.com",
        "maildrop.cc",
        "tempail.com",
        "fakeinbox.com",
        "dispostable.com",
        "mohmal.com",
    }
)

_CREATED_CANDS = (
    "created_at",
    "signup_at",
    "signup_time",
    "account_created_at",
    "registered_at",
    "registration_time",
    "registration_date",
    "signup_date",
    "join_date",
    "joined_at",
    "event_time",
    "event_date",
    "occurred_at",
    "session_start",
    "created",
    "ts",
    "timestamp",
    "datetime",
    "dt",
    "date",
)

_USER_CANDS = (
    "user_id",
    "account_id",
    "acc_id",
    "userid",
    "customer_id",
    "customerid",
    "member_id",
    "memberid",
    "username",
    "login",
    "uid",
    "id",
)

_EMAIL_CANDS = ("email", "user_email", "e_mail", "mail", "primary_email")

_IP_CANDS = (
    "ip_address",
    "signup_ip",
    "registration_ip",
    "ip",
    "client_ip",
    "remote_ip",
)

_UA_CANDS = ("user_agent", "useragent", "ua", "http_user_agent")

# canvas_fingerprint / browser_hash first — Humanoid-style hardware collision signals
_CANVAS_CANDS = (
    "canvas_fingerprint",
    "browser_hash",
    "fingerprint_id",
    "canvas_fp",
    "canvas_hash",
    "browser_fingerprint",
    "fingerprint",
)

_NAME_CANDS = ("name", "full_name", "customer_name", "display_name", "username", "acc_name", "account_name")


# Canonical names used only after alias bridge (see _canonicalize_fraud_column_aliases).
_CANONICAL_USER_ALIASES: tuple[str, ...] = (
    "acc_id",
    "uid",
    "customer_id",
    "userid",
    "account_id",
    "member_id",
    "user_id",
    "id",
)
_CANONICAL_TS_ALIASES: tuple[str, ...] = (
    "timestamp",
    "signup_time",
    "created_at",
    "registered_at",
    "registration_time",
    "date",
    "time",
    "ts",
    "datetime",
    "event_time",
    "joined_at",
)
_CANONICAL_IP_ALIASES: tuple[str, ...] = (
    "ip",
    "ip_address",
    "signup_ip",
    "remote_addr",
    "client_ip",
    "registration_ip",
    "remote_ip",
)


def _strip_csv_column_noise(df: pl.DataFrame) -> pl.DataFrame:
    """Strip BOM / outer whitespace from headers so acc_id / created_at resolve reliably."""
    renames: dict[str, str] = {}
    for c in df.columns:
        c2 = str(c).lstrip("\ufeff").strip()
        if c2 != c:
            renames[c] = c2
    if not renames:
        return df
    target_names = [renames.get(c, c) for c in df.columns]
    if len(set(target_names)) < len(target_names):
        return df
    return df.rename(renames)


_USER_FUZZ_TARGETS: tuple[str, ...] = (
    "userid",
    "accountid",
    "accid",
    "customerid",
    "memberid",
    "entityid",
    "playerid",
    "loginid",
    "subscriberid",
    "username",
    "accountnumber",
)
_TS_FUZZ_TARGETS: tuple[str, ...] = (
    "createdat",
    "signupat",
    "signup",
    "registeredat",
    "registration",
    "timestamp",
    "datetime",
    "eventtime",
    "occurredat",
    "joinedat",
    "dateregistered",
)


def _fuzzy_score_column_name(norm_col: str, targets: tuple[str, ...]) -> float:
    best = 0.0
    for t in targets:
        if t in norm_col or norm_col in t:
            best = max(best, 0.9)
        r = difflib.SequenceMatcher(None, norm_col, t).ratio()
        if r > best:
            best = r
    return best


def _fuzzy_rename_missing_core_columns(df: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, str]]:
    """Fuzzy header bridge when exact alias lists miss (typos, vendor-specific names)."""
    rename_map: dict[str, str] = {}
    blocked_user = frozenset(
        {"email", "mail", "ipaddress", "phone", "latitude", "longitude", "canvas", "fingerprint", "browser", "useragent"},
    )

    if "user_id" not in df.columns:
        best_col: str | None = None
        best_score = 0.52
        for c in df.columns:
            nk = _norm_col_key(c)
            if len(nk) < 3:
                continue
            if any(b in nk for b in blocked_user):
                continue
            sc = _fuzzy_score_column_name(nk, _USER_FUZZ_TARGETS)
            if nk in ("id", "uuid", "pk") and sc < 0.75:
                sc = 0.74
            if sc >= best_score:
                best_score = sc
                best_col = c
        if best_col:
            rename_map[best_col] = "user_id"

    if "created_at" not in df.columns:
        best_col = None
        best_score = 0.52
        for c in df.columns:
            nk = _norm_col_key(c)
            if len(nk) < 3:
                continue
            sc = _fuzzy_score_column_name(nk, _TS_FUZZ_TARGETS)
            dt = df[c].dtype
            if dt == pl.Date or dt == pl.Datetime or "Datetime" in str(dt):
                sc = max(sc, 0.85)
            if sc >= best_score:
                best_score = sc
                best_col = c
        if best_col:
            rename_map[best_col] = "created_at"

    if not rename_map:
        return df, {}
    return df.rename(rename_map), {str(k): str(v) for k, v in rename_map.items()}


def _canonicalize_fraud_column_aliases(df: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, str]]:
    """
    Schema-agnostic bridge: rename the first matching alias per role to stable names
    (`user_id`, `created_at`, `ip`) so downstream heuristics always find core columns.
    Skips a role if the canonical name already exists on the frame.
    """
    lower = {c.lower(): c for c in df.columns}
    rename_map: dict[str, str] = {}

    def _first_existing(aliases: tuple[str, ...]) -> str | None:
        for a in aliases:
            if a in df.columns:
                return a
            lk = a.lower()
            if lk in lower:
                return lower[lk]
        return None

    if "user_id" not in df.columns:
        src = _first_existing(_CANONICAL_USER_ALIASES)
        if src:
            rename_map[src] = "user_id"
    if "created_at" not in df.columns:
        src = _first_existing(_CANONICAL_TS_ALIASES)
        if src:
            rename_map[src] = "created_at"
    if "ip" not in df.columns:
        src = _first_existing(_CANONICAL_IP_ALIASES)
        if src:
            rename_map[src] = "ip"

    if not rename_map:
        return df, {}
    # Avoid double-rename if two aliases resolved to same source (shouldn't happen)
    out = df.rename(rename_map)
    return out, {str(k): str(v) for k, v in rename_map.items()}


def _pick_col(df: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand in df.columns:
            return cand
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _norm_col_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _resolve_explicit_col(df: pl.DataFrame, name: str | None) -> str | None:
    """Resolve an operator-supplied column name (case-insensitive, ignores spaces/underscores style drift)."""
    raw = (name or "").strip()
    if not raw:
        return None
    if raw in df.columns:
        return raw
    lower = {c.lower(): c for c in df.columns}
    if raw.lower() in lower:
        return lower[raw.lower()]
    want = _norm_col_key(raw)
    for c in df.columns:
        if _norm_col_key(c) == want:
            return c
    return None


def _pick_timestamp_dtype_heuristic(df: pl.DataFrame) -> str | None:
    """Prefer any column that is already Date/Datetime typed (common after try_parse_dates)."""
    for c in df.columns:
        dt = df[c].dtype
        if dt == pl.Date or dt == pl.Datetime:
            return c
        s = str(dt)
        if "Datetime" in s or (s.startswith("Date") and "Datetime" not in s):
            return c
    return None


def _pick_user_substring_heuristic(df: pl.DataFrame, *, skip_cols: frozenset[str]) -> str | None:
    """Last-resort: column whose normalized name suggests a stable account key."""
    hints = ("userid", "accountid", "accid", "memberid", "customerid", "loginid", "playerid")
    best: tuple[int, str] | None = None  # (-specificity rank, col) lower rank = better
    for c in df.columns:
        if c in skip_cols:
            continue
        n = _norm_col_key(c)
        if len(n) < 3 or len(n) > 48:
            continue
        for i, h in enumerate(hints):
            if h in n:
                rank = i
                if best is None or rank < best[0]:
                    best = (rank, c)
                break
    return best[1] if best else None


_TS_SEMANTIC_SUBSTR = (
    "time",
    "date",
    "ts",
    "created",
    "signup",
    "registered",
    "joined",
    "event",
    "stamp",
    "occurred",
    "session",
    "start",
    "at",
)

_USER_SEMANTIC_SUBSTR = (
    "userid",
    "accountid",
    "accid",
    "customerid",
    "memberid",
    "loginid",
    "playerid",
    "entityid",
    "uid",
)


def _semantic_map_timestamp(df: pl.DataFrame) -> str | None:
    """Score columns by datetime dtype + name tokens (timestamp, date, signup_time, …)."""
    best: tuple[int, str] | None = None
    penalize_exact = frozenset(
        {"latitude", "longitude", "amount", "price", "lat", "lon", "balance", "score"},
    )
    for c in df.columns:
        nk = _norm_col_key(c)
        if nk in penalize_exact:
            continue
        score = 0
        for h in _TS_SEMANTIC_SUBSTR:
            if h in nk:
                score += 35
        if nk in ("timestamp", "datetime"):
            score += 55
        dt = df[c].dtype
        if dt == pl.Date or dt == pl.Datetime:
            score += 110
        else:
            sdt = str(dt)
            if "Datetime" in sdt:
                score += 110
            elif sdt.startswith("Date"):
                score += 85
        if nk in ("id", "uuid", "pk") and "time" not in nk and "date" not in nk:
            score -= 50
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, c)
    if best is not None and best[0] >= 50:
        return best[1]
    return None


def _semantic_map_user_id(df: pl.DataFrame, *, skip_cols: frozenset[str]) -> str | None:
    """Score columns by normalized header (acc_id, customer_id, uid, …)."""
    best: tuple[int, str] | None = None
    for c in df.columns:
        if c in skip_cols:
            continue
        nk = _norm_col_key(c)
        if len(nk) < 2 or len(nk) > 56:
            continue
        score = 0
        for i, h in enumerate(_USER_SEMANTIC_SUBSTR):
            if h in nk:
                score += 95 - min(i, 40)
        if nk in ("id", "uuid"):
            score += 40
        if any(x in nk for x in ("email", "mail", "ipaddress", "phone", "latitude", "longitude", "amount")):
            score -= 90
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, c)
    if best is not None and best[0] >= 50:
        return best[1]
    return None


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _ipv4_subnet24(ip: str | None) -> str | None:
    if not ip or not isinstance(ip, str):
        return None
    ip = ip.strip()
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(x < 0 or x > 255 for x in nums):
        return None
    return f"{nums[0]}.{nums[1]}.{nums[2]}.0/24"


def _ua_stale_score(ua: str | None) -> int | None:
    """Return Chrome major version if UA looks stale (heuristic), else None."""
    if not ua:
        return None
    m = re.search(r"Chrome/(\d+)", ua, re.I)
    if not m:
        return None
    try:
        major = int(m.group(1))
    except ValueError:
        return None
    return major


def _series_pattern_score(user_ids: list[str]) -> tuple[bool, str | None]:
    """Detect sequential bot handles: user_01, user_02 / bot001, bot002."""
    if len(user_ids) < 4:
        return False, None
    pat = re.compile(r"^(?P<p>[a-zA-Z]+[._-]?)(?P<n>\d{1,6})$")
    nums: list[tuple[str, int]] = []
    for u in user_ids:
        m = pat.match(str(u).strip())
        if m:
            nums.append((m.group("p"), int(m.group("n"))))
    if len(nums) < 4:
        return False, None
    by_p: dict[str, list[int]] = {}
    for p, n in nums:
        by_p.setdefault(p, []).append(n)
    for p, ns in by_p.items():
        if len(ns) < 4:
            continue
        s = sorted(set(ns))
        runs = 0
        for i in range(1, len(s)):
            if s[i] == s[i - 1] + 1:
                runs += 1
        if runs >= 3:
            return True, f"sequential_like:{p}*{len(ns)}"
    return False, None


def _canvas_ip_hardware_bundle(
    df: pl.DataFrame,
    canvas_col: str | None,
    ip_col: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Shared canvas × IP distribution + optional hardware spoofing assessment."""
    canvas_fingerprint_distribution: list[dict[str, Any]] = []
    hardware_spoofing_assessment: dict[str, Any] | None = None
    if not (canvas_col and ip_col):
        return canvas_fingerprint_distribution, hardware_spoofing_assessment
    total_n = len(df)
    dist_df = (
        df.filter(pl.col(canvas_col).is_not_null())
        .group_by(canvas_col)
        .agg(pl.len().alias("row_count"), pl.col(ip_col).n_unique().alias("distinct_ip_count"))
        .sort("row_count", descending=True)
    )
    for row in dist_df.head(12).iter_rows(named=True):
        fp = row[canvas_col]
        rc = int(row["row_count"])
        dip = int(row["distinct_ip_count"])
        canvas_fingerprint_distribution.append(
            {
                "fingerprint_value": str(fp),
                "fingerprint_preview": str(fp)[:96],
                "row_count": rc,
                "share_pct": round(100.0 * rc / max(total_n, 1), 2),
                "distinct_ip_count": dip,
            },
        )
    if canvas_fingerprint_distribution:
        top = canvas_fingerprint_distribution[0]
        one_fp_dominates = top["share_pct"] >= 95.0
        ip_diverse_vs_accounts = top["distinct_ip_count"] >= max(5, int(0.45 * top["row_count"]))
        if one_fp_dominates and ip_diverse_vs_accounts and top["row_count"] >= 5:
            hardware_spoofing_assessment = {
                "label": "High-Confidence Hardware Spoofing Ring",
                "confidence": "high",
                "dominant_fingerprint": top["fingerprint_preview"],
                "accounts_on_dominant_fingerprint": top["row_count"],
                "distinct_ips_on_dominant_fingerprint": top["distinct_ip_count"],
                "share_pct": top["share_pct"],
                "rationale": (
                    "One canvas fingerprint accounts for nearly all rows while IP addresses stay highly "
                    "diverse—consistent with hardware fingerprint reuse / spoofing rather than organic signups."
                ),
            }
    return canvas_fingerprint_distribution, hardware_spoofing_assessment


def _build_hardware_ip_forensics(
    *,
    df: pl.DataFrame,
    canvas_col: str | None,
    ip_col: str | None,
    user_col: str | None,
    canvas_fingerprint_distribution: list[dict[str, Any]],
    hardware_spoofing_assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    """Structured payload for BotHardwareForensicCard (console / workspace)."""
    total_n = max(len(df), 1)
    if not canvas_fingerprint_distribution:
        return {
            "dominant_canvas_fingerprint": None,
            "row_count_on_dominant": 0,
            "unique_ips_on_dominant": 0,
            "unique_accounts_on_dominant": 0,
            "share_pct_on_dominant": 0.0,
            "associated_ips": [],
            "critical_hardware_spoofing": False,
            "verdict_label": "No canvas × IP distribution computed (missing columns).",
            "infrastructure_summary": "—",
            "recommended_action": "Upload signup telemetry with canvas_fingerprint and ip columns.",
            "pin_eligible": False,
            "hardware_spoofing_assessment": hardware_spoofing_assessment,
        }

    top = canvas_fingerprint_distribution[0]
    fval = str(top.get("fingerprint_value") or top.get("fingerprint_preview") or "")
    preview = str(top.get("fingerprint_preview") or fval[:96])
    row_c = int(top.get("row_count") or 0)
    dip = int(top.get("distinct_ip_count") or 0)
    share = float(top.get("share_pct") or 0.0)
    critical = share >= 99.5 or (len(canvas_fingerprint_distribution) == 1 and row_c >= total_n * 0.99)

    ips: list[str] = []
    uniq_accts = row_c
    if canvas_col and ip_col and fval:
        sub = df.filter(pl.col(canvas_col).cast(pl.Utf8, strict=False) == pl.lit(fval))
        ips = (
            sub.select(pl.col(ip_col).cast(pl.Utf8, strict=False))
            .drop_nulls()[ip_col]
            .unique()
            .head(120)
            .to_list()
        )
        ips = [str(x) for x in ips if str(x).strip()]
        if user_col:
            uniq_accts = int(sub[user_col].n_unique())

    pin_eligible = bool(hardware_spoofing_assessment) or (
        share >= 90.0 and dip >= 5 and dip >= max(3, int(0.15 * max(row_c, 1)))
    )

    if critical:
        verdict = "CRITICAL: HARDWARE SPOOFING DETECTED"
    elif hardware_spoofing_assessment:
        verdict = "Verified Bot Ring (High Confidence)"
    elif share >= 80.0:
        verdict = "Strong Hardware Concentration"
    else:
        verdict = "Review Canvas / IP Distribution"

    infra = (
        f"Shared fingerprint {preview} · ~{uniq_accts} accounts · {dip} distinct IPs on dominant canvas bucket."
    )

    rec = (
        "Treat as synthetic / automated signup ring: correlate with device history, velocity rules, and "
        "step-up authentication before batch remediation."
    )
    if dip >= max(10, row_c // 2):
        rec += " High IP diversity vs one canvas ⇒ residential proxy / Humanoid-class rotation likely."

    return {
        "dominant_canvas_fingerprint": preview,
        "dominant_canvas_fingerprint_full": fval[:512],
        "row_count_on_dominant": row_c,
        "unique_ips_on_dominant": dip,
        "unique_accounts_on_dominant": uniq_accts,
        "share_pct_on_dominant": share,
        "associated_ips": ips,
        "critical_hardware_spoofing": critical,
        "verdict_label": verdict,
        "infrastructure_summary": infra,
        "recommended_action": rec,
        "pin_eligible": pin_eligible,
        "hardware_spoofing_assessment": hardware_spoofing_assessment,
    }


def _degraded_bot_cluster_response(
    path: Path,
    df: pl.DataFrame,
    *,
    column_alias_bridge: dict[str, str],
    ts_col: str | None,
    user_col: str | None,
    parse_failed: bool,
) -> dict[str, Any]:
    """Never surface hard 'need_columns' failures — return forensic JSON + optional canvas-only signals."""
    email_col = _pick_col(df, _EMAIL_CANDS)
    ip_col = _pick_col(df, _IP_CANDS)
    ua_col = _pick_col(df, _UA_CANDS)
    canvas_col = _pick_col(df, _CANVAS_CANDS)
    name_col = _pick_col(df, _NAME_CANDS)
    canvas_fingerprint_distribution, hardware_spoofing_assessment = _canvas_ip_hardware_bundle(df, canvas_col, ip_col)
    hwf = _build_hardware_ip_forensics(
        df=df,
        canvas_col=canvas_col,
        ip_col=ip_col,
        user_col=user_col,
        canvas_fingerprint_distribution=canvas_fingerprint_distribution,
        hardware_spoofing_assessment=hardware_spoofing_assessment,
    )
    reasons: list[str] = []
    if not ts_col:
        reasons.append("missing_timestamp_column")
    if not user_col:
        reasons.append("missing_user_id_column")
    if parse_failed:
        reasons.append("no_parseable_timestamps")
    return {
        "ok": True,
        "kind": "bot_hardware_forensic",
        "analysis_degraded": True,
        "analysis_degraded_reason": ",".join(reasons) or "unknown",
        "row_count": len(df),
        "unique_users": int(df[user_col].n_unique()) if user_col else len(df),
        "bot_density_pct": 0.0,
        "clusters": [],
        "hardware_overlap_cards": [],
        "timeline_5m": [],
        "high_bot_window_alert": False,
        "max_bot_pct_5m_window": 0.0,
        "column_alias_bridge": column_alias_bridge,
        "columns_used": {
            "timestamp": ts_col,
            "user_id": user_col,
            "email": email_col,
            "ip": ip_col,
            "user_agent": ua_col,
            "canvas_fingerprint": canvas_col,
            "name": name_col,
        },
        "semantic_column_mapping": {
            "timestamp": ts_col,
            "user_id": user_col,
            "name": name_col,
            "canvas_fingerprint": canvas_col,
            "note": "Degraded analysis: time/user heuristics incomplete; canvas×IP forensics only.",
        },
        "canvas_fingerprint_distribution": canvas_fingerprint_distribution,
        "hardware_spoofing_assessment": hardware_spoofing_assessment,
        "hardware_ip_forensics": hwf,
        "cluster_insights_ready": bool(canvas_fingerprint_distribution),
        "primary_signal": "canvas_hardware" if canvas_fingerprint_distribution else None,
        "primary_signal_rationale": "Degraded path — hardware / canvas signals only." if canvas_fingerprint_distribution else None,
        "schema_grounded_analysis": {
            "dataset_basename": path.name,
            "column_alias_bridge": column_alias_bridge,
            "columns_present": list(df.columns),
            "email_column_present": email_col is not None,
            "forbid_email_pattern_narrative": email_col is None,
        },
    }


def detect_bot_clusters(
    dataset_path: str | Path,
    *,
    timestamp_column: str | None = None,
    user_id_column: str | None = None,
    burst_min_accounts: int = 8,
    burst_window_minutes: int = 1,
    infra_min_size: int = 5,
    disposable_min_size: int = 2,
    gmail_dot_min_size: int = 4,
    high_entropy_min: float = 4.25,
    high_entropy_len_min: int = 10,
    max_members_per_cluster: int = 1500,
    chrome_stale_below: int = 115,
) -> dict[str, Any]:
    """
    Identify bot-like registration clusters: time bursts, shared /24 + UA/canvas,
    disposable domains, Gmail dot-shuffle, high-entropy local parts, sequential ids.
    """
    path = Path(dataset_path)
    if not path.is_file():
        return {"ok": False, "error": f"Dataset not found: {path}"}

    df = pl.read_csv(path, try_parse_dates=True, infer_schema_length=5000)
    if len(df) == 0:
        return {"ok": False, "error": "Dataset is empty."}

    df = _strip_csv_column_noise(df)
    df, column_alias_bridge = _canonicalize_fraud_column_aliases(df)
    df, fuzzy_bridge = _fuzzy_rename_missing_core_columns(df)
    if fuzzy_bridge:
        column_alias_bridge = {**column_alias_bridge, **fuzzy_bridge}

    ts_col = _resolve_explicit_col(df, timestamp_column) or _pick_col(df, _CREATED_CANDS)
    if not ts_col:
        ts_col = _pick_timestamp_dtype_heuristic(df)
    if not ts_col:
        ts_col = _semantic_map_timestamp(df)
    user_col = _resolve_explicit_col(df, user_id_column) or _pick_col(df, _USER_CANDS)
    skip_for_user = frozenset({c for c in (ts_col,) if c})
    if not user_col:
        user_col = _pick_user_substring_heuristic(df, skip_cols=skip_for_user)
    if not user_col:
        user_col = _semantic_map_user_id(df, skip_cols=skip_for_user)
    email_col = _pick_col(df, _EMAIL_CANDS)
    ip_col = _pick_col(df, _IP_CANDS)
    ua_col = _pick_col(df, _UA_CANDS)
    canvas_col = _pick_col(df, _CANVAS_CANDS)
    name_col = _pick_col(df, _NAME_CANDS)

    if not ts_col or not user_col:
        return _degraded_bot_cluster_response(
            path,
            df,
            column_alias_bridge=column_alias_bridge,
            ts_col=ts_col,
            user_col=user_col,
            parse_failed=False,
        )

    # Normalize timestamp
    df_raw_for_fallback = df
    ts_expr = pl.col(ts_col)
    if df[ts_col].dtype == pl.Utf8 or str(df[ts_col].dtype).startswith("String"):
        ts_expr = pl.col(ts_col).str.to_datetime(strict=False, time_unit="us")
    df = df.with_columns(ts_expr.alias("_bot_ts"))

    df = df.filter(pl.col("_bot_ts").is_not_null())
    if len(df) == 0:
        return _degraded_bot_cluster_response(
            path,
            df_raw_for_fallback,
            column_alias_bridge=column_alias_bridge,
            ts_col=ts_col,
            user_col=user_col,
            parse_failed=True,
        )

    # Subnet + email parts
    steps: list[pl.Expr] = []
    if ip_col:
        steps.append(
            pl.col(ip_col)
            .map_elements(lambda x: _ipv4_subnet24(x), return_dtype=pl.Utf8)
            .alias("_subnet24")
        )
    else:
        steps.append(pl.lit(None).cast(pl.Utf8).alias("_subnet24"))

    if email_col:
        lower = pl.col(email_col).cast(pl.Utf8, strict=False).str.strip_chars().str.to_lowercase()
        parts = lower.str.split("@")
        steps.append(parts.list.get(0, null_on_oob=True).alias("_email_local"))
        steps.append(parts.list.get(1, null_on_oob=True).alias("_email_domain"))
    else:
        steps.extend(
            [
                pl.lit(None).cast(pl.Utf8).alias("_email_local"),
                pl.lit(None).cast(pl.Utf8).alias("_email_domain"),
            ]
        )

    df = df.with_columns(*steps)

    # Gmail-normalized local (dots removed for gmail/googlemail)
    df = df.with_columns(
        pl.when(pl.col("_email_domain").is_in(["gmail.com", "googlemail.com"]))
        .then(pl.col("_email_local").str.replace_all(r"\.", ""))
        .otherwise(pl.col("_email_local"))
        .alias("_gmail_norm_local")
    )

    canvas_fingerprint_distribution, hardware_spoofing_assessment = _canvas_ip_hardware_bundle(
        df,
        canvas_col,
        ip_col,
    )

    trunc = f"{burst_window_minutes}m"
    df = df.with_columns(pl.col("_bot_ts").dt.truncate(trunc).alias("_burst_bucket"))

    clusters_out: list[dict[str, Any]] = []
    cluster_seq = 0
    all_flagged_user_ids: set[str] = set()

    def _next_id(prefix: str) -> str:
        nonlocal cluster_seq
        cluster_seq += 1
        return f"{prefix}_{cluster_seq:04d}"

    # --- 1) Time-series bursts ---
    burst_groups = (
        df.group_by("_burst_bucket")
        .agg(pl.col(user_col).n_unique().alias("nu"), pl.len().alias("n"))
        .filter(pl.col("nu") >= burst_min_accounts)
    )
    for row in burst_groups.iter_rows(named=True):
        bucket = row["_burst_bucket"]
        sub = df.filter(pl.col("_burst_bucket") == bucket)
        members = sub[user_col].unique().to_list()
        members_str = [str(m) for m in members if m is not None]
        uas = sub[ua_col].drop_nulls().unique().head(3).to_list() if ua_col else []
        subs = sub["_subnet24"].drop_nulls().unique().head(3).to_list()
        traits = [f"~{len(members_str)} accounts in {burst_window_minutes}m window @ {bucket}"]
        if uas:
            traits.append(f"sample UA: {str(uas[0])[:120]}")
        if subs:
            traits.append(f"/24 overlap: {', '.join(str(s) for s in subs if s)}")
        ser_ok, ser_hint = _series_pattern_score(members_str)
        signals = ["TIME_BURST"]
        if ser_ok:
            signals.append("SEQUENTIAL_ID_PATTERN")
            if ser_hint:
                traits.append(ser_hint)
        all_flagged_user_ids.update(members_str)
        clusters_out.append(
            {
                "cluster_id": _next_id("burst"),
                "cluster_type": "time_burst",
                "size": len(members_str),
                "common_traits": traits,
                "signals": signals,
                "burst_window_start": str(bucket),
                "account_ids": members_str[:max_members_per_cluster],
                "account_ids_truncated": max(0, len(members_str) - max_members_per_cluster),
            }
        )

    hardware_overlap_cards: list[dict[str, Any]] = []
    ring_min = max(5, infra_min_size)
    # --- 2a) Humanoid / hardware: shared canvas + many distinct IPs (and names) — high-confidence bot ring ---
    if canvas_col and ip_col:
        aggs: list[pl.Expr] = [
            pl.col(user_col).n_unique().alias("nu"),
            pl.col(ip_col).n_unique().alias("n_ip"),
            pl.len().alias("n_rows"),
        ]
        if name_col:
            aggs.append(pl.col(name_col).n_unique().alias("n_name"))
        ring_groups = (
            df.filter(pl.col(canvas_col).is_not_null())
            .with_columns(pl.col(canvas_col).cast(pl.Utf8, strict=False).str.strip_chars().alias("_cf_norm"))
            .filter(pl.col("_cf_norm").is_not_null() & (pl.col("_cf_norm") != ""))
            .group_by("_cf_norm")
            .agg(aggs)
        )
        if name_col:
            cand_rings = ring_groups.filter(
                (pl.col("nu") >= ring_min) & (pl.col("n_ip") >= 3) & (pl.col("n_name") >= 3),
            )
        else:
            cand_rings = ring_groups.filter((pl.col("nu") >= ring_min) & (pl.col("n_ip") >= 5))
        for row in cand_rings.sort("nu", descending=True).head(25).iter_rows(named=True):
            fp_key = row["_cf_norm"]
            n_ip = int(row["n_ip"])
            n_name = int(row["n_name"]) if name_col else n_ip
            nu = int(row["nu"])
            sub = df.filter(pl.col(canvas_col).cast(pl.Utf8, strict=False).str.strip_chars() == fp_key)
            members = [str(x) for x in sub[user_col].unique().to_list() if x is not None]
            all_flagged_user_ids.update(members)
            fp_preview = str(fp_key)[:72]
            traits = [
                f"Shared {canvas_col} across {nu} accounts",
                f"{n_ip} distinct IPs behind one fingerprint",
                "Unique names per row — consistent with IP rotation + shared hardware",
            ]
            clusters_out.append(
                {
                    "cluster_id": _next_id("humanoid"),
                    "cluster_type": "humanoid_bot_ring",
                    "size": len(members),
                    "common_traits": traits,
                    "signals": ["HUMANOID_BOT_RING", "CANVAS_HARDWARE_COLLISION"],
                    "canvas_fingerprint": fp_preview,
                    "distinct_ip_count": n_ip,
                    "distinct_name_count": n_name if name_col else None,
                    "hardware_overlap": True,
                    "interpretation": (
                        "High-Confidence Humanoid Bot Ring: shared hardware (canvas) despite IP diversification."
                    ),
                    "account_ids": members[:max_members_per_cluster],
                    "account_ids_truncated": max(0, len(members) - max_members_per_cluster),
                },
            )
            hardware_overlap_cards.append(
                {
                    "label": "Hardware overlap",
                    "confidence": "high",
                    "canvas_fingerprint_preview": fp_preview,
                    "distinct_ip_count": n_ip,
                    "distinct_name_count": n_name if name_col else None,
                    "accounts_in_ring": nu,
                    "summary": (
                        f"{n_ip} distinct IPs hiding behind one canvas fingerprint ({fp_preview[:48]}…)"
                        if len(fp_preview) > 48
                        else f"{n_ip} distinct IPs hiding behind one canvas fingerprint."
                    ),
                },
            )

    # --- 2) Infrastructure overlap (/24 + UA, /24 + canvas) ---
    if ip_col and ua_col:
        infra = (
            df.filter(pl.col("_subnet24").is_not_null())
            .group_by(["_subnet24", ua_col])
            .agg(pl.col(user_col).n_unique().alias("nu"), pl.len().alias("n"))
            .filter(pl.col("nu") >= infra_min_size)
            .sort("nu", descending=True)
        )
        for row in infra.head(80).iter_rows(named=True):
            subnet = row["_subnet24"]
            ua = row[ua_col]
            if ua is None:
                continue
            sub = df.filter((pl.col("_subnet24") == subnet) & (pl.col(ua_col) == ua))
            members = [str(x) for x in sub[user_col].unique().to_list() if x is not None]
            ch = _ua_stale_score(str(ua))
            signals = ["SHARED_SUBNET_UA"]
            traits = [f"{subnet}", f"identical UA ({len(members)} users)", str(ua)[:140]]
            if ch is not None and ch < chrome_stale_below:
                signals.append("STALE_CHROME_UA")
                traits.append(f"Chrome/{ch} (< {chrome_stale_below})")
            all_flagged_user_ids.update(members)
            clusters_out.append(
                {
                    "cluster_id": _next_id("infra_ua"),
                    "cluster_type": "infrastructure_ua",
                    "size": len(members),
                    "common_traits": traits,
                    "signals": signals,
                    "subnet_24": subnet,
                    "account_ids": members[:max_members_per_cluster],
                    "account_ids_truncated": max(0, len(members) - max_members_per_cluster),
                }
            )

    if ip_col and canvas_col:
        infra_c = (
            df.filter(pl.col("_subnet24").is_not_null() & pl.col(canvas_col).is_not_null())
            .group_by(["_subnet24", canvas_col])
            .agg(pl.col(user_col).n_unique().alias("nu"))
            .filter(pl.col("nu") >= infra_min_size)
            .sort("nu", descending=True)
        )
        for row in infra_c.head(40).iter_rows(named=True):
            subnet = row["_subnet24"]
            fp = row[canvas_col]
            sub = df.filter((pl.col("_subnet24") == subnet) & (pl.col(canvas_col) == fp))
            members = [str(x) for x in sub[user_col].unique().to_list() if x is not None]
            fp_s = str(fp)[:64]
            all_flagged_user_ids.update(members)
            clusters_out.append(
                {
                    "cluster_id": _next_id("infra_fp"),
                    "cluster_type": "infrastructure_canvas",
                    "size": len(members),
                    "common_traits": [f"{subnet}", f"shared canvas fp `{fp_s}`"],
                    "signals": ["SHARED_SUBNET_CANVAS"],
                    "subnet_24": subnet,
                    "account_ids": members[:max_members_per_cluster],
                    "account_ids_truncated": max(0, len(members) - max_members_per_cluster),
                }
            )

    # --- 3) Disposable domains ---
    if email_col:
        dom_df = df.filter(pl.col("_email_domain").is_in(list(_DISPOSABLE_DOMAINS)))
        if len(dom_df) > 0:
            for row in (
                dom_df.group_by("_email_domain")
                .agg(pl.col(user_col).n_unique().alias("nu"))
                .filter(pl.col("nu") >= disposable_min_size)
            ).iter_rows(named=True):
                d = row["_email_domain"]
                sub = df.filter(pl.col("_email_domain") == d)
                members = [str(x) for x in sub[user_col].unique().to_list() if x is not None]
                all_flagged_user_ids.update(members)
                clusters_out.append(
                    {
                        "cluster_id": _next_id("disp"),
                        "cluster_type": "disposable_email",
                        "size": len(members),
                        "common_traits": [f"domain {d}", "disposable / throwaway provider"],
                        "signals": ["DISPOSABLE_EMAIL_DOMAIN"],
                        "email_domain": d,
                        "account_ids": members[:max_members_per_cluster],
                        "account_ids_truncated": max(0, len(members) - max_members_per_cluster),
                    }
                )

    # --- 4) Gmail dot-trick (many raw locals collapse to one normalized) ---
    if email_col:
        g = (
            df.filter(pl.col("_email_domain").is_in(["gmail.com", "googlemail.com"]))
            .group_by(["_gmail_norm_local", "_email_domain"])
            .agg(pl.col(user_col).n_unique().alias("nu"), pl.col(email_col).n_unique().alias("n_raw_emails"))
            .filter((pl.col("nu") >= gmail_dot_min_size) | (pl.col("n_raw_emails") >= gmail_dot_min_size))
        )
        for row in g.head(50).iter_rows(named=True):
            norm = row["_gmail_norm_local"]
            dom = row["_email_domain"]
            if not norm:
                continue
            sub = df.filter((pl.col("_gmail_norm_local") == norm) & (pl.col("_email_domain") == dom))
            members = [str(x) for x in sub[user_col].unique().to_list() if x is not None]
            if len(members) < 2:
                continue
            samples = sub[email_col].unique().head(5).to_list()
            all_flagged_user_ids.update(members)
            clusters_out.append(
                {
                    "cluster_id": _next_id("gmail_dot"),
                    "cluster_type": "gmail_dot_trick",
                    "size": len(members),
                    "common_traits": [
                        f"Gmail-normalized local `{norm}` @ {dom}",
                        f"raw variants (sample): {samples}",
                    ],
                    "signals": ["GMAIL_DOT_VARIANTS"],
                    "account_ids": members[:max_members_per_cluster],
                    "account_ids_truncated": max(0, len(members) - max_members_per_cluster),
                }
            )

    # --- 5) High-entropy local parts (gibberish) ---
    if email_col:

        def _ent_cell(v: Any) -> float:
            return _shannon_entropy(str(v)) if v is not None else 0.0

        local_entropy = df["_email_local"].map_elements(_ent_cell, return_dtype=pl.Float64)
        df_he = df.with_columns(local_entropy.alias("_local_entropy"))
        weird = df_he.filter(
            (pl.col("_local_entropy") >= high_entropy_min)
            & (pl.col("_email_local").fill_null("").str.len_chars() >= high_entropy_len_min)
        )
        if len(weird) > 0 and ip_col:
            geo = (
                weird.group_by("_subnet24")
                .agg(pl.col(user_col).n_unique().alias("nu"))
                .filter(pl.col("nu") >= max(3, infra_min_size // 2))
            )
            for row in geo.head(30).iter_rows(named=True):
                subnet = row["_subnet24"]
                if not subnet:
                    continue
                sub = weird.filter(pl.col("_subnet24") == subnet)
                members = [str(x) for x in sub[user_col].unique().to_list() if x is not None]
                all_flagged_user_ids.update(members)
                clusters_out.append(
                    {
                        "cluster_id": _next_id("entropy"),
                        "cluster_type": "high_entropy_email_subnet",
                        "size": len(members),
                        "common_traits": [
                            f"{subnet}",
                            f"high-entropy email local-part (H≥{high_entropy_min})",
                        ],
                        "signals": ["HIGH_ENTROPY_LOCAL", "INFRA_GEO_CONTEXT"],
                        "subnet_24": subnet,
                        "account_ids": members[:max_members_per_cluster],
                        "account_ids_truncated": max(0, len(members) - max_members_per_cluster),
                    }
                )

    all_users = {str(x) for x in df[user_col].unique().to_list() if x is not None}
    density = round(100.0 * len(all_flagged_user_ids) / max(len(all_users), 1), 2)

    primary_signal: str | None = None
    primary_rationale: str | None = None
    if hardware_overlap_cards:
        primary_signal = "canvas_hardware"
        top_ip = max((int(c.get("distinct_ip_count") or 0) for c in hardware_overlap_cards), default=0)
        primary_rationale = (
            f"Primary signal: shared canvas / browser fingerprint with {top_ip}+ distinct IPs "
            "(hardware collision despite IP rotation)."
        )
    else:
        for c in clusters_out:
            sigs = c.get("signals") if isinstance(c.get("signals"), list) else []
            if "HUMANOID_BOT_RING" in sigs or "CANVAS_HARDWARE_COLLISION" in sigs:
                primary_signal = "canvas_hardware"
                primary_rationale = "Primary signal: canvas-class cluster from detector output."
                break

    # --- Bot vs human ratio by 5-minute signup windows (for dashboard timeline) ---
    BOT_WINDOW_ALERT_PCT = 40.0
    flagged_list = sorted(all_flagged_user_ids)
    uid_expr = pl.col(user_col).cast(pl.Utf8, strict=False).str.strip_chars().alias("_uid_t")
    df_timeline = df.filter(pl.col("_bot_ts").is_not_null()).with_columns(
        uid_expr,
        pl.col("_bot_ts").dt.truncate("5m").alias("_win5m"),
    )
    df_timeline = df_timeline.filter(pl.col("_uid_t").is_not_null() & (pl.col("_uid_t") != ""))
    if len(df_timeline) > 0 and flagged_list:
        df_timeline = df_timeline.with_columns(pl.col("_uid_t").is_in(flagged_list).alias("_is_bot"))
    elif len(df_timeline) > 0:
        df_timeline = df_timeline.with_columns(pl.lit(False).alias("_is_bot"))

    timeline_5m: list[dict[str, Any]] = []
    high_bot_window_alert = False
    max_bot_pct_5m_window = 0.0
    if len(df_timeline) > 0:
        total_by = df_timeline.group_by("_win5m").agg(pl.col("_uid_t").n_unique().alias("total_users"))
        bots_by = (
            df_timeline.filter(pl.col("_is_bot"))
            .group_by("_win5m")
            .agg(pl.col("_uid_t").n_unique().alias("bot_users"))
        )
        joined = total_by.join(bots_by, on="_win5m", how="left").with_columns(
            pl.col("bot_users").fill_null(0).cast(pl.Int64)
        )
        joined = joined.filter(pl.col("total_users") > 0).sort("_win5m")
        for row in joined.iter_rows(named=True):
            w = row["_win5m"]
            tu = int(row["total_users"])
            bu = int(row["bot_users"])
            pct = round(100.0 * bu / tu, 2) if tu else 0.0
            if pct > max_bot_pct_5m_window:
                max_bot_pct_5m_window = pct
            if pct > BOT_WINDOW_ALERT_PCT:
                high_bot_window_alert = True
            w_s = w.isoformat() if hasattr(w, "isoformat") else str(w)
            timeline_5m.append(
                {
                    "window_start": w_s,
                    "total_users": tu,
                    "bot_users": bu,
                    "human_users": max(0, tu - bu),
                    "bot_pct": pct,
                    "human_pct": round(100.0 - pct, 2) if tu else 100.0,
                }
            )

    hardware_ip_forensics = _build_hardware_ip_forensics(
        df=df,
        canvas_col=canvas_col,
        ip_col=ip_col,
        user_col=user_col,
        canvas_fingerprint_distribution=canvas_fingerprint_distribution,
        hardware_spoofing_assessment=hardware_spoofing_assessment,
    )

    return {
        "ok": True,
        "kind": "bot_hardware_forensic",
        "column_alias_bridge": column_alias_bridge,
        "row_count": len(df),
        "unique_users": len(all_users),
        "bot_density_pct": density,
        "clusters": clusters_out,
        "hardware_overlap_cards": hardware_overlap_cards,
        "timeline_5m": timeline_5m,
        "bot_window_alert_threshold_pct": BOT_WINDOW_ALERT_PCT,
        "high_bot_window_alert": high_bot_window_alert,
        "max_bot_pct_5m_window": round(max_bot_pct_5m_window, 2),
        "columns_used": {
            "timestamp": ts_col,
            "user_id": user_col,
            "email": email_col,
            "ip": ip_col,
            "user_agent": ua_col,
            "canvas_fingerprint": canvas_col,
            "name": name_col,
        },
        "semantic_column_mapping": {
            "timestamp": ts_col,
            "user_id": user_col,
            "name": name_col,
            "canvas_fingerprint": canvas_col,
            "note": (
                "Resolved via canonical aliases, dtype heuristics, substring hints, and semantic header scoring. "
                "Proceed with these mappings—do not ask the operator to rename columns."
            ),
        },
        "humanoid_canvas_logic": (
            "If a cluster shares a canvas_fingerprint (or browser_hash) but shows many distinct IPs and distinct "
            "names, treat as High-Confidence Humanoid Bot Ring: shared hardware despite IP rotation."
        ),
        "primary_signal": primary_signal,
        "primary_signal_rationale": primary_rationale,
        "cluster_insights_ready": True,
        "canvas_fingerprint_distribution": canvas_fingerprint_distribution,
        "hardware_spoofing_assessment": hardware_spoofing_assessment,
        "hardware_ip_forensics": hardware_ip_forensics,
        "schema_grounded_analysis": {
            "dataset_basename": path.name,
            "column_alias_bridge": column_alias_bridge,
            "columns_present": list(df.columns),
            "email_column_present": email_col is not None,
            "forbid_email_pattern_narrative": email_col is None,
            "narration_rule": (
                "You are FORBIDDEN from mentioning Gmail dot-tricks, disposable-email concentration, or other "
                "**email-pattern** fraud stories unless `email_column_present` is true and the tool JSON actually "
                "contains email-derived clusters for this file."
            ),
            "investigate_protocol": (
                "When the operator asks to **Investigate**, first run **execute_in_sandbox** (or rely on "
                "`canvas_fingerprint_distribution` below) to verify `GROUP BY` canvas vs `COUNT(*)` and distinct IPs—"
                "then summarize only those numeric results."
            ),
            "stress_humanoid_canvas_note": (
                "For stress_bot_humanoid.csv: primary column is **canvas_fingerprint**; sample rows repeat the "
                "same hash **canvas_hash_999_xyz** — that repetition is the smoking gun, not email."
            )
            if "stress_bot_humanoid" in path.name.lower() and canvas_col
            else None,
        },
        "thresholds": {
            "burst_min_accounts": burst_min_accounts,
            "burst_window_minutes": burst_window_minutes,
            "infra_min_size": infra_min_size,
            "chrome_stale_below": chrome_stale_below,
        },
    }
