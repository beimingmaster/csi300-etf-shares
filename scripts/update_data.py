#!/usr/bin/env python3
"""Refresh 10 years of official daily share data for four major CSI 300 ETFs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "public" / "data"
CSV_PATH = DATA_DIR / "etf-shares.csv"
JSON_PATH = DATA_DIR / "etf-shares.json"

SSE_URL = "https://query.sse.com.cn/commonQuery.do"
SZSE_URL = "https://www.szse.cn/api/report/ShowReport/data"
CSI_INDEX_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
SSE_SQL_ID = "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"
CSI300_CODE = "000300"
CSI300_NAME = "沪深300指数"
TIMEZONE = ZoneInfo("Asia/Shanghai")
THREAD_LOCAL = threading.local()

LOOKBACK_YEARS = 10
REFRESH_DAYS = 21
SSE_WORKERS = 4
SSE_CHECKPOINT_SIZE = 40
SZSE_CHUNK_DAYS = 170


@dataclass(frozen=True)
class Fund:
    code: str
    name: str
    manager: str
    exchange: str
    rank: int
    color: str
    line_dash: str


FUNDS = (
    Fund(
        code="510300",
        name="沪深300ETF华泰柏瑞",
        manager="华泰柏瑞基金管理有限公司",
        exchange="上交所",
        rank=1,
        color="#234a6f",
        line_dash="solid",
    ),
    Fund(
        code="510310",
        name="沪深300ETF易方达",
        manager="易方达基金管理有限公司",
        exchange="上交所",
        rank=2,
        color="#c85f2c",
        line_dash="dash",
    ),
    Fund(
        code="510330",
        name="沪深300ETF华夏",
        manager="华夏基金管理有限公司",
        exchange="上交所",
        rank=3,
        color="#287d72",
        line_dash="dashdot",
    ),
    Fund(
        code="159919",
        name="沪深300ETF嘉实",
        manager="嘉实基金管理有限公司",
        exchange="深交所",
        rank=4,
        color="#a74747",
        line_dash="dot",
    ),
)
FUND_BY_CODE = {fund.code: fund for fund in FUNDS}
SSE_CODES = {fund.code for fund in FUNDS if fund.exchange == "上交所"}
SZSE_CODES = {fund.code for fund in FUNDS if fund.exchange == "深交所"}
KNOWN_UNAVAILABLE_SHARE_DATES = {
    ("159919", date(2016, 8, 1)),
    ("159919", date(2016, 8, 2)),
}
KNOWN_LARGE_MOVES = {
    ("510310", date(2024, 9, 20)): {
        "type": "fund_share_consolidation",
        "label": "基金份额合并",
        "review_status": "verified",
        "source_name": "易方达基金管理有限公司份额合并结果公告",
        "source_url": (
            "https://cdn.efunds.com.cn/owch/data/bulletin/20240923/"
            "%E6%98%93%E6%96%B9%E8%BE%BE%E5%9F%BA%E9%87%91%E7%AE%A1%E7%90%86"
            "%E6%9C%89%E9%99%90%E5%85%AC%E5%8F%B8%E5%85%B3%E4%BA%8E%E6%98%93"
            "%E6%96%B9%E8%BE%BE%E6%B2%AA%E6%B7%B1300%E4%BA%A4%E6%98%93%E5%9E%8B"
            "%E5%BC%80%E6%94%BE%E5%BC%8F%E6%8C%87%E6%95%B0%E5%8F%91%E8%B5%B7"
            "%E5%BC%8F%E8%AF%81%E5%88%B8%E6%8A%95%E8%B5%84%E5%9F%BA%E9%87%91"
            "%E5%9F%BA%E9%87%91%E4%BB%BD%E9%A2%9D%E5%90%88%E5%B9%B6%E7%BB%93"
            "%E6%9E%9C%E7%9A%84%E5%85%AC%E5%91%8A.pdf?from=person"
        ),
    }
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", help="latest calendar date to consider, YYYY-MM-DD")
    parser.add_argument("--start", help="inclusive requested start date, YYYY-MM-DD")
    parser.add_argument(
        "--refresh-days",
        type=int,
        default=REFRESH_DAYS,
        help="refetch this many recent calendar days",
    )
    parser.add_argument(
        "--seed-csv",
        type=Path,
        help="optional compatible CSV used only to initialize an empty cache",
    )
    return parser.parse_args()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; csi300-etf-shares/1.0)",
            "Accept": "application/json,text/plain,*/*",
        }
    )
    return session


def thread_session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        THREAD_LOCAL.session = make_session()
    return THREAD_LOCAL.session


def get_json(
    session: requests.Session,
    url: str,
    params: dict[str, str],
    referer: str,
    timeout: float = 35.0,
) -> Any:
    response = session.get(
        url,
        params=params,
        headers={"Referer": referer},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def fetch_trading_calendar(start: date, end: date) -> list[date]:
    payload = get_json(
        make_session(),
        CSI_INDEX_URL,
        {
            "indexCode": CSI300_CODE,
            "startDate": start.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d"),
        },
        "https://www.csindex.com.cn/",
    )
    if str(payload.get("code")) != "200":
        raise RuntimeError(f"CSI index API business error: {payload}")
    rows = payload.get("data") or []
    if not rows:
        raise RuntimeError("CSI index API returned no trading dates")

    dates: set[date] = set()
    for row in rows:
        returned_code = str(row.get("indexCode", "")).zfill(6)
        returned_name = str(row.get("indexNameCnAll", ""))
        if returned_code != CSI300_CODE or returned_name != CSI300_NAME:
            raise ValueError(
                "unexpected CSI index identity: "
                f"{returned_code}/{returned_name}"
            )
        trade_date = datetime.strptime(str(row["tradeDate"]), "%Y%m%d").date()
        if not start <= trade_date <= end:
            raise ValueError(f"out-of-range CSI index date: {trade_date}")
        if trade_date in dates:
            raise ValueError(f"duplicate CSI index date: {trade_date}")
        close = float(row["close"])
        if not math.isfinite(close) or close <= 0:
            raise ValueError(f"invalid CSI index close on {trade_date}: {close}")
        dates.add(trade_date)
    return sorted(dates)


def fetch_sse_day(day: date) -> list[dict[str, Any]]:
    payload = get_json(
        thread_session(),
        SSE_URL,
        {
            "isPagination": "true",
            "pageHelp.pageSize": "10000",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": "1",
            "sqlId": SSE_SQL_ID,
            "STAT_DATE": day.isoformat(),
        },
        "https://www.sse.com.cn/",
    )
    values: dict[str, float] = {}
    for item in payload.get("result", []):
        code = str(item.get("SEC_CODE", "")).strip()
        if code in SSE_CODES:
            values[code] = float(str(item["TOT_VOL"]).replace(",", "")) / 10_000
    missing = SSE_CODES - set(values)
    if missing:
        raise ValueError(f"SSE missing {sorted(missing)} on {day}")
    return [
        {
            "date": day,
            "code": code,
            "shares_100m": shares,
            "exchange": "上交所",
            "source": SSE_URL,
        }
        for code, shares in values.items()
    ]


def fetch_sse_dates(dates: list[date]) -> list[dict[str, Any]]:
    if not dates:
        return []
    all_rows: list[dict[str, Any]] = []
    for offset in range(0, len(dates), SSE_CHECKPOINT_SIZE):
        batch = dates[offset : offset + SSE_CHECKPOINT_SIZE]
        failures: list[tuple[date, Exception]] = []
        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=SSE_WORKERS) as executor:
            futures = {executor.submit(fetch_sse_day, day): day for day in batch}
            for future in as_completed(futures):
                day = futures[future]
                try:
                    rows.extend(future.result())
                except Exception as error:
                    failures.append((day, error))
        all_rows.extend(rows)
        completed = min(offset + len(batch), len(dates))
        print(f"SSE {completed}/{len(dates)} trading dates", flush=True)
        if failures:
            day, error = sorted(failures, key=lambda item: item[0])[0]
            raise RuntimeError(
                f"SSE failed for {len(failures)} date(s); first={day}"
            ) from error
        if completed < len(dates):
            time.sleep(0.2)
    return all_rows


def date_chunks(start: date, end: date) -> Iterable[tuple[date, date]]:
    current = start
    while current <= end:
        chunk_end = min(end, current + timedelta(days=SZSE_CHUNK_DAYS - 1))
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def fetch_szse_range(code: str, start: date, end: date) -> list[dict[str, Any]]:
    session = make_session()
    rows: list[dict[str, Any]] = []
    chunks = list(date_chunks(start, end))
    for chunk_index, (chunk_start, chunk_end) in enumerate(chunks, 1):
        page = 1
        while True:
            report_list = get_json(
                session,
                SZSE_URL,
                {
                    "SHOWTYPE": "JSON",
                    "CATALOGID": "scsj_fund_jjgm",
                    "TABKEY": "tab1",
                    "jjlb": "ETF",
                    "txtStart": chunk_start.isoformat(),
                    "txtEnd": chunk_end.isoformat(),
                    "txtDm": code,
                    "PAGENO": str(page),
                    "random": str(time.time()),
                },
                "https://www.szse.cn/market/fund/volume/etf/index.html",
            )
            if not isinstance(report_list, list) or not report_list:
                raise RuntimeError(f"unexpected SZSE response for {code}")
            report = report_list[0]
            if report.get("error"):
                raise RuntimeError(f"SZSE business error for {code}: {report['error']}")
            for item in report.get("data", []):
                if str(item.get("fund_code", "")).strip() != code:
                    continue
                shares = float(str(item["current_size"]).replace(",", "")) / 10_000
                rows.append(
                    {
                        "date": parse_date(str(item["size_date"])),
                        "code": code,
                        "shares_100m": shares,
                        "exchange": "深交所",
                        "source": SZSE_URL,
                    }
                )
            page_count = int(report.get("metadata", {}).get("pagecount") or 0)
            if page >= page_count:
                break
            page += 1
        print(
            f"SZSE {code} {chunk_index}/{len(chunks)} ranges",
            flush=True,
        )
        if chunk_index < len(chunks):
            time.sleep(0.2)
    return rows


def load_rows(path: Path) -> dict[tuple[date, str], dict[str, Any]]:
    if not path.exists():
        return {}
    rows: dict[tuple[date, str], dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            code = str(item.get("code", "")).strip().zfill(6)
            if code not in FUND_BY_CODE:
                continue
            row_date = parse_date(str(item["date"]))
            shares = float(item["shares_100m"])
            fund = FUND_BY_CODE[code]
            rows[(row_date, code)] = {
                "date": row_date,
                "code": code,
                "shares_100m": shares,
                "exchange": str(item.get("exchange") or fund.exchange),
                "source": str(
                    item.get("source")
                    or (SSE_URL if fund.exchange == "上交所" else SZSE_URL)
                ),
            }
    return rows


def validate_rows(
    rows: dict[tuple[date, str], dict[str, Any]],
    trading_dates: list[date],
) -> None:
    expected_dates = set(trading_dates)
    for fund in FUNDS:
        series = sorted(
            (
                row
                for (row_date, code), row in rows.items()
                if code == fund.code and row_date in expected_dates
            ),
            key=lambda row: row["date"],
        )
        available_dates = {row["date"] for row in series}
        if available_dates != expected_dates:
            missing = sorted(expected_dates - available_dates)
            extra = sorted(available_dates - expected_dates)
            raise ValueError(
                f"{fund.code} date coverage mismatch: "
                f"missing={missing[:5]}, extra={extra[:5]}"
            )
        previous: float | None = None
        for row in series:
            shares = float(row["shares_100m"])
            if not math.isfinite(shares) or shares <= 0:
                raise ValueError(
                    f"invalid shares for {fund.code} on {row['date']}: {shares}"
                )
            if previous is not None:
                ratio = shares / previous
                if ratio < 0.2 or ratio > 5:
                    raise ValueError(
                        f"implausible share ratio for {fund.code} on {row['date']}: {ratio}"
                    )
                if abs(ratio - 1) > 0.2 and (fund.code, row["date"]) not in KNOWN_LARGE_MOVES:
                    raise ValueError(
                        f"unreviewed >20% share move for {fund.code} on {row['date']}: "
                        f"{(ratio - 1) * 100:.2f}%"
                    )
            previous = shares


def align_trading_dates(
    rows: dict[tuple[date, str], dict[str, Any]],
    trading_dates: list[date],
    requested_start: date,
) -> list[date]:
    requested_set = set(trading_dates)
    first_dates: list[date] = []
    for fund in FUNDS:
        available = sorted(
            row_date
            for row_date, code in rows
            if code == fund.code and row_date in requested_set
        )
        if not available:
            raise ValueError(f"no share history for {fund.code}")
        first_dates.append(available[0])
    actual_start = max(first_dates)
    if actual_start > requested_start + timedelta(days=14):
        raise ValueError(
            f"common share history starts too late at {actual_start}; "
            f"requested {requested_start}"
        )
    return [day for day in trading_dates if day >= actual_start]


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def write_csv(rows: dict[tuple[date, str], dict[str, Any]]) -> None:
    fieldnames = ["date", "code", "shares_100m", "exchange", "source"]
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CSV_PATH.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for key in sorted(rows):
            item = rows[key]
            writer.writerow(
                {
                    "date": item["date"].isoformat(),
                    "code": item["code"],
                    "shares_100m": f"{float(item['shares_100m']):.6f}",
                    "exchange": item["exchange"],
                    "source": item["source"],
                }
            )
    os.replace(temporary, CSV_PATH)


def build_payload(
    rows: dict[tuple[date, str], dict[str, Any]],
    trading_dates: list[date],
    requested_start: date,
    updated_at: datetime,
) -> dict[str, Any]:
    date_keys = [day.isoformat() for day in trading_dates]
    series: dict[str, list[float]] = {}
    fund_payload: list[dict[str, Any]] = []
    for fund in FUNDS:
        values = [float(rows[(day, fund.code)]["shares_100m"]) for day in trading_dates]
        series[fund.code] = values
        minimum = min(values)
        maximum = max(values)
        minimum_index = values.index(minimum)
        maximum_index = values.index(maximum)
        first = values[0]
        latest = values[-1]
        fund_payload.append(
            {
                **asdict(fund),
                "first_shares_100m": round(first, 6),
                "latest_shares_100m": round(latest, 6),
                "change_100m": round(latest - first, 6),
                "change_pct": round((latest / first - 1) * 100, 6),
                "minimum_shares_100m": round(minimum, 6),
                "minimum_date": date_keys[minimum_index],
                "maximum_shares_100m": round(maximum, 6),
                "maximum_date": date_keys[maximum_index],
            }
        )

    aggregate_values = [
        round(sum(series[fund.code][index] for fund in FUNDS), 6)
        for index in range(len(trading_dates))
    ]
    aggregate_first = aggregate_values[0]
    aggregate_latest = aggregate_values[-1]
    actual_start = trading_dates[0]
    latest_date = trading_dates[-1]
    reviewed_events = []
    for (code, event_date), review in KNOWN_LARGE_MOVES.items():
        if event_date not in trading_dates:
            continue
        event_index = trading_dates.index(event_date)
        if event_index == 0:
            continue
        previous = series[code][event_index - 1]
        current = series[code][event_index]
        reviewed_events.append(
            {
                "code": code,
                "date": event_date.isoformat(),
                "previous_shares_100m": round(previous, 6),
                "current_shares_100m": round(current, 6),
                "change_pct": round((current / previous - 1) * 100, 6),
                **review,
            }
        )

    return {
        "metadata": {
            "title": "A股主流沪深300ETF份额趋势",
            "window_years": LOOKBACK_YEARS,
            "lookback_years": LOOKBACK_YEARS,
            "requested_start_date": requested_start.isoformat(),
            "actual_start_date": actual_start.isoformat(),
            "latest_data_date": latest_date.isoformat(),
            "updated_at": updated_at.isoformat(),
            "timezone": "Asia/Shanghai",
            "common_observations": len(trading_dates),
            "fund_observations": len(trading_dates) * len(FUNDS),
            "coverage_ratio": 1.0,
            "large_move_review_count": len(reviewed_events),
            "selection_as_of": "2026-07-31",
            "selection_basis": "普通被动沪深300ETF同日份额乘单位净值的估算净资产排名前四",
            "selection_policy": "固定当前四只主流产品，不构造历史逐日TOP4",
            "aggregate_method": "四只ETF原始份额的算术合计",
            "aggregate_warning": "不同ETF每份净值不同，份额合计仅用于统计展示，不代表净资产或资金流",
            "share_unit": "亿份",
            "sources": [
                {
                    "name": "上海证券交易所 ETF 规模披露",
                    "url": SSE_URL,
                    "role": "上交所ETF日终份额",
                },
                {
                    "name": "深圳证券交易所 ETF 规模披露",
                    "url": SZSE_URL,
                    "role": "深交所ETF日终份额",
                },
                {
                    "name": "中证指数官网",
                    "url": CSI_INDEX_URL,
                    "role": "沪深300官方交易日历",
                },
            ],
        },
        "dates": date_keys,
        "funds": fund_payload,
        "series": series,
        "reviewed_events": reviewed_events,
        "aggregate": {
            "values": aggregate_values,
            "first_shares_100m": round(aggregate_first, 6),
            "latest_shares_100m": round(aggregate_latest, 6),
            "change_100m": round(aggregate_latest - aggregate_first, 6),
            "change_pct": round(
                (aggregate_latest / aggregate_first - 1) * 100,
                6,
            ),
        },
    }


def main() -> None:
    args = parse_args()
    if args.refresh_days < 0:
        raise ValueError("refresh-days must not be negative")
    end = parse_date(args.end) if args.end else datetime.now(TIMEZONE).date()
    calendar_start = (
        parse_date(args.start)
        if args.start
        else shift_years(end, -LOOKBACK_YEARS) - timedelta(days=21)
    )
    calendar = fetch_trading_calendar(calendar_start, end)
    latest_date = calendar[-1]
    requested_start = (
        parse_date(args.start)
        if args.start
        else shift_years(latest_date, -LOOKBACK_YEARS)
    )
    trading_dates = [day for day in calendar if day >= requested_start]
    if not trading_dates:
        raise RuntimeError("no CSI 300 trading dates in requested window")

    rows = load_rows(CSV_PATH)
    if not rows and args.seed_csv:
        rows.update(load_rows(args.seed_csv))
        print(f"loaded seed cache from {args.seed_csv}", flush=True)

    refresh_cutoff = latest_date - timedelta(days=args.refresh_days)
    sse_dates = [
        day
        for day in trading_dates
        if day >= refresh_cutoff
        or any((day, code) not in rows for code in SSE_CODES)
    ]
    szse_dates = [
        day
        for day in trading_dates
        if day >= refresh_cutoff
        or any(
            (day, code) not in rows
            and (code, day) not in KNOWN_UNAVAILABLE_SHARE_DATES
            for code in SZSE_CODES
        )
    ]

    for item in fetch_sse_dates(sse_dates):
        rows[(item["date"], item["code"])] = item
    write_csv(rows)
    if szse_dates:
        selected_szse_dates = set(szse_dates)
        for code in sorted(SZSE_CODES):
            for item in fetch_szse_range(code, min(szse_dates), max(szse_dates)):
                if item["date"] in selected_szse_dates:
                    rows[(item["date"], item["code"])] = item
        write_csv(rows)

    trading_dates = align_trading_dates(rows, trading_dates, requested_start)
    validate_rows(rows, trading_dates)
    updated_at = datetime.now(TIMEZONE).replace(microsecond=0)
    payload = build_payload(
        rows,
        trading_dates,
        requested_start,
        updated_at,
    )
    write_csv(rows)
    atomic_write_text(
        JSON_PATH,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "funds": [fund.code for fund in FUNDS],
                "requested_start_date": requested_start.isoformat(),
                "actual_start_date": trading_dates[0].isoformat(),
                "latest_data_date": latest_date.isoformat(),
                "observations": len(trading_dates),
                "updated_at": updated_at.isoformat(),
                "json": str(JSON_PATH.relative_to(ROOT)),
                "csv": str(CSV_PATH.relative_to(ROOT)),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
