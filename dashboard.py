import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Optional
from datetime import datetime
import database as db
import ai_service
import news_service
import strategy_service
from config import DEFAULT_MONTHS, MOM_THRESHOLD, MIN_BENCHMARK_COUNT, has_llm, has_naver


def _calc_mom(data: list[dict]) -> Optional[float]:
    if len(data) < 2:
        return None
    cur = data[-1]["거래액"]
    prev = data[-2]["거래액"]
    if prev == 0:
        return None
    return (cur - prev) / prev


def _calc_yoy(data: list[dict]) -> Optional[float]:
    if len(data) < 13:
        return None
    cur = data[-1]["거래액"]
    prev = data[-13]["거래액"]
    if prev == 0:
        return None
    return (cur - prev) / prev


def _generate_hypothesis(merchant_name: str, mom: float, recent_data: list[dict]) -> Optional[str]:
    if not has_llm():
        return None
    direction = "증가" if mom > 0 else "감소"
    pct = abs(mom) * 100
    last = recent_data[-1]
    prompt = (
        f"PAYCO 결제 가맹점 '{merchant_name}'의 이번 달 거래액이 전월 대비 {pct:.1f}% {direction}했습니다.\n"
        f"최근 거래액: {last['거래액']:,}원, 거래건수: {last['거래건수']:,}건\n\n"
        "영업 담당자가 가맹점에 연락하기 전 확인해야 할 가능한 원인을 3가지 가설로 제시해주세요. "
        "각 가설은 한 문장으로 간결하게 작성하세요."
    )
    return ai_service.generate(prompt)


def _fmt_pct(val: Optional[float], positive_good: bool = True) -> str:
    if val is None:
        return "데이터 부족"
    sign = "+" if val > 0 else ""
    return f"{sign}{val*100:.1f}%"


@st.cache_data(ttl=300)
def _cached_managers() -> list[str]:
    return db.get_managers()

@st.cache_data(ttl=300)
def _cached_merchants(manager: Optional[str] = None) -> list[dict]:
    return db.get_merchants(manager)

@st.cache_data(ttl=300)
def _cached_monthly(merchant_id: int, months: int = 0) -> list[dict]:
    return db.get_monthly_data(merchant_id, months)

@st.cache_data(ttl=300)
def _cached_category_monthly(category: str) -> list[dict]:
    return db.get_category_monthly(category)


def render_merchant_selector(all_manager: bool = False) -> Optional[dict]:
    all_merchants = st.session_state.get("merchants", [])
    managers = sorted({m["담당자"] for m in all_merchants if m.get("담당자")})

    col1, col2 = st.columns([1, 2])
    with col1:
        manager_options = ["전체"] + managers
        selected_manager = st.selectbox("담당자", manager_options, key="manager_filter")

    if selected_manager == "전체":
        merchant_list = all_merchants
    else:
        merchant_list = [m for m in all_merchants if m.get("담당자") == selected_manager]

    if not merchant_list:
        with col2:
            st.info("가맹점 데이터가 없습니다. Excel을 업로드해주세요.")
        return None

    names = [m["가맹점명"] for m in merchant_list]
    with col2:
        selected_name = st.selectbox("가맹점 선택", names, key="merchant_select")

    return next((m for m in merchant_list if m["가맹점명"] == selected_name), None)


def render_dashboard(merchant: dict):
    st.markdown(f"## {merchant['가맹점명']}")

    cols = st.columns(4)
    cols[0].metric("업종", merchant.get("업종") or "-")
    cols[1].metric("카테고리", merchant.get("카테고리") or "-")
    cols[2].metric("담당자", merchant.get("담당자") or "-")
    cols[3].metric("구분", merchant.get("기존신규") or "-")

    st.divider()

    months_opt = st.select_slider(
        "표시 기간", options=[6, 12, 18, 24, 30], value=DEFAULT_MONTHS, key="months_slider"
    )
    monthly_map = st.session_state.get("monthly_map", {})
    all_records = sorted(monthly_map.get(merchant["id"], []), key=lambda r: r["year_month"])
    data = all_records[-months_opt:] if months_opt > 0 else all_records

    if not data:
        st.warning("거래 데이터가 없습니다.")
        return

    df = pd.DataFrame(data)
    df["label"] = df["year_month"]

    mom = _calc_mom(data)
    yoy = _calc_yoy(data)

    # 건수 MoM/YoY
    def _calc_mom_cnt(d):
        if len(d) < 2: return None
        c, p = d[-1]["거래건수"], d[-2]["거래건수"]
        return (c - p) / p if p else None

    def _calc_yoy_cnt(d):
        if len(d) < 13: return None
        c, p = d[-1]["거래건수"], d[-13]["거래건수"]
        return (c - p) / p if p else None

    mom_cnt = _calc_mom_cnt(data)
    yoy_cnt = _calc_yoy_cnt(data)

    st.markdown("**💰 거래액**")
    m1, m2, m3 = st.columns(3)
    m1.metric("최근 월 거래액",  f"{data[-1]['거래액']:,}원",
              delta=_fmt_pct(mom) if mom is not None else None)
    m2.metric("전월 대비",       _fmt_pct(mom))
    m3.metric("전년 동월 대비",  _fmt_pct(yoy))

    st.markdown("**🧾 결제건수**")
    c1, c2, c3 = st.columns(3)
    c1.metric("최근 월 결제건수", f"{data[-1]['거래건수']:,}건",
              delta=_fmt_pct(mom_cnt) if mom_cnt is not None else None)
    c2.metric("전월 대비",        _fmt_pct(mom_cnt))
    c3.metric("전년 동월 대비",   _fmt_pct(yoy_cnt))

    # Chart
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    promo_months = {r["year_month"] for r in data if r["프로모션여부"]}
    if promo_months:
        for ym in promo_months:
            idx = df[df["year_month"] == ym].index
            if not idx.empty:
                fig.add_vrect(
                    x0=df.loc[idx[0], "label"],
                    x1=df.loc[idx[0], "label"],
                    fillcolor="rgba(255,215,0,0.15)",
                    layer="below",
                    line_width=0,
                )

    fig.add_trace(
        go.Bar(x=df["label"], y=df["거래액"], name="거래액", marker_color="#1f77b4", opacity=0.8),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=df["label"], y=df["거래건수"], name="거래건수", mode="lines+markers",
                   line=dict(color="#ff7f0e", width=2)),
        secondary_y=True,
    )

    # Category benchmark — session_state에서 직접 필터링
    cat = merchant.get("카테고리")
    if cat:
        all_merchants = st.session_state.get("merchants", [])
        cat_ids = {m["id"] for m in all_merchants if m.get("카테고리") == cat}
        cat_records = []
        for mid, records in monthly_map.items():
            if mid in cat_ids:
                m_name = next((m["가맹점명"] for m in all_merchants if m["id"] == mid), "")
                for r in records:
                    cat_records.append({"year_month": r["year_month"], "거래액": r["거래액"], "가맹점명": m_name})
        cat_df = pd.DataFrame(cat_records)
        if len(cat_df["가맹점명"].unique()) >= MIN_BENCHMARK_COUNT:
            avg = cat_df.groupby("year_month")["거래액"].mean().reset_index()
            avg = avg[avg["year_month"].isin(df["year_month"])]
            fig.add_trace(
                go.Scatter(
                    x=avg["year_month"], y=avg["거래액"],
                    name=f"{cat} 평균", mode="lines",
                    line=dict(color="gray", dash="dot", width=1.5),
                ),
                secondary_y=False,
            )

    fig.update_layout(
        height=400,
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation="h", y=1.1),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="거래액 (원)", secondary_y=False)
    fig.update_yaxes(title_text="거래건수 (건)", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)

    if promo_months:
        st.caption("🟡 노란 음영: 프로모션 진행 기간")

    # AI 가설
    if mom is not None and abs(mom) >= MOM_THRESHOLD:
        st.divider()
        with st.expander("🤖 AI 변화 가설", expanded=True):
            if not has_llm():
                st.info("API 키 미설정 — LLM 기능을 사용하려면 `.env`에 API 키를 입력해주세요.")
            else:
                with st.spinner("AI 가설 생성 중..."):
                    hypothesis = _generate_hypothesis(merchant["가맹점명"], mom, data)
                if hypothesis:
                    st.markdown(hypothesis)
                else:
                    st.warning("가설 생성에 실패했습니다.")

    # News section
    st.divider()
    _render_news(merchant)

    # Strategy section
    st.divider()
    _render_strategy(merchant, data)


def _render_news(merchant: dict):
    st.markdown("### 📰 최근 뉴스 요약")

    if not has_naver() and not has_llm():
        st.info("API 키 미설정 — 뉴스 기능을 사용하려면 `.env`에 NAVER_CLIENT_ID/SECRET을 입력해주세요.")
        return

    col_refresh, _ = st.columns([1, 5])
    force = col_refresh.button("🔄 새로고침", key=f"news_refresh_{merchant['id']}")

    with st.spinner("뉴스 조회 중..."):
        result = news_service.get_news(merchant["id"], merchant["가맹점명"], force_refresh=force)

    if result["error"]:
        st.error(result["error"])
        return

    if result["no_news"]:
        st.info("최근 30일 내 관련 뉴스가 없습니다.")
        return

    if result["from_cache"]:
        st.caption("📦 캐시에서 불러옴")

    if result["summary"]:
        st.markdown(result["summary"])

    if result["links"]:
        st.markdown("**원문 링크**")
        for link in result["links"]:
            st.markdown(f"- [{link['title']}]({link['url']})")


def _render_strategy(merchant: dict, monthly_data: list[dict]):
    st.markdown("### 🎯 AI 영업 전략")

    last_contact = db.get_last_contact(merchant["id"])
    if last_contact:
        try:
            dt = datetime.fromisoformat(last_contact)
            st.caption(f"📞 마지막 접촉: {dt.strftime('%Y-%m-%d %H:%M')}")
        except Exception:
            pass

    if not has_llm():
        st.info("API 키 미설정 — `.env`에 GEMINI_API_KEY (무료) 또는 ANTHROPIC_API_KEY / OPENAI_API_KEY를 입력해주세요.")
        _render_strategy_history(merchant)
        return

    # 트리거 감지
    fired_triggers = strategy_service.evaluate_triggers(monthly_data, merchant)

    tab_new, tab_history = st.tabs(["✨ 새 전략 생성", "📋 전략 이력"])

    with tab_new:
        if fired_triggers:
            st.markdown("**🚨 감지된 신호:**")
            for t in fired_triggers:
                st.markdown(f"- `{t['code']}` **{t['label']}** — {t.get('detail', t['desc'])}")
            selected_trigger = fired_triggers[0]
        else:
            st.info("현재 자동 트리거 조건 해당 없음. 수동으로 전략을 생성할 수 있습니다.")
            trigger_options = {f"[{t['code']}] {t['label']}": t for t in strategy_service.get_all_triggers()}
            selected_key = st.selectbox("전략 유형 선택", list(trigger_options.keys()),
                                        key=f"trigger_select_{merchant['id']}")
            selected_trigger = trigger_options[selected_key]

        # 뉴스 요약 가져오기 (전략 컨텍스트용)
        cached_news = db.get_news_cache(merchant["id"])
        news_summary = cached_news["summary"] if cached_news else ""

        if st.button("🤖 전략 생성", key=f"gen_strategy_{merchant['id']}", type="primary"):
            with st.spinner("AI 전략 생성 중..."):
                content = strategy_service.generate_strategy(
                    merchant, monthly_data, selected_trigger, news_summary
                )
            if content:
                st.session_state[f"strategy_draft_{merchant['id']}"] = {
                    "content": content,
                    "trigger": selected_trigger,
                }
            else:
                err = ai_service.get_last_error()
                st.error(f"전략 생성 실패: {err}" if err else "전략 생성 실패. API 키를 확인해주세요.")

        # 생성된 전략 초안 표시
        draft_key = f"strategy_draft_{merchant['id']}"
        if draft_key in st.session_state:
            draft = st.session_state[draft_key]
            st.divider()
            st.markdown(f"**[{draft['trigger']['code']}] {draft['trigger']['label']}** 기반 전략 초안")
            st.markdown(draft["content"])

            memo = st.text_area("📝 메모 (선택사항)", key=f"memo_{merchant['id']}",
                                placeholder="통화 후 내용, 가맹점 반응 등 자유롭게 기록")

            col_save, col_discard = st.columns([1, 4])
            if col_save.button("💾 저장", key=f"save_strategy_{merchant['id']}", type="primary"):
                db.save_strategy(
                    merchant_id=merchant["id"],
                    trigger_code=draft["trigger"]["code"],
                    trigger_label=draft["trigger"]["label"],
                    strategy_content=draft["content"],
                    memo=memo,
                )
                del st.session_state[draft_key]
                st.success("저장됐습니다!")
                st.rerun()

            if col_discard.button("🗑 버리기", key=f"discard_strategy_{merchant['id']}"):
                del st.session_state[draft_key]
                st.rerun()

    with tab_history:
        _render_strategy_history(merchant)


def _render_strategy_history(merchant: dict):
    strategies = db.get_strategies(merchant["id"])

    if not strategies:
        st.info("저장된 전략이 없습니다.")
        return

    for s in strategies:
        try:
            dt = datetime.fromisoformat(s["created_at"])
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = s["created_at"]

        with st.expander(f"[{s['trigger_code']}] {s['trigger_label']} — {date_str}"):
            st.markdown(s["strategy_content"])
            if s["memo"]:
                st.markdown(f"**📝 메모:** {s['memo']}")

            col_contact, _ = st.columns([1, 4])
            if col_contact.button("📞 접촉 완료", key=f"contact_{s['id']}"):
                db.mark_contacted(s["id"])
                st.success("접촉 기록 저장됨")
                st.rerun()

            new_memo = st.text_input("메모 수정", value=s["memo"] or "",
                                     key=f"edit_memo_{s['id']}")
            if st.button("💾 메모 저장", key=f"save_memo_{s['id']}"):
                db.update_strategy_memo(s["id"], new_memo)
                st.success("메모 저장됨")
                st.rerun()
