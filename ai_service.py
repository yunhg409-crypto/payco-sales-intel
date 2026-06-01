from typing import Optional
from config import LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY, has_llm
import os

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def has_any_llm() -> bool:
    return has_llm() or bool(GEMINI_API_KEY)


_last_error: str = ""

def get_last_error() -> str:
    return _last_error

def generate(prompt: str, system: str = "") -> Optional[str]:
    """LLM 호출. API 키 없으면 None 반환."""
    global _last_error
    _last_error = ""

    # Gemini 우선 — 키가 있으면 Gemini만 사용
    if GEMINI_API_KEY:
        try:
            return _call_gemini(prompt, system)
        except Exception as e:
            _last_error = f"Gemini 오류: {e}"
            return None  # Gemini 실패 시 다른 provider 미시도

    # Gemini 키 없을 때만 Claude/OpenAI 시도
    if LLM_PROVIDER == "claude" and ANTHROPIC_API_KEY:
        try:
            return _call_claude(prompt, system)
        except Exception as e:
            _last_error = f"Claude 오류: {e}"
            return None

    if LLM_PROVIDER == "openai" and OPENAI_API_KEY:
        try:
            return _call_openai(prompt, system)
        except Exception as e:
            _last_error = f"OpenAI 오류: {e}"
            return None

    _last_error = "사용 가능한 API 키가 없습니다."
    return None


def _call_claude(prompt: str, system: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    kwargs = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return msg.content[0].text


def _call_openai(prompt: str, system: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=1024,
    )
    return resp.choices[0].message.content


GEMINI_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

def _call_gemini(prompt: str, system: str) -> str:
    import urllib.request, json, time
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    body = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}]
    }).encode()

    last_err = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            last_err = f"{model}: HTTP {e.code}"
            if e.code in (429, 503):
                time.sleep(2)
                continue
            raise
        except Exception as e:
            last_err = f"{model}: {e}"
            continue

    raise Exception(f"모든 모델 실패: {last_err}")
