from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import database as db
import data_loader
import dashboard
import ranking
import analytics

st.set_page_config(
    page_title="PAYCO 세일즈 인텔리전스",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

db.init_db()
db.purge_expired_cache()


@st.cache_data(ttl=300, show_spinner="데이터 불러오는 중...")
def _load_all():
    """세션당 1회 — JOIN 단일 쿼리로 전체 데이터 로드."""
    rows = db.get_all_data_joined()

    merchants, monthly_map = {}, {}
    for r in rows:
        mid = r["id"]
        if mid not in merchants:
            merchants[mid] = {
                "id": mid,
                "가맹점명":  r.get("name") or "",
                "업종":      r.get("industry") or "",
                "카테고리":  r.get("category") or "",
                "담당자":    r.get("manager") or "",
                "채널":      r.get("channel") or "",
                "기존신규":  r.get("merchant_type") or "",
            }
        if r.get("year_month"):
            monthly_map.setdefault(mid, []).append({
                "merchant_id":  mid,
                "year_month":   r["year_month"],
                "거래액":       r.get("amount") or 0,
                "거래건수":     r.get("count") or 0,
                "프로모션여부": r.get("has_promo") or 0,
            })

    merchant_list = sorted(merchants.values(), key=lambda m: m["가맹점명"])
    return merchant_list, monthly_map


def render_sidebar(merchant_count: int):
    with st.sidebar:
        st.title("💳 PAYCO\n세일즈 인텔리전스")
        st.divider()

        if merchant_count:
            st.success(f"✅ 가맹점 {merchant_count}개 로드됨")

        st.subheader("📂 데이터 업로드")
        uploaded = st.file_uploader(
            "Excel 파일 업로드",
            type=["xlsx"],
            help="리스트(20260127) 시트가 포함된 PAYCO 가맹점 실적 파일",
        )
        if uploaded:
            progress_bar = st.progress(0, text="파싱 중...")
            status_text = st.empty()
            try:
                def on_progress(current, total):
                    pct = current / total
                    progress_bar.progress(pct, text=f"저장 중... {current}/{total} 가맹점")
                    status_text.caption(f"{current}/{total} 가맹점 처리됨")

                m_cnt, r_cnt = data_loader.load_excel(uploaded, progress_callback=on_progress)
                progress_bar.progress(1.0, text="완료!")
                status_text.empty()
                st.cache_data.clear()  # 새 데이터 반영
                st.success(f"✅ 완료: 가맹점 {m_cnt}개, {r_cnt:,}건 적재")
                st.rerun()
            except ValueError as e:
                progress_bar.empty()
                st.error(f"❌ 파싱 오류: {e}")
            except Exception as e:
                progress_bar.empty()
                st.error(f"❌ 오류: {e}")

        st.divider()
        st.caption("v0.3 — 속도 최적화 적용")

    return uploaded


def main():
    merchants, monthly_map = _load_all()

    render_sidebar(len(merchants))

    if not merchants:
        st.title("PAYCO 세일즈 인텔리전스")
        st.info("👈 왼쪽 사이드바에서 Excel 파일을 업로드해주세요.")
        return

    # 세션 상태에 저장 — 각 모듈이 DB 없이 바로 사용
    st.session_state["merchants"] = merchants
    st.session_state["monthly_map"] = monthly_map

    tab_analytics, tab_rank, tab_detail = st.tabs([
        "📈 종합 분석", "📊 순위 & 지표", "🔍 가맹점 상세"
    ])

    with tab_analytics:
        analytics.render_analytics()

    with tab_rank:
        ranking.render_ranking()

    with tab_detail:
        merchant = dashboard.render_merchant_selector()
        if merchant:
            dashboard.render_dashboard(merchant)


if __name__ == "__main__":
    main()
