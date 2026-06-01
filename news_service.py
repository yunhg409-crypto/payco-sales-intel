import requests
from typing import Optional
import database as db
import ai_service
from config import (
    NAVER_CLIENT_ID, NAVER_CLIENT_SECRET,
    NEWS_DISPLAY_COUNT, has_naver, has_llm
)


def _fetch_naver_news(query: str) -> list[dict]:
    url = "https://openapi.naver.com/v1/search/news.json"
    # 공백/개행 제거
    clean_query = query.strip().replace('\r', '').replace('\n', '')
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID.strip(),
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET.strip(),
    }
    params = {"query": clean_query, "display": NEWS_DISPLAY_COUNT, "sort": "date"}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        {
            "title": _strip_tags(item.get("title", "")),
            "url": item.get("originallink") or item.get("link", ""),
            "description": _strip_tags(item.get("description", "")),
        }
        for item in items
    ]


def _strip_tags(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text)


def _summarize(articles: list[dict], merchant_name: str) -> str:
    if not articles or not has_llm():
        return ""
    snippets = "\n".join(
        f"- {a['title']}: {a['description']}" for a in articles
    )
    prompt = (
        f"다음은 '{merchant_name}'에 관한 최근 뉴스입니다.\n\n"
        f"{snippets}\n\n"
        "영업팀 관점에서 이 가맹점과의 협력에 참고할 핵심 내용을 한국어로 3줄 이내로 요약해주세요. "
        "단순한 뉴스 요약이 아니라 영업 관점의 시사점을 중심으로 작성해주세요."
    )
    return ai_service.generate(prompt) or ""


def get_news(merchant_id: int, merchant_name: str, force_refresh: bool = False) -> dict:
    """
    Returns: {
        "summary": str,
        "links": [{"title": str, "url": str}],
        "from_cache": bool,
        "error": str | None,
        "no_news": bool
    }
    """
    if force_refresh:
        db.invalidate_news_cache(merchant_id)

    cached = db.get_news_cache(merchant_id)
    if cached:
        return {**cached, "from_cache": True, "error": None, "no_news": not cached["summary"]}

    if not has_naver():
        return {"summary": "", "links": [], "from_cache": False,
                "error": "NAVER_API_KEY 미설정", "no_news": False}

    try:
        articles = _fetch_naver_news(merchant_name)
    except requests.RequestException as e:
        return {"summary": "", "links": [], "from_cache": False,
                "error": f"Naver API 오류: {e}", "no_news": False}

    if not articles:
        db.set_news_cache(merchant_id, "", [])
        return {"summary": "", "links": [], "from_cache": False, "error": None, "no_news": True}

    summary = _summarize(articles, merchant_name)
    links = [{"title": a["title"], "url": a["url"]} for a in articles]
    db.set_news_cache(merchant_id, summary, links)

    return {"summary": summary, "links": links, "from_cache": False, "error": None, "no_news": False}
