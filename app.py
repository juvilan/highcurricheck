# app.py — Streamlit 메인 화면
import streamlit as st
import pandas as pd
from parser import parse_file
from checker import run_checks

st.set_page_config(page_title="교육과정 검토기", layout="wide")
st.title("고등학교 교육과정 자동 검토기")
st.caption("2022 개정 교육과정 학점 배당표 → 자율점검표 기반 21개 기준 자동 검토")

with st.sidebar:
    st.header("사용 방법")
    st.markdown("""
1. 학교에서 작성한 학점 배당표 엑셀(.xlsx) 업로드  
2. 자동으로 시트·과목 인식 → 검토 결과 표 출력  
3. **확인필요** 행을 클릭해 원본 엑셀 해당 셀 직접 점검  
4. 여러 학교를 한 번에 비교하려면 다중 업로드 가능
""")
    st.divider()
    st.caption("검토 근거: 고등학교 교육과정 편성·운영 방향, 자율점검표")

uploaded = st.file_uploader(
    "학점 배당표 엑셀 파일 업로드 (여러 개 동시 가능)",
    type=["xlsx"], accept_multiple_files=True)

if not uploaded:
    st.info("좌측 사이드바의 안내를 참고하여 .xlsx 파일을 업로드해 주세요.")
    st.stop()

for f in uploaded:
    st.divider()
    st.subheader(f"파일: {f.name}")
    try:
        df_raw, anchors, subjects, sheet = parse_file(f)
    except Exception as e:
        st.error(f"파싱 실패: {e}")
        continue

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("인식된 시트", sheet)
    col2.metric("과목 행 수", len(subjects))
    col3.metric("합계 시작 행", anchors.get("sum_start", "?"))
    col4.metric("창체 행", anchors.get("cea", "?"))

    result = run_checks(df_raw, anchors, subjects)

    # 결과 색상 강조
    def color_row(row):
        if "통과" in str(row["결과"]):
            return ["background-color:#dcfce7"] * len(row)
        if "위반" in str(row["결과"]):
            return ["background-color:#fee2e2"] * len(row)
        return ["background-color:#fef3c7"] * len(row)

    st.markdown("#### 검토 결과")
    st.dataframe(result.style.apply(color_row, axis=1),
                 use_container_width=True, hide_index=True)

    with st.expander("파싱된 과목 데이터 보기 (디버깅용)"):
        st.dataframe(subjects, use_container_width=True, height=300)

    # 결과 CSV 다운로드
    st.download_button("검토 결과 CSV 다운로드",
        result.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"검토결과_{f.name}.csv", mime="text/csv")
