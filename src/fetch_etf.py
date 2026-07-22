"""Naver ETF API 데이터 수집 모듈.

이 모듈은 네이버 금융의 ETF API를 호출하여, 반환되는 JSONP 형식의 데이터를
파싱한 뒤 CSV 파일 형태로 지정된 경로에 저장하는 기능을 제공합니다.
"""

import urllib.request
import json
import csv
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

URL: str = "https://finance.naver.com/api/sise/etfItemList.nhn?etfType=0&targetColumn=market_sum&sortOrder=desc&_callback=window.__jindo2_callback._7957"

def fetch_and_save() -> None:
    """네이버 ETF API 데이터를 가져와 CSV 파일로 저장합니다.

    API 응답에서 JSONP callback 형식을 파싱하여 순수 JSON 데이터를 추출하고,
    그 중 ETF 목록 데이터를 타임스탬프가 포함된 CSV 파일로 로컬 디렉토리에 저장합니다.

    Raises:
        urllib.error.URLError: 네트워크 요청 실패 시 발생할 수 있습니다.
        json.JSONDecodeError: JSON 파싱 실패 시 발생할 수 있습니다.
    """
    try:
        # User-Agent를 설정하여 봇 감지 우회 및 HTTP 요청 생성
        req = urllib.request.Request(
            URL, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        
        # API 데이터 요청 및 수신
        with urllib.request.urlopen(req) as response:
            raw_data: bytes = response.read()
            # 네이버 금융 API 응답 인코딩 처리 (기본 utf-8 시도 후 실패 시 한국어 인코딩 cp949 적용)
            try:
                html: str = raw_data.decode('utf-8')
            except UnicodeDecodeError:
                html = raw_data.decode('cp949')
            
        # JSONP 파싱: callback 함수 호출 형태 `_callback(...)`에서 괄호 안의 JSON 객체 문자열만 추출
        match: Optional[re.Match] = re.search(r'\((.*)\)', html, re.DOTALL)
        if not match:
            print("JSONP 응답에서 JSON 데이터를 찾을 수 없습니다.")
            return
            
        json_str: str = match.group(1)
        json_data: Dict[str, Any] = json.loads(json_str)
        
        result: Dict[str, Any] = json_data.get('result', {})
        etf_list: List[Dict[str, Any]] = result.get('etfItemList', [])
        
        if not etf_list:
            print("ETF 아이템 목록이 비어 있습니다.")
            return
            
        # 파일 저장 이름 정의: 현재 시간(연월일_시분초)을 포함한 CSV 파일 생성
        timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename: str = f"etf_data_{timestamp}.csv"
        
        # 첫 번째 ETF 객체의 키 리스트를 CSV 헤더로 사용
        headers: List[str] = list(etf_list[0].keys())
        
        # CSV 파일 쓰기 (utf-8-sig 인코딩으로 Excel 등에서 한글 깨짐 방지)
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for item in etf_list:
                writer.writerow(item)
                
        print(f"성공적으로 {len(etf_list)}개의 ETF 데이터를 {filename}에 저장했습니다.")
    except Exception as e:
        print(f"오류가 발생했습니다: {e}")

if __name__ == "__main__":
    fetch_and_save()
