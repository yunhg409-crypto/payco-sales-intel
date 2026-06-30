from typing import Optional
import ai_service

# ── 트리거 정의 ─────────────────────────────────────────────────

TRIGGERS = [
    {
        "code": "T-01",
        "label": "전월 대비 급락",
        "desc": "MoM 거래액 -10% 이상 하락",
        "direction": "방어/이탈방지",
    },
    {
        "code": "T-02",
        "label": "전월 대비 급등",
        "desc": "MoM 거래액 +20% 이상 상승",
        "direction": "업셀/확장",
    },
    {
        "code": "T-03",
        "label": "2개월 연속 하락",
        "desc": "2개월 연속 전월 대비 감소",
        "direction": "긴급 관계관리",
    },
    {
        "code": "T-04",
        "label": "프로모션 종료 후 첫 달",
        "desc": "프로모션 종료 다음 달",
        "direction": "효과분석/재제안",
    },
    {
        "code": "T-05",
        "label": "신규 가맹점 3개월",
        "desc": "신규 가맹점 온보딩 3개월 경과",
        "direction": "온보딩 점검",
    },
    {
        "code": "T-06",
        "label": "전년 대비 급락",
        "desc": "YoY 거래액 -15% 이상 하락",
        "direction": "연간 리스크 경보",
    },
]


def evaluate_triggers(monthly_data: list[dict], merchant: dict) -> list[dict]:
    """
    월별 데이터와 가맹점 정보를 받아 발화된 트리거 목록 반환.
    Returns list of trigger dicts with 'fired': True.
    """
    if not monthly_data or len(monthly_data) < 2:
        return []

    fired = []

    last = monthly_data[-1]["거래액"]
    prev = monthly_data[-2]["거래액"] if len(monthly_data) >= 2 else 0
    prev2 = monthly_data[-3]["거래액"] if len(monthly_data) >= 3 else None

    mom = (last - prev) / prev if prev != 0 else None

    # T-01: MoM -10%
    if mom is not None and mom <= -0.10:
        fired.append({**TRIGGERS[0], "detail": f"전월 대비 {mom*100:.1f}%"})

    # T-02: MoM +20%
    if mom is not None and mom >= 0.20:
        fired.append({**TRIGGERS[1], "detail": f"전월 대비 +{mom*100:.1f}%"})

    # T-03: 2개월 연속 하락
    if prev2 is not None and prev != 0 and prev2 != 0:
        mom_prev = (prev - prev2) / prev2
        if mom is not None and mom < 0 and mom_prev < 0:
            fired.append({**TRIGGERS[2], "detail": "2개월 연속 감소 중"})

    # T-04: 프로모션 종료 후 첫 달 (이전 달 프로모션, 현재 달 미진행)
    if len(monthly_data) >= 2:
        cur_promo = monthly_data[-1].get("프로모션여부", 0)
        prev_promo = monthly_data[-2].get("프로모션여부", 0)
        if prev_promo and not cur_promo:
            fired.append({**TRIGGERS[3], "detail": "전월 프로모션 종료"})

    # T-05: 신규 가맹점 + 데이터 3~6개월 (초기 온보딩 기간)
    if merchant.get("기존신규", "").strip() in ("신규", "신규가맹점") and 3 <= len(monthly_data) <= 6:
        fired.append({**TRIGGERS[4], "detail": "신규 가맹점 3개월 데이터 축적"})

    # T-06: YoY -15%
    if len(monthly_data) >= 13:
        yoy_base = monthly_data[-13]["거래액"]
        if yoy_base != 0:
            yoy = (last - yoy_base) / yoy_base
            if yoy <= -0.15:
                fired.append({**TRIGGERS[5], "detail": f"전년 동월 대비 {yoy*100:.1f}%"})

    return fired


def generate_strategy(merchant: dict, monthly_data: list[dict],
                       trigger: dict, news_summary: str = "") -> Optional[str]:
    """
    트리거 + 거래 데이터 + 뉴스 요약을 합쳐 LLM 영업전략 초안 생성.
    """
    if not monthly_data:
        return None

    last = monthly_data[-1]
    recent_trend = " → ".join(
        f"{r['year_month']}({r['거래액']:,})" for r in monthly_data[-3:]
    )

    news_section = f"\n\n[최근 뉴스 요약]\n{news_summary}" if news_summary else ""

    prompt = f"""PAYCO 온라인영업팀 담당자를 위한 영업전략을 제안해주세요.

[가맹점 정보]
- 가맹점명: {merchant['가맹점명']}
- 업종/카테고리: {merchant.get('업종','-')} / {merchant.get('카테고리','-')}
- 구분: {merchant.get('기존신규','-')}

[거래 현황]
- 최근 3개월 추이: {recent_trend}
- 최근 월 거래건수: {last['거래건수']:,}건
- 감지된 신호: [{trigger['code']}] {trigger['label']} — {trigger.get('detail','')}
- 전략 방향: {trigger['direction']}{news_section}

[제약 조건]
- PAYCO 프로모션 비용은 총 거래액 대비 1.5% 이하로 유지해야 함
- PG 수수료 약 2%, 포인트 원가 약 0.3% 고려
- 할인 외 비용 없는 전략(노출 확대, 데이터 공유, 공동 이벤트 등)도 적극 활용

위 상황을 고려해 영업담당자가 가맹점 담당자에게 제안할 수 있는 구체적인 영업전략을 500자 이내로 작성해주세요.
제안 배경(왜 지금인지), 핵심 제안 내용, 예상 효과 순으로 간결하게 작성해주세요."""

    return ai_service.generate(prompt)


def get_all_triggers() -> list[dict]:
    return TRIGGERS
