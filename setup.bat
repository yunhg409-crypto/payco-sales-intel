@echo off
chcp 65001 > nul
echo ================================================
echo  PAYCO 세일즈 인텔리전스 - 설치 및 실행
echo ================================================
echo.

REM Python 확인
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo.
    echo Python 3.11 이상을 설치해주세요:
    echo https://www.python.org/downloads/
    echo.
    echo 설치 시 "Add Python to PATH" 옵션을 반드시 체크하세요!
    pause
    exit /b 1
)

python --version
echo.

REM 가상환경 생성
if not exist ".venv" (
    echo [1/3] 가상환경 생성 중...
    python -m venv .venv
)

REM 패키지 설치
echo [2/3] 패키지 설치 중...
.venv\Scripts\pip install -r requirements.txt --quiet

REM .env 파일 확인
if not exist ".env" (
    echo [3/3] .env 파일 생성 중...
    copy .env.example .env > nul
    echo.
    echo [중요] .env 파일에 API 키를 입력해주세요:
    echo   - ANTHROPIC_API_KEY 또는 OPENAI_API_KEY (AI 기능용)
    echo   - NAVER_CLIENT_ID + NAVER_CLIENT_SECRET (뉴스 기능용)
    echo.
    echo API 키 없이도 대시보드 기본 기능은 사용 가능합니다.
) else (
    echo [3/3] .env 파일 확인 완료
)

echo.
echo ================================================
echo  앱 실행 중... 브라우저가 자동으로 열립니다.
echo  종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo ================================================
echo.

.venv\Scripts\streamlit run app.py
