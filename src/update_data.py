"""실시간 네이버 금융 ETF 데이터를 주기적으로 수집하여 저장하는 스크립트.

이 스크립트는 네이버 금융 API에서 실시간 ETF 종목 정보를 수집한 후,
CORS 우회 등을 위해 사용되는 JSONP 구문을 파싱하여 순수한 JSON 데이터 형식으로
저장소 내부의 `data/etf_data.json` 파일에 영속화합니다.
"""

import os
import re
import json
import requests
from typing import Dict, Any, List

# 실시간 ETF 데이터를 제공하는 네이버 금융 API URL
API_URL: str = (
    "https://finance.naver.com/api/sise/etfItemList.nhn?"
    "etfType=0&targetColumn=market_sum&sortOrder=desc&"
    "_callback=window.__jindo2_callback._7957"
)

# 데이터가 저장될 결과 파일의 상대 경로
OUTPUT_PATH: str = os.path.join("data", "etf_data.json")


def fetch_and_save_data() -> None:
    """네이버 금융 API로부터 데이터를 패치하고 전처리 후 JSON 파일로 저장합니다.

    Raises:
        requests.RequestException: API 호출 과정에서 HTTP 네트워크 에러 발생 시.
        ValueError: JSONP 파싱 오류 혹은 올바르지 않은 데이터 수신 시.
    """
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    print("네이버 금융 API 호출을 시작합니다...")
    # HTTP GET 요청
    response = requests.get(API_URL, headers=headers, timeout=10)
    response.raise_for_status()

    # 인코딩 설정 (네이버 금융 응답은 종종 cp949 인코딩을 사용함)
    if response.encoding is None or response.encoding == "ISO-8859-1":
        response.encoding = response.apparent_encoding

    html_content: str = response.text

    # JSONP callback 구문 window.__jindo2_callback._7957(...)에서 내부 JSON만 정규식으로 추출
    match = re.search(r"\((.*)\)", html_content, re.DOTALL)
    if not match:
        raise ValueError("API 응답 내용에서 JSON 본문을 추출하는 데 실패했습니다.")

    json_str: str = match.group(1)
    data_dict: Dict[str, Any] = json.loads(json_str)

    # 데이터 유효성 검증
    etf_list: List[Dict[str, Any]] = (
        data_dict.get("result", {}).get("etfItemList", [])
    )
    if not etf_list:
        raise ValueError("API 수집 결과에 ETF 항목 리스트가 존재하지 않습니다.")

    # 저장할 디렉토리 생성
    output_dir: str = os.path.dirname(OUTPUT_PATH)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 순수 JSON 형식으로 영속화 (가독성을 위해 indent 적용)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=2)

    print(f"데이터가 성공적으로 {OUTPUT_PATH} 에 저장되었습니다. (수집 개수: {len(etf_list)}개)")


if __name__ == "__main__":
    try:
        fetch_and_save_data()
    except Exception as e:
        print(f"[ERROR] ETF 데이터 자동 수집 실패: {e}")
        exit(1)
