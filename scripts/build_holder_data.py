#!/usr/bin/env python3
"""Build static holder-structure datasets from verified report snapshots."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "scripts" / "data" / "holder-structure-source.csv"
JSON_PATH = ROOT / "public" / "data" / "holder-structure.json"
CSV_PATH = ROOT / "public" / "data" / "holder-structure.csv"

AGGREGATE_FUND_ORDER = ("510300", "510310", "510330", "159919")
STANDALONE_FUND_ORDER = ("159915",)
FUND_ORDER = AGGREGATE_FUND_ORDER + STANDALONE_FUND_ORDER
CATEGORY_ORDER = ("national_team", "other_institution", "individual")
SOURCE_KINDS = {
    "manager_official_pdf",
    "csrc_official_pdf",
    "public_report_mirror",
}
CATEGORIES = {
    "national_team": {
        "label": "国家队（已识别）",
        "short_label": "国家队",
        "color": "#c95929",
        "line_dash": "solid",
        "precision": "lower_bound",
        "precision_label": "前十大持有人中已识别下限；未识别时留空",
    },
    "other_institution": {
        "label": "其他机构（含保险）",
        "short_label": "其他机构",
        "color": "#234a6f",
        "line_dash": "dash",
        "precision": "upper_bound",
        "precision_label": "扣除已识别国家队后的上限",
    },
    "individual": {
        "label": "个人",
        "short_label": "个人",
        "color": "#287d72",
        "line_dash": "dot",
        "precision": "exact",
        "precision_label": "报告原表精确值",
    },
}


def parse_decimal(row: dict[str, str], field: str, *, allow_zero: bool = False) -> Decimal:
    value = Decimal(row[field])
    if value < 0 or (value == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(
            f"{row['fund_code']} {row['period_end']}: {field} must be {qualifier}"
        )
    return value


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def shares_100m(value: Decimal) -> float:
    return float(round(value / Decimal(100_000_000), 6))


def ratio_pct(value: Decimal, total: Decimal) -> float:
    return float(round(value / total * Decimal(100), 6))


def row_precision(row: dict[str, Any], category: str) -> tuple[str, str]:
    if category == "national_team":
        if row["national_team_status"] == "not_identified":
            return "not_identified", "前十大持有人未识别到国家队，不代表持仓为零"
        return "lower_bound", "前十大持有人中已识别国家队下限"
    if category == "other_institution":
        if row["national_team_status"] == "not_identified":
            return (
                "includes_unidentified_national_team",
                "包含未进入前十或未识别的国家队持仓，为其他机构上限",
            )
        return "upper_bound", "扣除已识别国家队后的其他机构上限"
    return "exact", "报告原表精确值"


def category_value(row: dict[str, Any], category: str) -> Decimal | None:
    if category == "national_team" and row["national_team_status"] == "not_identified":
        return None
    return row["categories"][category]


def load_rows() -> list[dict[str, Any]]:
    with SOURCE_PATH.open(encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_rows:
        code = raw["fund_code"]
        period = raw["period_end"]
        date.fromisoformat(period)
        date.fromisoformat(raw["report_send_date"])
        date.fromisoformat(raw["official_upload_date"])
        if code not in FUND_ORDER:
            raise ValueError(f"unexpected fund code: {code}")
        if (code, period) in seen:
            raise ValueError(f"duplicate holder point: {code} {period}")
        if raw["source_kind"] not in SOURCE_KINDS:
            raise ValueError(f"unsupported source kind: {raw['source_kind']}")
        seen.add((code, period))

        total = parse_decimal(raw, "total_shares")
        institution = parse_decimal(raw, "comparable_institution_shares")
        individual = parse_decimal(raw, "individual_shares")
        feeder = parse_decimal(raw, "feeder_shares", allow_zero=True)
        national_team = parse_decimal(
            raw, "identified_national_team_shares", allow_zero=True
        )
        national_count = int(raw["identified_national_team_account_count"])
        national_status = raw["national_team_status"]
        if institution + individual + feeder != total:
            raise ValueError(f"holder categories do not close: {code} {period}")
        if national_team > institution:
            raise ValueError(f"national-team shares exceed institutions: {code} {period}")
        if national_status == "lower_bound":
            if national_team <= 0 or national_count <= 0:
                raise ValueError(f"invalid identified national-team point: {code} {period}")
        elif national_status == "not_identified":
            if national_team != 0 or national_count != 0:
                raise ValueError(f"unidentified national-team point is not empty: {code} {period}")
        else:
            raise ValueError(f"unsupported national-team status: {code} {period}")

        rows.append(
            {
                **raw,
                "total_shares": total,
                "comparable_institution_shares": institution,
                "individual_shares": individual,
                "feeder_shares": feeder,
                "identified_national_team_shares": national_team,
                "identified_national_team_account_count": national_count,
                "holder_table_page": int(raw["holder_table_page"]),
                "national_team_status": national_status,
                "categories": {
                    "national_team": national_team,
                    "other_institution": institution - national_team,
                    "individual": individual,
                },
            }
        )

    if {row["fund_code"] for row in rows} != set(FUND_ORDER):
        raise ValueError("holder source is missing one or more configured funds")
    return sorted(rows, key=lambda row: (row["period_end"], FUND_ORDER.index(row["fund_code"])))


def category_series(
    aligned_rows: list[dict[str, Any] | None], category: str
) -> dict[str, list[Any]]:
    shares: list[float | None] = []
    ratios: list[float | None] = []
    precision: list[str | None] = []
    precision_labels: list[str | None] = []
    for row in aligned_rows:
        if row is None:
            shares.append(None)
            ratios.append(None)
            precision.append(None)
            precision_labels.append(None)
            continue
        value = category_value(row, category)
        status, label = row_precision(row, category)
        shares.append(shares_100m(value) if value is not None else None)
        ratios.append(ratio_pct(value, row["total_shares"]) if value is not None else None)
        precision.append(status)
        precision_labels.append(label)
    return {
        "shares_100m": shares,
        "ratio_pct": ratios,
        "precision": precision,
        "precision_labels": precision_labels,
    }


def aggregate_series(
    periods: list[str], by_period: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    totals: list[Decimal | None] = []
    member_counts: list[int] = []
    category_values: dict[str, list[Decimal | None]] = {
        category: [] for category in CATEGORY_ORDER
    }
    category_precision: dict[str, list[str | None]] = {
        category: [] for category in CATEGORY_ORDER
    }
    category_labels: dict[str, list[str | None]] = {
        category: [] for category in CATEGORY_ORDER
    }

    for period in periods:
        active = [
            row for row in by_period[period] if row["fund_code"] in AGGREGATE_FUND_ORDER
        ]
        member_counts.append(len(active))
        if not active:
            totals.append(None)
            for category in CATEGORY_ORDER:
                category_values[category].append(None)
                category_precision[category].append(None)
                category_labels[category].append(None)
            continue

        total = sum((row["total_shares"] for row in active), Decimal(0))
        totals.append(total)
        national_complete = all(
            row["national_team_status"] == "lower_bound" for row in active
        )
        for category in CATEGORY_ORDER:
            if category == "national_team" and not national_complete:
                category_values[category].append(None)
                category_precision[category].append("not_identified")
                category_labels[category].append(
                    "至少一只成分ETF的前十大持有人未识别到国家队，汇总留空"
                )
                continue
            value = sum((row["categories"][category] for row in active), Decimal(0))
            category_values[category].append(value)
            if category == "other_institution" and not national_complete:
                category_precision[category].append("includes_unidentified_national_team")
                category_labels[category].append(
                    "包含未进入前十或未识别的国家队持仓，为其他机构汇总上限"
                )
            else:
                status, label = row_precision(active[0], category)
                category_precision[category].append(status)
                category_labels[category].append(label)

    aggregate: dict[str, Any] = {
        "member_counts": member_counts,
        "total_shares_100m": [
            shares_100m(value) if value is not None else None for value in totals
        ],
        "categories": {},
    }
    for category in CATEGORY_ORDER:
        values = category_values[category]
        aggregate["categories"][category] = {
            "shares_100m": [
                shares_100m(value) if value is not None else None for value in values
            ],
            "ratio_pct": [
                ratio_pct(value, total)
                if value is not None and total is not None
                else None
                for value, total in zip(values, totals)
            ],
            "precision": category_precision[category],
            "precision_labels": category_labels[category],
        }
    return aggregate


def build_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_code[row["fund_code"]].append(row)
        by_period[row["period_end"]].append(row)

    periods = sorted(by_period)
    funds = [{"code": code, "name": by_code[code][0]["fund_name"]} for code in FUND_ORDER]
    series: dict[str, Any] = {}
    for code in FUND_ORDER:
        rows_by_period = {row["period_end"]: row for row in by_code[code]}
        aligned_rows = [rows_by_period.get(period) for period in periods]
        series[code] = {
            "report_count": len(by_code[code]),
            "first_report_period": min(rows_by_period),
            "total_shares_100m": [
                shares_100m(row["total_shares"]) if row is not None else None
                for row in aligned_rows
            ],
            "categories": {
                category: category_series(aligned_rows, category)
                for category in CATEGORY_ORDER
            },
        }

    source_counts = Counter(row["source_kind"] for row in rows)
    latest_disclosure = max(row["official_upload_date"] for row in rows)
    return {
        "schema_version": "2.0",
        "metadata": {
            "start_period": periods[0],
            "latest_period": periods[-1],
            "latest_disclosure_date": latest_disclosure,
            "period_count": len(periods),
            "report_count": len(rows),
            "reports_per_fund": {
                code: len(by_code[code]) for code in FUND_ORDER
            },
            "source_kind_counts": dict(sorted(source_counts.items())),
            "disclosure_frequency": "semiannual",
            "source_name": "基金管理人官网、中国证监会统一信息披露平台及公开原报告镜像",
            "source_url": "http://eid.csrc.gov.cn/fund/",
            "aggregate_fund_codes": list(AGGREGATE_FUND_ORDER),
            "standalone_fund_codes": list(STANDALONE_FUND_ORDER),
            "q1_2026_holder_data_available": False,
            "national_team_definition": "定期报告前十名持有人中明确命名的中央汇金和中国证券金融账户合计",
            "national_team_missing_note": "未进入前十大或未识别到国家队时留空，不记为零",
            "other_institution_definition": "可比机构份额扣除已识别国家队份额，包含保险、券商、银行、资管等，不含ETF联接基金；国家队未识别期为上限",
            "aggregate_definition": "四只沪深300ETF在各报告期可用成员的原始份额直接相加，占比为合计分类份额除以合计总份额；159915仅单独展示，不进入汇总",
            "connection_line_note": "连接线仅辅助观察中报和年报披露点次序，不代表半年内连续持仓路径",
        },
        "categories": CATEGORIES,
        "periods": periods,
        "funds": funds,
        "series": series,
        "aggregate": aggregate_series(periods, by_period),
        "reports": [
            {
                "fund_code": row["fund_code"],
                "period_end": row["period_end"],
                "report_type": row["report_type"],
                "report_send_date": row["report_send_date"],
                "official_upload_date": row["official_upload_date"],
                "instance_id": row["instance_id"],
                "official_pdf_url": row["official_pdf_url"],
                "source_kind": row["source_kind"],
                "crosscheck_url": row["crosscheck_url"],
                "holder_table_page": row["holder_table_page"],
                "source_page_numbers": row["source_page_numbers"],
                "national_team_status": row["national_team_status"],
                "national_team_account_count": row[
                    "identified_national_team_account_count"
                ],
            }
            for row in rows
        ],
    }


def write_public_csv(rows: list[dict[str, Any]]) -> None:
    fields = (
        "period_end",
        "fund_code",
        "fund_name",
        "category",
        "category_label",
        "holder_shares",
        "holder_shares_100m",
        "holder_ratio_pct",
        "precision_status",
        "total_shares",
        "report_send_date",
        "official_upload_date",
        "instance_id",
        "source_kind",
        "holder_table_page",
        "official_pdf_url",
        "crosscheck_url",
    )
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            for category in CATEGORY_ORDER:
                shares = category_value(row, category)
                precision, _ = row_precision(row, category)
                writer.writerow(
                    {
                        "period_end": row["period_end"],
                        "fund_code": row["fund_code"],
                        "fund_name": row["fund_name"],
                        "category": category,
                        "category_label": CATEGORIES[category]["label"],
                        "holder_shares": decimal_text(shares) if shares is not None else "",
                        "holder_shares_100m": (
                            f"{shares_100m(shares):.6f}" if shares is not None else ""
                        ),
                        "holder_ratio_pct": (
                            f"{ratio_pct(shares, row['total_shares']):.6f}"
                            if shares is not None
                            else ""
                        ),
                        "precision_status": precision,
                        "total_shares": decimal_text(row["total_shares"]),
                        "report_send_date": row["report_send_date"],
                        "official_upload_date": row["official_upload_date"],
                        "instance_id": row["instance_id"],
                        "source_kind": row["source_kind"],
                        "holder_table_page": row["holder_table_page"],
                        "official_pdf_url": row["official_pdf_url"],
                        "crosscheck_url": row["crosscheck_url"],
                    }
                )


def main() -> None:
    rows = load_rows()
    payload = build_payload(rows)
    JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_public_csv(rows)
    print(
        f"Wrote {JSON_PATH.relative_to(ROOT)} and {CSV_PATH.relative_to(ROOT)} "
        f"from {len(rows)} verified report points"
    )


if __name__ == "__main__":
    main()
