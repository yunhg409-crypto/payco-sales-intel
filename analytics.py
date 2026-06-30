"""
PAYCO 세일즈 인텔리전스 — 종합 분석 탭
포트폴리오 전체 현황 + 가맹점 심층 지표
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from typing import Optional
import database as db


# ──────────────────────────────────────────────────────────────
# 데이터 빌더
# ──────────────────────────────────────────────────────────────

def _build_full_df() -> pd.DataFrame:
    """모든 가맹점 × 모든 월 데이터를 flat DataFrame으로 반환."""
    merchants = db.get_merchants()
    rows = []
    for m in merchants:
        data = db.get_monthly_data(m["id"])
        for d in data:
            rows.append({
                "id": m["id"],
                "가맹점명": m["가맹점명"],
                "업종": m.get("업종") or "-",
                "카테고리": m.get("카테고리") or "-",
                "담당자": m.get("담당자") or "-",
                "기존신규": m.get("기존신규") or "-",
                "year_month": d["year_month"],
                "거래액": d["거래액"],
                "거래건수": d["거래건수"],
                "프로모션여부": d["프로모션여부"],
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m")
    return df.sort_values(["id", "year_month"])


def _merchant_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """가맹점별 최신 지표 집계."""
    rows = []
    for mid, grp in df.groupby("id"):
        grp = grp.sort_values("year_month").reset_index(drop=True)
        if len(grp) < 2:
            continue

        amt = grp["거래액"].tolist()
        cnt = grp["거래건수"].tolist()
        months = grp["year_month"].tolist()

        cur_amt, prev_amt = amt[-1], amt[-2]
        cur_cnt, prev_cnt = cnt[-1], cnt[-2]

        mom_amt = (cur_amt - prev_amt) / prev_amt if prev_amt else None
        mom_cnt = (cur_cnt - prev_cnt) / prev_cnt if prev_cnt else None
        yoy_amt = (amt[-1] - amt[-13]) / amt[-13] if len(amt) >= 13 and amt[-13] else None

        # 객단가
        avg_order = cur_amt / cur_cnt if cur_cnt else None
        avg_order_prev = prev_amt / prev_cnt if prev_cnt else None
        mom_avg_order = (avg_order - avg_order_prev) / avg_order_prev \
                        if avg_order and avg_order_prev else None

        # 3개월 이동평균
        ma3 = np.mean(amt[-3:]) if len(amt) >= 3 else None

        # 6개월 성장 추세 (선형회귀 기울기 방향)
        trend_dir = None
        if len(amt) >= 6:
            x = np.arange(6)
            y = np.array(amt[-6:], dtype=float)
            if y.std() > 0:
                slope = np.polyfit(x, y, 1)[0]
                trend_dir = "상승" if slope > 0 else "하락"

        # 연속 상승/하락 스트릭
        streak = 0
        streak_dir = None
        for i in range(len(amt) - 1, 0, -1):
            diff = amt[i] - amt[i-1]
            if streak == 0:
                streak_dir = "상승" if diff > 0 else ("하락" if diff < 0 else None)
                if streak_dir:
                    streak = 1
            elif (diff > 0 and streak_dir == "상승") or (diff < 0 and streak_dir == "하락"):
                streak += 1
            else:
                break

        # 최근 12개월 중 최대/최소 대비 현재 위치
        recent12 = amt[-12:]
        pct_from_max = (cur_amt - max(recent12)) / max(recent12) if max(recent12) else None
        pct_from_min = (cur_amt - min(recent12)) / min(recent12) if min(recent12) else None

        # 변동성 (CV: 표준편차/평균)
        cv = np.std(recent12) / np.mean(recent12) if np.mean(recent12) > 0 else None

        # 프로모션 효과 (프로모션 달 평균 vs 비프로모션 달 평균)
        promo_amts = [a for a, p in zip(amt, grp["프로모션여부"].tolist()) if p]
        no_promo_amts = [a for a, p in zip(amt, grp["프로모션여부"].tolist()) if not p]
        promo_effect = None
        if promo_amts and no_promo_amts:
            promo_effect = (np.mean(promo_amts) - np.mean(no_promo_amts)) / np.mean(no_promo_amts)

        rows.append({
            "id": mid,
            "가맹점명": grp["가맹점명"].iloc[0],
            "업종": grp["업종"].iloc[0],
            "카테고리": grp["카테고리"].iloc[0],
            "담당자": grp["담당자"].iloc[0],
            "기존신규": grp["기존신규"].iloc[0],
            "기준월": grp["year_month"].iloc[-1].strftime("%Y-%m"),
            "거래액": cur_amt,
            "거래건수": cur_cnt,
            "객단가": avg_order,
            "전월대비_거래액": mom_amt,
            "전월대비_건수": mom_cnt,
            "전월대비_객단가": mom_avg_order,
            "전년대비_거래액": yoy_amt,
            "3개월이동평균": ma3,
            "6개월추세": trend_dir,
            "연속스트릭": f"{streak_dir} {streak}개월" if streak_dir and streak >= 2 else "-",
            "12개월최고대비": pct_from_max,
            "12개월최저대비": pct_from_min,
            "변동성CV": cv,
            "프로모션효과": promo_effect,
            "데이터개월수": len(amt),
        })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────
# 포트폴리오 전체 현황
# ──────────────────────────────────────────────────────────────

def _render_portfolio_overview(full_df: pd.DataFrame, metrics_df: pd.DataFrame):
    st.markdown("### 🏦 포트폴리오 전체 현황")

    latest_month = full_df["year_month"].max()
    prev_month   = full_df[full_df["year_month"] < latest_month]["year_month"].max()

    cur  = full_df[full_df["year_month"] == latest_month]
    prev = full_df[full_df["year_month"] == prev_month]

    total_amt   = cur["거래액"].sum()
    total_cnt   = cur["거래건수"].sum()
    prev_amt    = prev["거래액"].sum()
    prev_cnt    = prev["거래건수"].sum()
    mom_total   = (total_amt - prev_amt) / prev_amt if prev_amt else 0
    mom_cnt_tot = (total_cnt - prev_cnt) / prev_cnt if prev_cnt else 0

    rising  = (metrics_df["전월대비_거래액"] > 0).sum()
    falling = (metrics_df["전월대비_거래액"] < 0).sum()
    flat    = len(metrics_df) - rising - falling
    danger  = (metrics_df["전월대비_거래액"] <= -0.10).sum()
    growth  = (metrics_df["전월대비_거래액"] >= 0.20).sum()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("총 거래액", f"{total_amt/1e8:.1f}억",
              delta=f"{mom_total*100:+.1f}%")
    c2.metric("총 결제건수", f"{total_cnt:,}건",
              delta=f"{mom_cnt_tot*100:+.1f}%")
    c3.metric("↑ 상승 가맹점", f"{rising}개")
    c4.metric("↓ 하락 가맹점", f"{falling}개")
    c5.metric("🚨 급락 (-10%↓)", f"{danger}개")
    c6.metric("🚀 급등 (+20%↑)", f"{growth}개")

    # 상태 분포 파이
    col_pie, col_cat = st.columns(2)
    with col_pie:
        fig = go.Figure(go.Pie(
            labels=["상승", "하락", "보합"],
            values=[rising, falling, flat],
            marker_colors=["#2ecc71", "#e74c3c", "#95a5a6"],
            hole=0.4,
            textinfo="label+percent",
        ))
        fig.update_layout(title="전월 대비 가맹점 상태 분포",
                          height=280, margin=dict(t=40, b=0, l=0, r=0),
                          showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with col_cat:
        cat_df = cur.groupby("카테고리")["거래액"].sum().reset_index()
        cat_df.columns = ["카테고리", "거래액"]
        cat_df = cat_df.sort_values("거래액", ascending=False).head(8)
        fig = px.bar(cat_df, x="거래액", y="카테고리", orientation="h",
                     color="거래액", color_continuous_scale="Blues",
                     title="카테고리별 거래액 (최근 월)")
        fig.update_layout(height=280, margin=dict(t=40, b=0, l=0, r=20),
                          coloraxis_showscale=False, yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)


def _render_heatmap(full_df: pd.DataFrame):
    st.markdown("### 🗓 가맹점 × 월별 거래액 증감률 히트맵")
    st.caption("최근 12개월 기준. 초록=상승 / 빨강=하락")

    # 최근 12개월만
    months12 = sorted(full_df["year_month"].unique())[-12:]
    df12 = full_df[full_df["year_month"].isin(months12)].copy()

    pivot = df12.pivot_table(index="가맹점명", columns="year_month",
                              values="거래액", aggfunc="sum")
    pivot.columns = [c.strftime("%y.%m") for c in pivot.columns]

    # MoM 증감률로 변환
    mom_pivot = pivot.pct_change(axis=1) * 100

    # 거래액 기준 상위 30개만
    top30 = df12.groupby("가맹점명")["거래액"].sum().nlargest(30).index
    mom_pivot = mom_pivot.loc[mom_pivot.index.isin(top30)]

    fig = go.Figure(go.Heatmap(
        z=mom_pivot.values,
        x=mom_pivot.columns.tolist(),
        y=mom_pivot.index.tolist(),
        colorscale=[
            [0.0, "#c0392b"], [0.35, "#e74c3c"],
            [0.45, "#f5b7b1"], [0.5, "#f8f9fa"],
            [0.55, "#a9dfbf"], [0.65, "#2ecc71"],
            [1.0, "#1a5276"],
        ],
        zmid=0,
        text=[[f"{v:.0f}%" if not np.isnan(v) else "" for v in row]
              for row in mom_pivot.values],
        texttemplate="%{text}",
        textfont={"size": 9},
        hovertemplate="%{y}<br>%{x}: %{z:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        height=max(400, len(mom_pivot) * 22),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="",
        yaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_risk_growth(metrics_df: pd.DataFrame):
    col_risk, col_growth = st.columns(2)

    with col_risk:
        st.markdown("### 🚨 위험 신호 가맹점")
        risk = metrics_df[metrics_df["전월대비_거래액"] <= -0.10].copy()
        risk = risk.sort_values("전월대비_거래액")
        if risk.empty:
            st.success("현재 급락 가맹점 없음")
        else:
            for _, r in risk.iterrows():
                pct = r["전월대비_거래액"] * 100
                streak = r["연속스트릭"]
                st.error(
                    f"**{r['가맹점명']}**  "
                    f"`{pct:+.1f}%` | {r['카테고리']} | {r['담당자']} "
                    + (f"| {streak}" if streak != "-" else "")
                )

    with col_growth:
        st.markdown("### 🚀 성장 기회 가맹점")
        grow = metrics_df[metrics_df["전월대비_거래액"] >= 0.20].copy()
        grow = grow.sort_values("전월대비_거래액", ascending=False)
        if grow.empty:
            st.info("현재 급등 가맹점 없음")
        else:
            for _, r in grow.iterrows():
                pct = r["전월대비_거래액"] * 100
                st.success(
                    f"**{r['가맹점명']}**  "
                    f"`+{pct:.1f}%` | {r['카테고리']} | {r['담당자']}"
                )


# ──────────────────────────────────────────────────────────────
# 가맹점 심층 지표
# ──────────────────────────────────────────────────────────────

def _render_merchant_deep(full_df: pd.DataFrame, metrics_df: pd.DataFrame):
    st.markdown("### 🔬 가맹점 심층 분석")

    names = sorted(metrics_df["가맹점명"].tolist())
    col1, col2 = st.columns([2, 1])
    with col1:
        sel = st.selectbox("가맹점 선택", names, key="deep_merchant")
    with col2:
        periods = st.select_slider("분석 기간", options=[6, 12, 18, 24, 30],
                                    value=12, key="deep_months")

    m_row = metrics_df[metrics_df["가맹점명"] == sel].iloc[0]
    mid   = int(m_row["id"])
    data  = db.get_monthly_data(mid, months=periods)
    if not data:
        st.warning("데이터 없음")
        return

    df_m  = pd.DataFrame(data)
    df_m["year_month"] = pd.to_datetime(df_m["year_month"], format="%Y-%m")
    df_m["객단가"]    = df_m.apply(
        lambda r: r["거래액"] / r["거래건수"] if r["거래건수"] else 0, axis=1
    )
    df_m["거래액_MA3"] = df_m["거래액"].rolling(3, min_periods=1).mean()
    df_m["MoM_pct"]   = df_m["거래액"].pct_change() * 100
    df_m["label"]     = df_m["year_month"].dt.strftime("%y.%m")

    # ── 지표 카드 9개 ──────────────────────────────────
    st.divider()
    _render_deep_metrics(m_row, df_m, metrics_df)
    st.divider()

    # ── 차트 4종 ───────────────────────────────────────
    _render_deep_charts(df_m, sel)


def _render_deep_metrics(m_row, df_m: pd.DataFrame, metrics_df: pd.DataFrame):
    # 전체 순위
    rank_amt = metrics_df["거래액"].rank(ascending=False).loc[
        metrics_df["id"] == m_row["id"]].values
    rank_amt = int(rank_amt[0]) if len(rank_amt) else "-"
    total_merchants = len(metrics_df)

    # 카테고리 내 순위
    cat_df = metrics_df[metrics_df["카테고리"] == m_row["카테고리"]]
    cat_rank = cat_df["거래액"].rank(ascending=False).loc[
        cat_df["id"] == m_row["id"]].values
    cat_rank = int(cat_rank[0]) if len(cat_rank) else "-"

    # 점유율
    share = m_row["거래액"] / metrics_df["거래액"].sum() * 100

    def _pct(v): return f"{'+' if v and v > 0 else ''}{v*100:.1f}%" if v else "-"
    def _won(v): return f"{v:,.0f}원" if v else "-"

    r1 = st.columns(5)
    r1[0].metric("전체 거래액 순위",  f"{rank_amt}위 / {total_merchants}")
    r1[1].metric("카테고리 내 순위",  f"{cat_rank}위 / {len(cat_df)}")
    r1[2].metric("전체 점유율",       f"{share:.2f}%")
    r1[3].metric("전월대비 거래액",   _pct(m_row["전월대비_거래액"]))
    r1[4].metric("전년대비 거래액",   _pct(m_row["전년대비_거래액"]))

    r2 = st.columns(5)
    r2[0].metric("객단가",            _won(m_row["객단가"]))
    r2[1].metric("전월대비 객단가",   _pct(m_row["전월대비_객단가"]))
    r2[2].metric("6개월 추세",        m_row["6개월추세"] or "-")
    r2[3].metric("연속 스트릭",       m_row["연속스트릭"])
    r2[4].metric("변동성(CV)",
                 f"{m_row['변동성CV']*100:.1f}%" if m_row["변동성CV"] else "-",
                 help="낮을수록 안정적. 변동계수(표준편차/평균)")

    r3 = st.columns(5)
    r3[0].metric("12개월 최고 대비",
                 _pct(m_row["12개월최고대비"]),
                 help="현재 거래액이 최근 12개월 최고점 대비 몇 %인지")
    r3[1].metric("12개월 최저 대비",
                 _pct(m_row["12개월최저대비"]),
                 help="현재 거래액이 최근 12개월 최저점 대비 몇 %인지")
    r3[2].metric("3개월 이동평균",
                 f"{m_row['3개월이동평균']/1e6:.1f}백만" if m_row["3개월이동평균"] else "-")
    r3[3].metric("프로모션 효과",
                 _pct(m_row["프로모션효과"]) if m_row["프로모션효과"] else "데이터 부족",
                 help="프로모션 진행 달 평균 vs 미진행 달 평균")
    r3[4].metric("데이터 기간", f"{m_row['데이터개월수']}개월")


def _render_deep_charts(df_m: pd.DataFrame, merchant_name: str):
    col_a, col_b = st.columns(2)

    # 차트1: 거래액 + 3개월 MA + MoM%
    with col_a:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(
            x=df_m["label"], y=df_m["거래액"],
            name="거래액", marker_color="#3498db", opacity=0.7
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=df_m["label"], y=df_m["거래액_MA3"],
            name="3개월 MA", mode="lines",
            line=dict(color="#e67e22", width=2, dash="dot")
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=df_m["label"], y=df_m["MoM_pct"],
            name="MoM(%)", mode="lines+markers",
            line=dict(color="#9b59b6", width=1.5),
            marker=dict(size=5)
        ), secondary_y=True)
        fig.add_hline(y=0, line_dash="dash", line_color="gray",
                      line_width=1, secondary_y=True)
        fig.update_layout(title="거래액 추이 + 3개월 이동평균 + MoM",
                          height=320, margin=dict(l=0, r=60, t=40, b=0),
                          legend=dict(orientation="h", y=1.15),
                          hovermode="x unified")
        fig.update_yaxes(title_text="거래액", secondary_y=False)
        fig.update_yaxes(title_text="MoM (%)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)

    # 차트2: 결제건수 + 객단가
    with col_b:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(
            x=df_m["label"], y=df_m["거래건수"],
            name="결제건수", marker_color="#1abc9c", opacity=0.7
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=df_m["label"], y=df_m["객단가"],
            name="객단가", mode="lines+markers",
            line=dict(color="#e74c3c", width=2),
            marker=dict(size=5)
        ), secondary_y=True)
        fig.update_layout(title="결제건수 + 객단가 추이",
                          height=320, margin=dict(l=0, r=60, t=40, b=0),
                          legend=dict(orientation="h", y=1.15),
                          hovermode="x unified")
        fig.update_yaxes(title_text="결제건수", secondary_y=False)
        fig.update_yaxes(title_text="객단가 (원)", secondary_y=True)
        st.plotly_chart(fig, use_container_width=True)

    col_c, col_d = st.columns(2)

    # 차트3: MoM 분포 히스토그램
    with col_c:
        mom_vals = df_m["MoM_pct"].dropna()
        fig = go.Figure(go.Histogram(
            x=mom_vals, nbinsx=15,
            marker_color="#3498db", opacity=0.75,
        ))
        fig.add_vline(x=0, line_dash="dash", line_color="gray")
        fig.add_vline(x=mom_vals.mean(), line_dash="dot", line_color="#e67e22",
                      annotation_text=f"평균 {mom_vals.mean():.1f}%",
                      annotation_position="top right")
        fig.update_layout(title="월별 MoM 증감률 분포",
                          height=280, margin=dict(l=0, r=0, t=40, b=0),
                          xaxis_title="MoM (%)", yaxis_title="개월 수")
        st.plotly_chart(fig, use_container_width=True)

    # 차트4: 계절성 — 월별 평균 거래액 (1~12월 패턴)
    with col_d:
        df_m["월"] = df_m["year_month"].dt.month
        seasonal = df_m.groupby("월")["거래액"].mean().reset_index()
        seasonal.columns = ["월", "평균거래액"]
        seasonal["월명"] = seasonal["월"].apply(lambda x: f"{x}월")
        overall_avg = seasonal["평균거래액"].mean()
        seasonal["대비"] = (seasonal["평균거래액"] - overall_avg) / overall_avg * 100
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in seasonal["대비"]]
        fig = go.Figure(go.Bar(
            x=seasonal["월명"], y=seasonal["대비"],
            marker_color=colors,
            text=[f"{v:+.0f}%" for v in seasonal["대비"]],
            textposition="outside",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
        fig.update_layout(title="월별 계절성 패턴 (연평균 대비 %)",
                          height=280, margin=dict(l=0, r=0, t=40, b=30),
                          yaxis_title="%")
        st.plotly_chart(fig, use_container_width=True)


# ──────────────────────────────────────────────────────────────
# 메인 렌더 함수
# ──────────────────────────────────────────────────────────────

def render_analytics():
    full_df = _build_full_df()
    if full_df.empty:
        st.info("가맹점 데이터가 없습니다. Excel을 업로드해주세요.")
        return

    metrics_df = _merchant_metrics(full_df)
    if metrics_df.empty:
        st.info("분석 가능한 데이터가 부족합니다.")
        return

    tab1, tab2, tab3 = st.tabs(["🏦 포트폴리오 현황", "🗓 히트맵", "🔬 가맹점 심층"])

    with tab1:
        _render_portfolio_overview(full_df, metrics_df)
        st.divider()
        _render_risk_growth(metrics_df)

    with tab2:
        _render_heatmap(full_df)

    with tab3:
        _render_merchant_deep(full_df, metrics_df)
