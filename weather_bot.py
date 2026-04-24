"""
기상청 단기예보 API + 텔레그램 날씨 알림 봇
---------------------------------------------
필요한 환경변수:
  KMA_API_KEY      : 기상청 API 서비스 키 (URL 인코딩된 키)
  TELEGRAM_TOKEN   : 텔레그램 봇 토큰
  TELEGRAM_CHAT_ID : 메시지를 받을 채팅 ID

사용법:
  python weather_bot.py          # 즉시 실행 (테스트용)
  python weather_bot.py --test   # API 응답만 출력, 텔레그램 미전송
"""

import os
import sys
import requests
from datetime import datetime, timedelta

# ──────────────────────────────────────────
# 설정
# ──────────────────────────────────────────

# 환경변수에서 읽기
KMA_API_KEY = os.environ.get("KMA_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# 격자 좌표 (서울 중구 기준 — 아래 주석 참고)
NX = 60  # 경도 격자
NY = 122  # 위도 격자

# ──────────────────────────────────────────
# 기상청 API
# ──────────────────────────────────────────

# 카테고리 코드 한글 매핑
SKY_CODE = {"1": "☀️ 맑음", "3": "⛅ 구름많음", "4": "☁️ 흐림"}
PTY_CODE = {"0": "없음", "1": "🌧 비", "2": "🌨 비/눈", "3": "❄️ 눈", "4": "🌦 소나기"}


def get_base_time() -> tuple[str, str]:
    """
    기상청 단기예보는 하루 8회 발표 (0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300).
    현재 시각 기준으로 가장 최근 발표 시각을 반환합니다.
    API 반영에 약 10분이 걸리므로 10분의 여유를 둡니다.
    """
    now = datetime.now() - timedelta(minutes=10)
    base_hours = [2, 5, 8, 11, 14, 17, 20, 23]

    base_hour = base_hours[0]
    for h in base_hours:
        if now.hour >= h:
            base_hour = h
        else:
            break

    base_date = now.strftime("%Y%m%d")
    base_time = f"{base_hour:02d}00"
    return base_date, base_time


def fetch_forecast(nx: int = NX, ny: int = NY) -> dict:
    """기상청 단기예보 API를 호출하여 오늘의 예보 아이템 목록을 반환합니다."""
    base_date, base_time = get_base_time()
    url = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

    params = {
        "serviceKey": KMA_API_KEY,  # 공공데이터포털에서 발급받은 키 (디코딩된 값 사용)
        "pageNo": 1,
        "numOfRows": 300,           # 여러 시간대 데이터를 한 번에 받기 위해 충분히 크게
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()

    body = resp.json().get("response", {}).get("body", {})
    result_code = resp.json()["response"]["header"]["resultCode"]
    if result_code != "00":
        msg = resp.json()["response"]["header"]["resultMsg"]
        raise RuntimeError(f"기상청 API 오류: [{result_code}] {msg}")

    items = body.get("items", {}).get("item", [])
    return items


def parse_today_weather(items: list) -> dict:
    """
    TMX(일최고기온), TMN(일최저기온)을 직접 추출하고
    SKY, POP, PTY는 오전 9시 기준으로 가져옵니다.
    """
    today = datetime.now().strftime("%Y%m%d")
    data = {}

    for item in items:
        if item["fcstDate"] != today:
            continue

        cat = item["category"]

        # 최고/최저 기온은 날짜 안에 딱 한 번만 나옴 — 바로 저장
        if cat in ("TMX", "TMN"):
            data[cat] = item["fcstValue"]

        # 하늘/강수/기온은 오전 8시 기준
        if item["fcstTime"] == "0800" and cat in ("TMP", "SKY", "POP", "PTY"):
            data[cat] = item["fcstValue"]

    return data


def format_weather_message(data: dict) -> str:
    now = datetime.now()
    date_str = now.strftime("%Y년 %m월 %d일 (%a)")

    tmx = data.get("TMX", "?")
    tmn = data.get("TMN", "?")
    tmp = data.get("TMP", "?")
    sky = SKY_CODE.get(data.get("SKY", ""), "알 수 없음")
    pop = data.get("POP", "?")
    pty = PTY_CODE.get(data.get("PTY", "0"), "없음")

    lines = [
        f"🌤 *오늘의 날씨* — {date_str}",
        "",
        f"🌡 오늘 최고기온 : *{tmx}°C*  /  최저기온 : *{tmn}°C*",
        f"🌡 지금 기온 : *{tmp}°C*",
        f"🌥 하늘 : {sky}",
        f"🌂 강수확률 : *{pop}%*",
        f"💧 강수형태 : {pty}",
    ]

    if int(pop) >= 60:
        lines.append("")
        lines.append("☔ 강수확률이 높으니 우산을 챙기세요!")

    return "\n".join(lines)


# ──────────────────────────────────────────
# 텔레그램 전송
# ──────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """텔레그램 Bot API로 메시지를 전송합니다."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json().get("ok", False)


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────

def main(test_mode: bool = False):
    # 환경변수 체크
    missing = [k for k, v in {
        "KMA_API_KEY": KMA_API_KEY,
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }.items() if not v]

    if missing:
        print(f"[오류] 환경변수가 설정되지 않았습니다: {', '.join(missing)}")
        sys.exit(1)

    print(f"[{datetime.now():%H:%M:%S}] 기상청 API 호출 중...")
    items = fetch_forecast()
    print(f"  → {len(items)}개 예보 아이템 수신")

    weather = parse_today_weather(items)
    print(f"  → 파싱 결과: {weather}")

    message = format_weather_message(weather)
    print("\n── 전송할 메시지 ──")
    print(message)
    print("───────────────────")

    if test_mode:
        print("\n[테스트 모드] 텔레그램 전송 생략")
        return

    print("\n텔레그램 전송 중...")
    ok = send_telegram(message)
    if ok:
        print("✅ 전송 완료!")
    else:
        print("❌ 전송 실패")
        sys.exit(1)


if __name__ == "__main__":
    test = "--test" in sys.argv
    main(test_mode=test)
