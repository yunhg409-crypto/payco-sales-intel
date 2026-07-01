import re
import pandas as pd
from typing import Tuple
import database as db
from config import (
    EXCEL_SHEET_NAME, MERCHANT_COL, CATEGORY_COL, INDUSTRY_COL,
    MANAGER_COL, CHANNEL_COL, PROMO_COL, TYPE_COL, MERCHANT_ALIASES
)

YM_PATTERN = re.compile(r"(\d{2})년\s*(\d{1,2})월")


def _find_header_row(df_raw: pd.DataFrame) -> int:
    for i, row in df_raw.iterrows():
        if any(str(v) == MERCHANT_COL for v in row.values):
            return i
    raise ValueError(f"헤더 행을 찾을 수 없습니다. '{MERCHANT_COL}' 컬럼이 없습니다.")


_EXCLUDE = ("예상", "차이", "증감", "달성", "목표")

def _parse_ym(col_name: str) -> str | None:
    col_str = str(col_name)
    if any(kw in col_str for kw in _EXCLUDE):
        return None
    m = YM_PATTERN.search(col_str)
    if m:
        yy, mm = int(m.group(1)), int(m.group(2))
        return f"20{yy:02d}-{mm:02d}"
    return None


def _split_amount_count_cols(cols: list[str]) -> Tuple[dict, dict]:
    """
    헤더 위 행(row 11)의 '거래액' / '결제건수' 구분 없이
    컬럼명 패턴만으로 분리: 같은 YM이 두 번 등장하면 앞=거래액, 뒤=결제건수.
    """
    seen: dict[str, list[int]] = {}
    for i, c in enumerate(cols):
        ym = _parse_ym(c)
        if ym:
            seen.setdefault(ym, []).append(i)

    amount_idx: dict[str, int] = {}
    count_idx: dict[str, int] = {}
    for ym, indices in seen.items():
        amount_idx[ym] = indices[0]
        if len(indices) >= 2:
            count_idx[ym] = indices[1]

    return amount_idx, count_idx


def load_excel(file_path_or_buffer) -> Tuple[int, int]:
    """
    Excel 파싱 후 DB upsert.
    Returns: (merchant_count, row_count)
    """
    df_raw = pd.read_excel(
        file_path_or_buffer,
        sheet_name=EXCEL_SHEET_NAME,
        header=None,
    )

    header_row = _find_header_row(df_raw)
    df = df_raw.iloc[header_row:].reset_index(drop=True)
    df.columns = df.iloc[0]
    df = df.iloc[1:].reset_index(drop=True)

    required = [MERCHANT_COL, CATEGORY_COL, INDUSTRY_COL, MANAGER_COL]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼 없음: {missing}")

    cols = list(df.columns)
    amount_idx, count_idx = _split_amount_count_cols(cols)

    if not amount_idx:
        raise ValueError("월별 거래액 컬럼을 찾을 수 없습니다. 컬럼명 형식: '24년 1월'")

    db.init_db()
    merchant_count = 0
    row_count = 0

    conn = db.get_conn()
    try:
        for _, row in df.iterrows():
            name = str(row.get(MERCHANT_COL, "")).strip()
            if not name or name in ("nan", "온라인 전체", "포인트플러스"):
                continue
            # 통합 매핑 적용
            name = MERCHANT_ALIASES.get(name, name)

            promo_raw = str(row.get(PROMO_COL, "")).strip()
            merchant_data = {
                "가맹점명": name,
                "업종": str(row.get(INDUSTRY_COL, "")).strip() or None,
                "카테고리": str(row.get(CATEGORY_COL, "")).strip() or None,
                "담당자": str(row.get(MANAGER_COL, "")).strip() or None,
                "채널": str(row.get(CHANNEL_COL, "")).strip() or None,
                "기존신규": str(row.get(TYPE_COL, "")).strip() or None,
            }
            mid = db.upsert_merchant(conn, merchant_data)
            merchant_count += 1

            monthly_rows = []
            for ym, col_i in amount_idx.items():
                try:
                    amt = row.iloc[col_i]
                    amt = int(float(amt)) if pd.notna(amt) and str(amt).strip() not in ("", "nan") else 0
                except (ValueError, TypeError):
                    amt = 0

                cnt = 0
                if ym in count_idx:
                    try:
                        cv = row.iloc[count_idx[ym]]
                        cnt = int(float(cv)) if pd.notna(cv) and str(cv).strip() not in ("", "nan") else 0
                    except (ValueError, TypeError):
                        cnt = 0

                is_promo = 1 if promo_raw and promo_raw.lower() not in ("nan", "") else 0

                monthly_rows.append({
                    "merchant_id": mid,
                    "year_month": ym,
                    "거래액": amt,
                    "거래건수": cnt,
                    "프로모션여부": is_promo,
                })
                row_count += 1

            db.upsert_monthly(conn, monthly_rows)
            conn.commit()  # 가맹점마다 커밋 (timeout 방지)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return merchant_count, row_count
