"""실시간 네이버 금융 ETF 데이터 분석 및 시각화 대시보드.

이 모듈은 네이버 금융 API로부터 실시간 ETF 데이터를 수집하고,
메모리 내에서 전처리 및 가공을 거쳐 다양한 통계치와 시각화 차트를 제공하는
Streamlit 기반의 종합 EDA 대시보드 애플리케이션입니다.
"""

import re
import json
import urllib.request
from typing import Dict, Any, List, Tuple
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 네이버 금융 ETF API JSONP URL
API_URL: str = (
    "https://finance.naver.com/api/sise/etfItemList.nhn?"
    "etfType=0&targetColumn=market_sum&sortOrder=desc&"
    "_callback=window.__jindo2_callback._7957"
)

# 주요 운용사 브랜드 목록
MAJOR_BRANDS: List[str] = [
    "KODEX", "TIGER", "KBSTAR", "ACE", "SOL", 
    "HANARO", "ARIRANG", "KOSEF", "RISE", "WOORI"
]


@st.cache_data(ttl=10)  # 실시간 데이터 조회를 위해 캐시 수명을 10초로 제한
def fetch_realtime_etf_data() -> pd.DataFrame:
    """네이버 금융 API로부터 실시간 ETF 데이터를 수집하여 DataFrame으로 변환합니다.

    Returns:
        pd.DataFrame: 전처리된 ETF 데이터가 포함된 Pandas DataFrame.
        데이터 수집 실패 시 빈 DataFrame을 반환합니다.
    """
    try:
        # API 호출 시 봇 감지 우회를 위한 User-Agent 설정
        req = urllib.request.Request(
            API_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        
        # HTTP 요청 및 데이터 읽기
        with urllib.request.urlopen(req) as response:
            raw_data: bytes = response.read()
            # UTF-8 복호화 실패 시 한국어 기본 인코딩 cp949 적용
            try:
                html_content: str = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                html_content = raw_data.decode("cp949")
        
        # JSONP callback 구문에서 내부 JSON 문자열 추출 (정규식 사용)
        match = re.search(r"\((.*)\)", html_content, re.DOTALL)
        if not match:
            st.error("API 응답에서 JSON 데이터를 파싱할 수 없습니다.")
            return pd.DataFrame()
            
        json_str: str = match.group(1)
        data_dict: Dict[str, Any] = json.loads(json_str)
        etf_list: List[Dict[str, Any]] = (
            data_dict.get("result", {}).get("etfItemList", [])
        )
        
        if not etf_list:
            st.warning("수집된 ETF 데이터가 없습니다.")
            return pd.DataFrame()
            
        # DataFrame 생성
        df = pd.DataFrame(etf_list)
        return df
        
    except Exception as e:
        st.error(f"데이터 수집 중 오류 발생: {e}")
        return pd.DataFrame()


def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    """수집된 ETF raw 데이터를 정제하고 파생 변수를 생성합니다.

    Args:
        df (pd.DataFrame): API에서 추출된 raw DataFrame.

    Returns:
        pd.DataFrame: 정제 및 파생 변수가 추가된 DataFrame.
    """
    if df.empty:
        return df
        
    # 복사본 생성하여 경고 방지
    df_clean = df.copy()
    
    # 컬럼 타입 숫자형으로 안전하게 변환
    numeric_cols = ["nowVal", "changeVal", "changeRate", "nav", "quant", "amonut", "marketSum"]
    for col in numeric_cols:
        if col in df_clean.columns:
            df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce").fillna(0)
            
    # 3개월 수익률 컬럼 변환
    if "threeMonthEarnRate" in df_clean.columns:
        df_clean["threeMonthEarnRate"] = (
            pd.to_numeric(df_clean["threeMonthEarnRate"], errors="coerce").fillna(0)
        )
        
    # 1. 브랜드(운용사) 파생 변수 생성
    def extract_brand(name: str) -> str:
        """종목명에서 운용사 브랜드를 추출합니다.

        Args:
            name (str): ETF 종목명.

        Returns:
            str: 추출된 브랜드명 또는 '기타'.
        """
        tokens = name.split()
        if not tokens:
            return "기타"
        first_token = tokens[0].upper()
        # 알려진 주요 브랜드에 포함되면 해당 브랜드 반환, 아니면 기타로 분류
        return first_token if first_token in MAJOR_BRANDS else "기타"
        
    df_clean["brand"] = df_clean["itemname"].apply(extract_brand)
    
    # 2. 테마 및 유형 분류 파생 변수 생성
    def classify_theme(name: str) -> str:
        """종목명 키워드를 분석하여 ETF 유형을 분류합니다.

        Args:
            name (str): ETF 종목명.

        Returns:
            str: 분류된 테마 유형명.
        """
        # 고위험 파생 상품 키워드 검사
        if any(keyword in name for keyword in ["레버리지", "인버스", "2X", "선물"]):
            return "고위험/파생"
        # 채권 및 금리형 자산 키워드 검사
        elif any(keyword in name for keyword in ["채권", "국채", "회사채", "KOFR", "CD금리", "금리"]):
            return "채권/금리"
        # 배당 및 인컴 키워드 검사
        elif any(keyword in name for keyword in ["배당", "고배당", "배당귀족", "리츠"]):
            return "배당/인컴"
        # 미국 자산 키워드 검사
        elif "미국" in name:
            return "해외주식(미국)"
        # 미국 외 글로벌 자산 키워드 검사
        elif any(keyword in name for keyword in ["글로벌", "MSCI", "차이나", "중국", "일본", "유럽", "베트남", "인도"]):
            return "해외주식(글로벌)"
        # 액티브 펀드 키워드 검사
        elif "액티브" in name:
            return "국내액티브"
        # 그 외 일반 국내 주식형
        else:
            return "국내주식/일반"
            
    df_clean["theme"] = df_clean["itemname"].apply(classify_theme)
    
    return df_clean


def generate_analyst_report(df: pd.DataFrame, filtered_df: pd.DataFrame) -> str:
    """20년차 데이터 분석가 관점에서 현재 ETF 시장에 대한 심층 인사이트 리포트를 작성합니다.

    Args:
        df (pd.DataFrame): 전체 ETF DataFrame.
        filtered_df (pd.DataFrame): 필터링된 ETF DataFrame.

    Returns:
        str: 마크다운 형식의 상세 분석 리포트.
    """
    total_count = len(df)
    if total_count == 0:
        return "데이터가 존재하지 않아 리포트를 생성할 수 없습니다."
        
    # 주요 통계치 계산
    total_market_sum_trillion = df["marketSum"].sum() * 100000000 / 1000000000000  # 억원 -> 조원 단위 변환
    total_amount_hundred_million = df["amonut"].sum() / 100  # 백만원 -> 억원 단위 변환
    
    # 상승 / 하락 종목 수 계산 (changeRate 기준)
    rising_count = len(df[df["changeRate"] > 0])
    falling_count = len(df[df["changeRate"] < 0])
    flat_count = len(df[df["changeRate"] == 0])
    rising_ratio = (rising_count / total_count) * 100
    
    # 브랜드 점유율
    brand_sums = df.groupby("brand")["marketSum"].sum()
    top_brand = brand_sums.idxmax()
    top_brand_share = (brand_sums.max() / df["marketSum"].sum()) * 100
    
    # 거래대금 상위 종목
    top_amount_etf = df.sort_values(by="amonut", ascending=False).iloc[0]
    
    # 테마별 현황
    theme_perf = df.groupby("theme")["changeRate"].mean().sort_values(ascending=False)
    best_theme = theme_perf.index[0]
    best_theme_perf = theme_perf.iloc[0]
    
    # 리포트 텍스트 생성
    report = f"""
    ### 📊 20년차 시니어 애널리스트의 실시간 시장 진단 리포트

    현재 시각 기준으로 수집된 총 **{total_count:,}개**의 ETF 종목을 바탕으로 실시간 시장 상황을 진단합니다.

    #### 1. 거시 시장 에너지 및 유동성 평가
    오늘 국내 ETF 시장의 전체 시가총액 규모는 약 **{total_market_sum_trillion:.2f}조 원**에 달하며, 금일 발생한 실시간 누적 거래대금은 약 **{total_amount_hundred_million:,.1f}억 원**으로 집계되었습니다. 
    시장 내 상승 종목은 **{rising_count:,}개({rising_ratio:.1f}%)**, 하락 종목은 **{falling_count:,}개**, 보합 종목은 **{flat_count:,}개**로 확인됩니다. 
    상승 종목의 비율이 {rising_ratio:.1f}% 수준인 것으로 보아, 오늘 시장은 {"매수 우위의 긍정적인 수급 흐름" if rising_ratio > 55 else "매도 압력이 우세한 보수적 흐름" if rising_ratio < 45 else "방향성이 뚜렷하지 않은 혼조세 양상"}을 띠고 있습니다.

    #### 2. 거래량 및 시가총액 집중도 분석
    유동성 측면에서 가장 활발한 거래가 일어나는 종목은 **{top_amount_etf['itemname']}**(으)로, 현재까지 단일 종목에서만 **{top_amount_etf['amonut']/100:,.1f}억 원** 규모의 거래대금이 마크되며 시장의 유동성을 집중적으로 흡수하고 있습니다.
    자산운용사별 점유율을 분석한 결과, 시가총액 기준 가장 지배적인 브랜드는 **{top_brand}**(으)로 전체 시장의 **{top_brand_share:.1f}%**를 독식하고 있는 독과점적 양상이 관찰됩니다. 이는 브랜드 인지도 및 선점 효과가 ETF 시장 생태계 내에서 여전히 강력한 진입장벽이자 경쟁력으로 작용하고 있음을 시사합니다.

    #### 3. 테마 및 자산군별 모멘텀 분석
    오늘 자산군별 평균 수익률(등락률) 추이를 살펴보면, **{best_theme}** 테마가 평균 **{best_theme_perf:+.2f}%**의 등락률을 기록하며 시장 전체 상승 랠리를 주도하고 있습니다. 
    반면, 상대적으로 저조한 자산군은 투자자들의 차익 실현 매물 출회 및 거시적 매크로 변수 영향을 받고 있어 포트폴리오 다변화 측면에서 각별한 모니터링이 요구됩니다. 필터링된 조건 하에 노출된 **{len(filtered_df):,}개**의 종목군을 대상으로 상세 분석 테이블을 참고하시어 자산 배분 전략을 정밀하게 튜닝해 보시기 바랍니다.
    """
    return report


def main() -> None:
    """Streamlit 대시보드의 메인 뷰 구성 및 컨트롤러 역할을 수행합니다."""
    # 1. 페이지 설정 및 프리미엄 테마 적용
    st.set_page_config(
        page_title="실시간 네이버 ETF 종합 EDA 대시보드",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # 커스텀 CSS를 통한 디자인 미세조정 (글래스모피즘 분위기 및 부드러운 폰트 설정)
    st.markdown(
        """
        <style>
        .main {
            background-color: #f8f9fa;
        }
        .stMetric {
            background-color: white;
            padding: 15px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
            border: 1px solid #e9ecef;
        }
        div[data-testid="stSidebar"] {
            background-color: #f1f3f5;
        }
        h1, h2, h3 {
            color: #212529;
            font-family: 'Inter', sans-serif;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    # 2. 타이틀 영역 구성
    st.title("📈 실시간 네이버 금융 ETF 종합 EDA 대시보드")
    st.markdown(
        "네이버 금융의 실시간 ETF 데이터를 수집하여 포트폴리오 분포, "
        "자산군별 성과, 거래 대금 집중도를 종합적으로 분석합니다."
    )
    
    # 3. 실시간 데이터 로드
    with st.spinner("네이버 금융 실시간 API로부터 데이터를 가져오는 중..."):
        raw_df = fetch_realtime_etf_data()
        
    if raw_df.empty:
        st.error("데이터를 불러오지 못했습니다. 잠시 후 새로고침 버튼을 눌러주세요.")
        if st.button("🔄 데이터 다시 가져오기"):
            st.rerun()
        return
        
    # 데이터 전처리 및 가공
    df = preprocess_data(raw_df)
    
    # 4. 사이드바 필터 컨트롤 배치
    st.sidebar.header("🔍 대시보드 검색 및 필터")
    
    # 새로고침 버튼 배치
    if st.sidebar.button("🔄 실시간 데이터 갱신", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
        
    # 키워드 검색
    search_query = st.sidebar.text_input("종목명 검색", value="", placeholder="예: 200, 미국, 반도체")
    
    # 운용사(브랜드) 멀티 셀렉트
    all_brands = sorted(df["brand"].unique())
    selected_brands = st.sidebar.multiselect(
        "운용사(브랜드) 선택",
        options=all_brands,
        default=all_brands
    )
    
    # 테마/유형 멀티 셀렉트
    all_themes = sorted(df["theme"].unique())
    selected_themes = st.sidebar.multiselect(
        "자산 유형 선택",
        options=all_themes,
        default=all_themes
    )
    
    # 시가총액 범위 필터 (억원 단위)
    min_market_sum = int(df["marketSum"].min())
    max_market_sum = int(df["marketSum"].max())
    market_sum_range = st.sidebar.slider(
        "시가총액 범위 (억 원)",
        min_value=min_market_sum,
        max_value=max_market_sum,
        value=(min_market_sum, max_market_sum),
        step=500
    )
    
    # 등락률 범위 필터
    min_change_rate = float(df["changeRate"].min())
    max_change_rate = float(df["changeRate"].max())
    change_rate_range = st.sidebar.slider(
        "등락률 범위 (%)",
        min_value=min_change_rate,
        max_value=max_change_rate,
        value=(min_change_rate, max_change_rate),
        step=0.1
    )
    
    # 필터링 조건 적용
    filtered_df = df[
        (df["brand"].isin(selected_brands)) &
        (df["theme"].isin(selected_themes)) &
        (df["marketSum"].between(market_sum_range[0], market_sum_range[1])) &
        (df["changeRate"].between(change_rate_range[0], change_rate_range[1]))
    ]
    
    # 텍스트 검색 쿼리 추가 적용
    if search_query:
        filtered_df = filtered_df[
            filtered_df["itemname"].str.contains(search_query, case=False, na=False)
        ]
        
    # 5. 핵심 지표(KPI) 패널 구성
    kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)
    
    with kpi_col1:
        st.metric(
            label="필터링된 종목 수", 
            value=f"{len(filtered_df):,} 개", 
            delta=f"전체 {len(df):,} 종목 중"
        )
        
    with kpi_col2:
        total_market_sum = filtered_df["marketSum"].sum()
        # 10,000억 원 = 1조 원
        st.metric(
            label="선택 자산 시가총액", 
            value=f"{total_market_sum * 100000000 / 1000000000000:.2f} 조 원",
            delta=f"전체 대비 {(total_market_sum / df['marketSum'].sum() * 100):.1f}%"
        )
        
    with kpi_col3:
        total_amount = filtered_df["amonut"].sum()
        # 100백만 원 = 1억 원
        st.metric(
            label="선택 자산 거래대금", 
            value=f"{total_amount / 100:,.1f} 억 원",
            delta=f"전체 대비 {(total_amount / df['amonut'].sum() * 100):.1f}%"
        )
        
    with kpi_col4:
        # 등락률 평균치
        avg_change = filtered_df["changeRate"].mean()
        # 상승 종목 수와 하락 종목 수 계산
        pos_count = len(filtered_df[filtered_df["changeRate"] > 0])
        neg_count = len(filtered_df[filtered_df["changeRate"] < 0])
        st.metric(
            label="평균 등락률", 
            value=f"{avg_change:+.2f}%", 
            delta=f"🔺 {pos_count} / 🔻 {neg_count}"
        )
        
    st.markdown("---")
    
    # 데이터가 아예 필터링되어 존재하지 않을 경우 에러 방지
    if filtered_df.empty:
        st.warning("선택 조건에 부합하는 ETF 데이터가 없습니다. 필터를 조정해 주세요.")
        return
        
    # 6. 대화형 탭 기반 시각화 및 분석 구성
    tab_overview, tab_distribution, tab_correlation, tab_brand = st.tabs([
        "📊 전체 시장 개요 & 인사이트",
        "📈 등락 및 수익성 분포 분석",
        "🔍 거래 집중도 & 시총 상관관계",
        "🏢 자산운용사(브랜드)별 점유율"
    ])
    
    # --- Tab 1: 전체 시장 개요 & 애널리스트 리포트 ---
    with tab_overview:
        st.subheader("💡 실시간 시장 구조 및 전문 분석 요약")
        
        # 20년차 데이터 분석가 리포트 출력
        st.markdown(generate_analyst_report(df, filtered_df))
        
        st.markdown("---")
        
        # 시가총액 상위 TOP 15 시각화
        st.subheader("🏆 시가총액 상위 TOP 15 ETF 현황")
        top15_df = filtered_df.sort_values(by="marketSum", ascending=False).head(15)
        
        fig_top15 = px.bar(
            top15_df,
            x="marketSum",
            y="itemname",
            orientation="h",
            color="changeRate",
            color_continuous_scale=px.colors.diverging.RdBu_r,
            color_continuous_midpoint=0.0,
            labels={"marketSum": "시가총액 (억 원)", "itemname": "ETF 종목명", "changeRate": "등락률 (%)"},
            title="필터링된 자산 중 시가총액 TOP 15 목록 (색상: 실시간 등락률)"
        )
        # 차트 레이아웃 미려하게 다듬기 (y축 정렬 기준을 total ascending으로 지정하여 시가총액 역순으로 하단부터 배치)
        fig_top15.update_layout(
            yaxis={"categoryorder": "total ascending"},
            height=500,
            margin=dict(l=20, r=20, t=40, b=20),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(fig_top15, use_container_width=True)

    # --- Tab 2: 등락 및 수익성 분포 분석 ---
    with tab_distribution:
        st.subheader("📉 등락률 및 주요 자산 유형별 모멘텀 분석")
        
        col_dist1, col_dist2 = st.columns(2)
        
        with col_dist1:
            # 전체 등락률 분포 히스토그램
            fig_hist = px.histogram(
                filtered_df,
                x="changeRate",
                nbins=30,
                color_discrete_sequence=["#1f77b4"],
                labels={"changeRate": "등락률 (%)", "count": "종목 수"},
                title="실시간 등락률 도수분포표 (전체 시장 심리 지수)",
                marginal="box"  # 상단에 박스플롯 추가하여 정밀 분석 제공
            )
            fig_hist.update_layout(
                height=450,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                bargap=0.05
            )
            st.plotly_chart(fig_hist, use_container_width=True)
            
        with col_dist2:
            # 자산 유형(테마)별 등락률 상자 수염 그림 (변동성 분석)
            fig_box = px.box(
                filtered_df,
                x="theme",
                y="changeRate",
                color="theme",
                labels={"theme": "자산군 유형", "changeRate": "등락률 (%)"},
                title="자산군 유형(테마)별 등락률 분포 및 변동성 (Box Plot)"
            )
            fig_box.update_layout(
                height=450,
                showlegend=False,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig_box, use_container_width=True)

    # --- Tab 3: 거래 집중도 & 시총 상관관계 ---
    with tab_correlation:
        st.subheader("🔍 시가총액 대비 실시간 자금 유입(거래대금) 상관분석")
        
        # 로그 스케일 적용 여부를 토글 옵션으로 제공
        use_log_scale = st.checkbox("시가총액 축에 로그 스케일 적용 (시각화 왜곡 방지)", value=True)
        
        # 거래대금 vs 시가총액 산점도
        fig_scatter = px.scatter(
            filtered_df,
            x="marketSum",
            y="amonut",
            size="quant",  # 버블 크기는 거래량
            color="changeRate",  # 버블 색상은 등락률
            hover_name="itemname",
            hover_data=["nowVal", "brand", "theme"],
            log_x=use_log_scale,
            color_continuous_scale=px.colors.diverging.RdBu_r,
            color_continuous_midpoint=0.0,
            labels={
                "marketSum": "시가총액 (억 원)", 
                "amonut": "거래대금 (백만 원)", 
                "quant": "거래량",
                "changeRate": "등락률 (%)"
            },
            title="시가총액 vs 거래대금 분포도 (버블 크기: 거래량, 색상: 등락률)"
        )
        fig_scatter.update_layout(
            height=550,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
        
        st.markdown(
            "💡 **차트 해석 가이드**: 우상단에 위치할수록 시가총액이 크고 오늘 거래가 집중된 주도주 자산군입니다. "
            "반면 버블의 크기(거래량)가 거대함에도 Y축(거래대금)이 하단에 가깝다면 저가주 위주의 대량 거래 형태를 의미하며, "
            "붉은색(양수) 버블은 강한 매수 에너지가, 푸른색(음수) 버블은 매도 물량 출회를 의미합니다."
        )

    # --- Tab 4: 자산운용사(브랜드)별 점유율 ---
    with tab_brand:
        st.subheader("🏢 국내 자산운용사(브랜드)별 시장 지배력 측정")
        
        col_brand1, col_brand2 = st.columns(2)
        
        # 운용사 데이터 집계
        brand_stats = filtered_df.groupby("brand").agg(
            market_sum_total=("marketSum", "sum"),
            etf_count=("itemcode", "count")
        ).reset_index()
        
        with col_brand1:
            # 시가총액 기준 점유율 도넛 차트
            fig_pie_sum = px.pie(
                brand_stats,
                names="brand",
                values="market_sum_total",
                hole=0.4,
                title="운용사별 시가총액(AUM) 점유율 (%)",
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_pie_sum.update_layout(
                height=450,
                margin=dict(l=20, r=20, t=50, b=20)
            )
            st.plotly_chart(fig_pie_sum, use_container_width=True)
            
        with col_brand2:
            # 종목 수 기준 점유율 도넛 차트
            fig_pie_count = px.pie(
                brand_stats,
                names="brand",
                values="etf_count",
                hole=0.4,
                title="운용사별 상장 종목 수 점유율 (%)",
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_pie_count.update_layout(
                height=450,
                margin=dict(l=20, r=20, t=50, b=20)
            )
            st.plotly_chart(fig_pie_count, use_container_width=True)

    st.markdown("---")
    
    # 7. 전체 데이터 테이블 그리드 출력
    st.subheader("📋 실시간 ETF 통합 원본 데이터 검색 및 다운로드")
    
    # 유저 가독성 극대화를 위한 컬럼명 맵핑 및 정렬
    table_df = filtered_df[[
        "itemcode", "itemname", "nowVal", "changeRate", 
        "marketSum", "amonut", "threeMonthEarnRate", "brand", "theme"
    ]].copy()
    
    table_df.columns = [
        "종목코드", "종목명", "현재가 (원)", "등락률 (%)", 
        "시가총액 (억 원)", "거래대금 (백만 원)", "3개월 수익률 (%)", "운용사", "자산유형"
    ]
    
    # 시가총액 기준 내림차순 정렬
    table_df = table_df.sort_values(by="시가총액 (억 원)", ascending=False)
    
    # Streamlit 데이터프레임으로 미려하게 출력
    st.dataframe(
        table_df, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "종목코드": st.column_config.TextColumn("종목코드"),
            "현재가 (원)": st.column_config.NumberColumn(format="%d"),
            "등락률 (%)": st.column_config.NumberColumn(format="%+.2f"),
            "시가총액 (억 원)": st.column_config.NumberColumn(format="%d"),
            "거래대금 (백만 원)": st.column_config.NumberColumn(format="%d"),
            "3개월 수익률 (%)": st.column_config.NumberColumn(format="%+.2f"),
        }
    )


if __name__ == "__main__":
    main()
