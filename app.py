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


def render_sidebar():
    with st.sidebar:
        st.title("💳 PAYCO\n세일즈 인텔리전스")
        st.divider()

        merchant_count = len(db.get_merchants())
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
                st.success(f"✅ 완료: 가맹점 {m_cnt}개, {r_cnt:,}건 적재")
                st.rerun()
            except ValueError as e:
                progress_bar.empty()
                st.error(f"❌ 파싱 오류: {e}")
            except Exception as e:
                progress_bar.empty()
                st.error(f"❌ 오류: {e}")

        st.divider()
        st.caption("v0.2 — AI 전략 기능은 API 키 설정 후 사용 가능")

    return uploaded


def main():
    render_sidebar()

    merchants = db.get_merchants()
    if not merchants:
        st.title("PAYCO 세일즈 인텔리전스")
        st.info("👈 왼쪽 사이드바에서 Excel 파일을 업로드해주세요.")
        return

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
