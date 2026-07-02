import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import database as db


def _build_summary_df(months_back: int = 2) -> pd.DataFrame:
    """세션 메모리에서 순위 DataFrame 구성 — DB 쿼리 없음."""
    merchants = st.session_state.get("merchants", [])
    monthly_map = st.session_state.get("monthly_map", {})
    rows = []

    for m in merchants:
        data = monthly_map.get(m["id"], [])
        if len(data) < 2:
            continue

        cur  = data[-1]
        prev = data[-2]
        cur_amt  = cur["거래액"]
        prev_amt = prev["거래액"]
        cur_cnt  = cur["거래건수"]
        prev_cnt = prev["거래건수"]

        mom_amt = (cur_amt - prev_amt) / prev_amt if prev_amt else None
        mom_cnt = (cur_cnt - prev_cnt) / prev_cnt if prev_cnt else None

        yoy_amt = None
        if len(data) >= 13:
            base_amt = data[-13]["거래액"]
            yoy_amt = (cur_amt - base_amt) / base_amt if base_amt else None

        rows.append({
            "id":        m["id"],
            "가맹점명":  m["가맹점명"],
            "업종":      m.get("업종") or "-",
            "카테고리":  m.get("카테고리") or "-",
            "담당자":    m.get("담당자") or "-",
            "기준월":    cur["year_month"],
            "거래액":    cur_amt,
            "거래건수":  cur_cnt,
            "전월대비_거래액":  mom_amt,
            "전월대비_거래건수": mom_cnt,
            "전년대비_거래액":  yoy_amt,
        })

    return pd.DataFrame(rows)


def _fmt_pct(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    sign = "+" if v > 0 else ""
    return f"{sign}{v*100:.1f}%"


def _color_pct(v):
    if v is None or pd.isna(v):
        return "color: gray"
    return "color: #2ecc71" if v > 0 else "color: #e74c3c"


def render_ranking():
    st.markdown("## 📊 전략 가맹점 순위 & 지표")

    df = _build_summary_df()
    if df.empty:
        st.info("가맹점 데이터가 없습니다. Excel을 업로드해주세요.")
        return

    # ── 필터 ────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        managers = ["전체"] + sorted(df["담당자"].unique().tolist())
        sel_mgr = st.selectbox("담당자", managers, key="rank_mgr")
    with col2:
        cats = ["전체"] + sorted(df["카테고리"].unique().tolist())
        sel_cat = st.selectbox("카테고리", cats, key="rank_cat")
    with col3:
        sort_opts = {
            "거래액 높은순": ("거래액", False),
            "거래액 낮은순": ("거래액", True),
            "전월대비 상승순": ("전월대비_거래액", False),
            "전월대비 하락순": ("전월대비_거래액", True),
            "전년대비 상승순": ("전년대비_거래액", False),
            "전년대비 하락순": ("전년대비_거래액", True),
            "거래건수 높은순": ("거래건수", False),
        }
        sel_sort = st.selectbox("정렬", list(sort_opts.keys()), key="rank_sort")

    filtered = df.copy()
    if sel_mgr != "전체":
        filtered = filtered[filtered["담당자"] == sel_mgr]
    if sel_cat != "전체":
        filtered = filtered[filtered["카테고리"] == sel_cat]

    sort_col, sort_asc = sort_opts[sel_sort]
    filtered = filtered.sort_values(sort_col, ascending=sort_asc, na_position="last")
    filtered = filtered.reset_index(drop=True)
    filtered.index += 1

    # ── 요약 카드 ─────────────────────────────────────
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    total_amt = filtered["거래액"].sum()
    rising = (filtered["전월대비_거래액"] > 0).sum()
    falling = (filtered["전월대비_거래액"] < 0).sum()
    risk = (filtered["전월대비_거래액"] <= -0.10).sum()

    m1.metric("총 거래액", f"{total_amt/1e8:.1f}억")
    m2.metric("전월 대비 상승", f"{rising}개 가맹점", delta=f"+{rising}")
    m3.metric("전월 대비 하락", f"{falling}개 가맹점", delta=f"-{falling}", delta_color="inverse")
    m4.metric("🚨 -10% 이상 급락", f"{risk}개 가맹점")

    st.divider()

    # ── 탭 ────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["📋 전체 순위표", "📈 상승 Top 10", "📉 하락 Top 10"])

    with tab1:
        _render_full_table(filtered)

    with tab2:
        top_rising = filtered.nlargest(10, "전월대비_거래액")
        _render_bar_chart(top_rising, "전월대비_거래액", "전월 대비 거래액 상승 Top 10", color="#2ecc71")

    with tab3:
        top_falling = filtered.nsmallest(10, "전월대비_거래액")
        _render_bar_chart(top_falling, "전월대비_거래액", "전월 대비 거래액 하락 Top 10", color="#e74c3c")

    # ── 선택 가맹점 월별 추이 ─────────────────────────────
    st.divider()
    _render_merchant_trend(filtered)


def _render_full_table(df: pd.DataFrame):
    display = df[["가맹점명", "카테고리", "담당자", "거래액", "거래건수",
                   "전월대비_거래액", "전월대비_거래건수", "전년대비_거래액"]].copy()

    display["거래액"] = display["거래액"].apply(lambda x: f"{x:,}")
    display["거래건수"] = display["거래건수"].apply(lambda x: f"{x:,}")
    display["전월↕거래액"] = display["전월대비_거래액"].apply(_fmt_pct)
    display["전월↕건수"]  = display["전월대비_거래건수"].apply(_fmt_pct)
    display["전년↕거래액"] = display["전년대비_거래액"].apply(_fmt_pct)

    display = display.drop(columns=["전월대비_거래액", "전월대비_거래건수", "전년대비_거래액"])

    st.dataframe(
        display,
        use_container_width=True,
        height=500,
        column_config={
            "가맹점명":   st.column_config.TextColumn("가맹점명", width="medium"),
            "거래액":     st.column_config.TextColumn("거래액 (원)"),
            "거래건수":   st.column_config.TextColumn("결제건수 (건)"),
            "전월↕거래액": st.column_config.TextColumn("전월대비 거래액"),
            "전월↕건수":  st.column_config.TextColumn("전월대비 건수"),
            "전년↕거래액": st.column_config.TextColumn("전년대비 거래액"),
        },
    )


def _render_bar_chart(df: pd.DataFrame, col: str, title: str, color: str):
    if df.empty:
        st.info("데이터 없음")
        return

    chart_df = df.dropna(subset=[col]).copy()
    chart_df["pct"] = chart_df[col] * 100
    chart_df = chart_df.sort_values("pct", ascending=True)

    fig = go.Figure(go.Bar(
        x=chart_df["pct"],
        y=chart_df["가맹점명"],
        orientation="h",
        marker_color=[color if v >= 0 else "#e74c3c" for v in chart_df["pct"]],
        text=[f"{v:+.1f}%" for v in chart_df["pct"]],
        textposition="outside",
    ))
    fig.update_layout(
        title=title,
        height=400,
        margin=dict(l=0, r=60, t=40, b=0),
        xaxis_title="전월 대비 (%)",
        yaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_merchant_trend(filtered_df: pd.DataFrame):
    st.markdown("### 📈 가맹점 월별 거래액 · 건수 추이")

    names = filtered_df["가맹점명"].tolist()
    col1, col2 = st.columns([2, 1])
    with col1:
        selected = st.selectbox("가맹점 선택", names, key="trend_merchant")
    with col2:
        months = st.select_slider("표시 기간", options=[6, 12, 18, 24, 30],
                                   value=12, key="trend_months")

    match = filtered_df[filtered_df["가맹점명"] == selected]
    if match.empty:
        st.warning("선택한 가맹점 데이터를 찾을 수 없습니다.")
        return
    row = match.iloc[0]
    merchant_id = int(row["id"])
    monthly_map = st.session_state.get("monthly_map", {})
    all_records = sorted(monthly_map.get(merchant_id, []), key=lambda r: r["year_month"])
    data = all_records[-months:] if months > 0 else all_records

    if not data:
        st.warning("데이터가 없습니다.")
        return

    df = pd.DataFrame(data)

    # MoM/YoY 카드
    cur_amt = data[-1]["거래액"]
    cur_cnt = data[-1]["거래건수"]

    mom_amt = (data[-1]["거래액"] - data[-2]["거래액"]) / data[-2]["거래액"] \
              if len(data) >= 2 and data[-2]["거래액"] else None
    mom_cnt = (data[-1]["거래건수"] - data[-2]["거래건수"]) / data[-2]["거래건수"] \
              if len(data) >= 2 and data[-2]["거래건수"] else None
    yoy_amt = (data[-1]["거래액"] - data[-13]["거래액"]) / data[-13]["거래액"] \
              if len(data) >= 13 and data[-13]["거래액"] else None
    yoy_cnt = (data[-1]["거래건수"] - data[-13]["거래건수"]) / data[-13]["거래건수"] \
              if len(data) >= 13 and data[-13]["거래건수"] else None

    def _d(v): return f"{'+' if v > 0 else ''}{v*100:.1f}%" if v is not None else None

    st.markdown("**💰 거래액**")
    c1, c2, c3 = st.columns(3)
    c1.metric("최근 월 거래액",   f"{cur_amt:,}원", delta=_d(mom_amt))
    c2.metric("전월 대비",        _d(mom_amt) or "-")
    c3.metric("전년 동월 대비",   _d(yoy_amt) or "-")

    st.markdown("**🧾 결제건수**")
    c4, c5, c6 = st.columns(3)
    c4.metric("최근 월 결제건수", f"{cur_cnt:,}건",  delta=_d(mom_cnt))
    c5.metric("전월 대비",        _d(mom_cnt) or "-")
    c6.metric("전년 동월 대비",   _d(yoy_cnt) or "-")

    # 이중축 차트
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # 프로모션 음영
    for r in data:
        if r.get("프로모션여부"):
            fig.add_vrect(
                x0=r["year_month"], x1=r["year_month"],
                fillcolor="rgba(255,215,0,0.15)", layer="below", line_width=0,
            )

    fig.add_trace(
        go.Bar(x=df["year_month"], y=df["거래액"], name="거래액",
               marker_color="#1f77b4", opacity=0.8),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=df["year_month"], y=df["거래건수"], name="결제건수",
                   mode="lines+markers", line=dict(color="#ff7f0e", width=2)),
        secondary_y=True,
    )

    # MoM 변화율 라인
    if len(data) >= 2:
        mom_vals = [None]
        for i in range(1, len(data)):
            prev = data[i-1]["거래액"]
            cur  = data[i]["거래액"]
            mom_vals.append((cur - prev) / prev * 100 if prev else None)

        fig.add_trace(
            go.Scatter(
                x=df["year_month"], y=mom_vals, name="MoM(%)",
                mode="lines+markers",
                line=dict(color="#9b59b6", width=1.5, dash="dot"),
                marker=dict(size=5),
                yaxis="y3",
            ),
        )
        fig.update_layout(
            yaxis3=dict(
                title="MoM (%)",
                overlaying="y",
                side="right",
                anchor="free",
                position=1.0,
                showgrid=False,
                zeroline=True,
                zerolinecolor="rgba(155,89,182,0.3)",
            )
        )

    fig.update_layout(
        height=420,
        margin=dict(l=0, r=80, t=30, b=0),
        legend=dict(orientation="h", y=1.08),
        hovermode="x unified",
        xaxis_title="",
    )
    fig.update_yaxes(title_text="거래액 (원)", secondary_y=False)
    fig.update_yaxes(title_text="결제건수 (건)", secondary_y=True)

    st.plotly_chart(fig, use_container_width=True)

    if any(r.get("프로모션여부") for r in data):
        st.caption("🟡 노란 음영: 프로모션 진행 기간")
