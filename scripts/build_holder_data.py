#!/usr/bin/env python3
"""Build static holder-structure datasets from verified report snapshots."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "scripts" / "data" / "holder-structure-source.csv"
JSON_PATH = ROOT / "public" / "data" / "holder-structure.json"
CSV_PATH = ROOT / "public" / "data" / "holder-structure.csv"

FUND_ORDER = ("510300", "510310", "510330", "159919")
CATEGORY_ORDER = ("national_team", "other_institution", "individual")
CATEGORIES = {
    "national_team": {
        "label": "国家队（已识别）",
        "short_label": "国家队",
        "color": "#c95929",
        "line_dash": "solid",
        "precision": "lower_bound",
        "precision_label": "已识别下限",
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


def parse_positive_int(row: dict[str, str], field: str) -> int:
    value = int(row[field])
    if value <= 0:
        raise ValueError(f"{row['fund_code']} {row['period_end']}: {field} must be positive")
    return value


def shares_100m(value: int) -> float:
    return round(value / 100_000_000, 6)


def ratio_pct(value: int, total: int) -> float:
    return round(value / total * 100, 6)


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
        seen.add((code, period))

        total = parse_positive_int(raw, "total_shares")
        institution = parse_positive_int(raw, "comparable_institution_shares")
        individual = parse_positive_int(raw, "individual_shares")
        feeder = parse_positive_int(raw, "feeder_shares")
        national_team = parse_positive_int(raw, "identified_national_team_shares")
        if institution + individual + feeder != total:
            raise ValueError(f"holder categories do not close: {code} {period}")
        if national_team > institution:
            raise ValueError(f"national-team shares exceed institutions: {code} {period}")
        if raw["national_team_status"] != "lower_bound":
            raise ValueError(f"unsupported national-team status: {code} {period}")

        other_institution = institution - national_team
        rows.append(
            {
                **raw,
                "total_shares": total,
                "comparable_institution_shares": institution,
                "individual_shares": individual,
                "feeder_shares": feeder,
                "identified_national_team_shares": national_team,
                "identified_national_team_account_count": int(
                    raw["identified_national_team_account_count"]
                ),
                "holder_table_page": int(raw["holder_table_page"]),
                "categories": {
                    "national_team": national_team,
                    "other_institution": other_institution,
                    "individual": individual,
                },
            }
        )

    periods = sorted({row["period_end"] for row in rows})
    expected = {(code, period) for code in FUND_ORDER for period in periods}
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise ValueError(f"incomplete holder panel; missing={missing}, extra={extra}")
    return sorted(rows, key=lambda row: (row["period_end"], FUND_ORDER.index(row["fund_code"])))


def category_series(rows: list[dict[str, Any]], category: str) -> dict[str, list[Any]]:
    shares = [row["categories"][category] for row in rows]
    totals = [row["total_shares"] for row in rows]
    precision = CATEGORIES[category]["precision"]
    return {
        "shares_100m": [shares_100m(value) for value in shares],
        "ratio_pct": [ratio_pct(value, total) for value, total in zip(shares, totals)],
        "precision": [precision] * len(rows),
    }


def build_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_period: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_code[row["fund_code"]].append(row)
        by_period[row["period_end"]].append(row)

    periods = sorted(by_period)
    funds = [
        {"code": code, "name": by_code[code][0]["fund_name"]}
        for code in FUND_ORDER
    ]
    series: dict[str, Any] = {}
    for code in FUND_ORDER:
        fund_rows = sorted(by_code[code], key=lambda row: row["period_end"])
        series[code] = {
            "total_shares_100m": [shares_100m(row["total_shares"]) for row in fund_rows],
            "categories": {
                category: category_series(fund_rows, category)
                for category in CATEGORY_ORDER
            },
        }

    aggregate_totals: list[int] = []
    aggregate_categories: dict[str, list[int]] = {
        category: [] for category in CATEGORY_ORDER
    }
    for period in periods:
        period_rows = by_period[period]
        total = sum(row["total_shares"] for row in period_rows)
        aggregate_totals.append(total)
        for category in CATEGORY_ORDER:
            aggregate_categories[category].append(
                sum(row["categories"][category] for row in period_rows)
            )

    aggregate = {
        "total_shares_100m": [shares_100m(value) for value in aggregate_totals],
        "categories": {},
    }
    for category in CATEGORY_ORDER:
        values = aggregate_categories[category]
        aggregate["categories"][category] = {
            "shares_100m": [shares_100m(value) for value in values],
            "ratio_pct": [
                ratio_pct(value, total)
                for value, total in zip(values, aggregate_totals)
            ],
            "precision": [CATEGORIES[category]["precision"]] * len(periods),
        }

    latest_disclosure = max(row["official_upload_date"] for row in rows)
    return {
        "schema_version": "1.0",
        "metadata": {
            "start_period": periods[0],
            "latest_period": periods[-1],
            "latest_disclosure_date": latest_disclosure,
            "period_count": len(periods),
            "report_count": len(rows),
            "disclosure_frequency": "semiannual",
            "source_name": "中国证监会资本市场统一信息披露平台",
            "source_url": "http://eid.csrc.gov.cn/fund/",
            "q1_2026_holder_data_available": False,
            "national_team_definition": "定期报告前十名持有人中明确命名的中央汇金和中国证券金融账户合计",
            "other_institution_definition": "可比机构份额扣除已识别国家队份额，包含保险、券商、银行、资管等，不含ETF联接基金",
            "aggregate_definition": "四只基金报告原始份额直接相加，占比为合计分类份额除以合计总份额，不代表资产金额",
            "connection_line_note": "连接线仅辅助观察中报和年报披露点次序，不代表半年内连续持仓路径",
        },
        "categories": CATEGORIES,
        "periods": periods,
        "funds": funds,
        "series": series,
        "aggregate": aggregate,
        "reports": [
            {
                "fund_code": row["fund_code"],
                "period_end": row["period_end"],
                "report_type": row["report_type"],
                "report_send_date": row["report_send_date"],
                "official_upload_date": row["official_upload_date"],
                "instance_id": row["instance_id"],
                "official_pdf_url": row["official_pdf_url"],
                "holder_table_page": row["holder_table_page"],
                "source_page_numbers": row["source_page_numbers"],
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
        "holder_table_page",
        "official_pdf_url",
    )
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            for category in CATEGORY_ORDER:
                shares = row["categories"][category]
                writer.writerow(
                    {
                        "period_end": row["period_end"],
                        "fund_code": row["fund_code"],
                        "fund_name": row["fund_name"],
                        "category": category,
                        "category_label": CATEGORIES[category]["label"],
                        "holder_shares": shares,
                        "holder_shares_100m": f"{shares_100m(shares):.6f}",
                        "holder_ratio_pct": f"{ratio_pct(shares, row['total_shares']):.6f}",
                        "precision_status": CATEGORIES[category]["precision"],
                        "total_shares": row["total_shares"],
                        "report_send_date": row["report_send_date"],
                        "official_upload_date": row["official_upload_date"],
                        "instance_id": row["instance_id"],
                        "holder_table_page": row["holder_table_page"],
                        "official_pdf_url": row["official_pdf_url"],
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
