"""Load and validate the hand-curated override tables in pit/overrides/.

Every table must have its required columns, parseable dates, no duplicate keys and a non-empty
`source` (a URL, an evidence path, or the literal PENDING which acceptance test M2 reports)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import OVERRIDES

SCHEMAS: dict[str, dict] = {
    "membership_name_overrides": {"cols": ["constituent_ric", "constituent_name", "instrument", "reason", "source"],
                                  "key": ["constituent_ric", "constituent_name"], "dates": []},
    "membership_isin_substitutions": {"cols": ["from_isin", "to_isin", "valid_from", "valid_to", "applies_to", "reason", "source"],
                                      "key": ["from_isin", "valid_from"], "dates": []},
    "membership_alias_dedup": {"cols": ["keep_ric", "drop_ric", "before_date", "reason", "source"],
                               "key": ["drop_ric"], "dates": ["before_date"]},
    "membership_change_isin_overrides": {"cols": ["constituent_ric", "date", "isin", "reason", "source"],
                                         "key": ["constituent_ric", "date"], "dates": ["date"]},
    "extra_membership_events": {"cols": ["date", "isin", "change", "reason", "source"],
                                "key": ["date", "isin", "change"], "dates": ["date"]},
    "membership_probe_explanations": {"cols": ["date", "replay_isin", "probe_isin", "reason", "source"],
                                      "key": ["date", "replay_isin", "probe_isin"], "dates": ["date"]},
    "listing_transfers": {"cols": ["isin", "primary_ric", "alias_ric", "transfer_session", "adjudication", "source"],
                          "key": ["isin"], "dates": ["transfer_session"]},
    "ric_isin_dated": {"cols": ["ric", "isin", "valid_from", "valid_to", "reason", "source"],
                       "key": ["ric", "valid_from"], "dates": ["valid_from", "valid_to"]},
    "member_session_exceptions": {"cols": ["session", "isin", "rics", "event_type", "source", "has_valid_lseg_ohlcv",
                                            "position_settlement_validated"], "key": ["session", "isin"], "dates": ["session"]},
    "manual_settlement_terms": {"cols": ["ric", "outcome", "completion_date", "cash_per_share", "successor_name",
                                          "successor_shares_per_share", "other_consideration", "election_note", "source"],
                                 "key": ["ric", "completion_date"], "dates": ["completion_date"]},
    "membership_probe_assertions": {"cols": ["date", "ric", "expected_member", "min_rows", "reason", "source"],
                                    "key": ["date", "ric"], "dates": ["date"]},
    "roster_link_confirmations": {"cols": ["ivv_line", "replay_isin", "cik", "evidence", "source", "confirmed_on"],
                                  "key": ["replay_isin"], "dates": ["confirmed_on"]},
}


class OverrideError(ValueError):
    pass


def load(name: str, directory: Path = OVERRIDES) -> pd.DataFrame:
    if name not in SCHEMAS:
        raise OverrideError(f"unknown override table {name!r}")
    spec = SCHEMAS[name]
    path = Path(directory) / f"{name}.csv"
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in spec["cols"] if c not in df.columns]
    if missing:
        raise OverrideError(f"{path.name}: missing columns {missing}")
    if (df["source"].str.strip() == "").any():
        raise OverrideError(f"{path.name}: rows without a source")
    for c in spec["dates"]:
        bad = pd.to_datetime(df[c], errors="coerce").isna()
        if bad.any():
            raise OverrideError(f"{path.name}: unparseable {c} in rows {list(df.index[bad])}")
    if df.duplicated(spec["key"]).any():
        raise OverrideError(f"{path.name}: duplicate keys {spec['key']}")
    if "change" in df.columns and not df["change"].isin(["Joiner", "Leaver"]).all():
        raise OverrideError(f"{path.name}: change must be Joiner or Leaver")
    return df


def pending_sources() -> list[dict]:
    """Rows across all tables whose source is still PENDING (reported by acceptance test M2)."""
    out = []
    for name in SCHEMAS:
        df = load(name)
        for _, r in df[df["source"].str.upper().eq("PENDING")].iterrows():
            out.append({"table": name, **{k: r[k] for k in df.columns if k != "source"}})
    return out
