"""Streamlit 교육과정 자동 검토 앱 - 안정 버전"""
import warnings
warnings.filterwarnings("ignore")

import streamlit as st
import pandas as pd
from io import BytesIO
import traceback

st.set_page_config(page_title="교육과정 검토", layout="wide")
st.title("고등학교 교육과정 자동 검토")
st.caption("2022 개정 교육과정 · 자율점검표 기반")

# ----- 모듈 임포트 (실패 시 즉시 표시) -----
try:
    from parser import parse_curriculum
    from checker import check_curriculum
except Exception as e:
    st.error(f"모듈 임포트 실패: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ----- 업로드 -----
uploaded = st.file_uploader(
    "학점 배당표 엑셀 파일 업로드 (.xlsx)",
    type=["xlsx"],
    help="○○고등학교_2026학년도 입학생 교육과정 학점 배당표.xlsx"
)

if not uploaded:
    st.info("파일을 업로드하면 자동으로 검토가 시작됩니다.")
    st.stop()

# ----- 파싱 (BytesIO 방식 - 임시파일 사용 안 함) -----
with st.spinner("파일 파싱 중..."):
    try:
        bio = BytesIO(uploaded.getvalue())
        parsed = parse_curriculum(bio)
        # school 이름은 업로드 파일명에서 추출
        parsed["school"] = uploaded.name.split("_")[0].replace(".xlsx", "")
    except Exception as e:
        st.error(f"파싱 실패: {e}")
        with st.expander("오류 상세"):
            st.code(traceback.format_exc())
        st.stop()

st.success(f"파싱 완료 — 시트: `{parsed['sheet']}` · 과목 행: {len(parsed['rows'])}개")

# ----- 검토 -----
with st.spinner("검토 기준 적용 중..."):
    try:
        results = check_curriculum(parsed)
    except Exception as e:
        st.error(f"검토 실패: {e}")
        with st.expander("오류 상세"):
            st.code(traceback.format_exc())
        st.stop()

# ----- 헤더 -----
st.markdown("---")
st.subheader(f"{parsed['school']} 검토 결과")
st.caption(f"검토 단위: {len(results)}개")

# ----- 종합 판정 카드 -----
counts = {k: sum(1 for r in results if r['결과'] == k)
          for k in ['PASS', 'FAIL', 'WARN', 'INFO', 'N/A']}
colors = {'PASS':'#15803d','FAIL':'#b91c1c','WARN':'#b45309',
          'INFO':'#4b5563','N/A':'#6b7280'}

cols = st.columns(5)
for col, (k, v) in zip(cols, counts.items()):
    col.markdown(
        f"<div style='border:1px solid #d1d5db;border-radius:8px;padding:12px'>"
        f"<div style='font-size:11px;color:#6b7280'>{k}</div>"
        f"<div style='font-size:28px;font-weight:600;color:{colors[k]};"
        f"margin-top:4px'>{v}</div></div>",
        unsafe_allow_html=True
    )

# ----- FAIL/WARN 콜아웃 -----
st.markdown("### 주요 발견 사항")
fails = [r for r in results if r['결과'] == 'FAIL']
warns = [r for r in results if r['결과'] == 'WARN']

if not fails and not warns:
    st.success("FAIL/WARN 항목 없음. 모든 정량 기준 통과.")

for r in fails:
    st.error(f"**FAIL · {r['id']}** {r['항목']} — {r['근거']}")
for r in warns:
    st.warning(f"**WARN · {r['id']}** {r['항목']} — {r['근거']}")

# ----- 영역별 상세 (Styler 없이 plain DataFrame) -----
st.markdown("### 영역별 상세 검토 결과")
df = pd.DataFrame(results)

for area in sorted(df['영역'].unique()):
    sub = df[df['영역'] == area][['id','항목','기준','측정값','결과','근거']].reset_index(drop=True)
    st.markdown(f"**{area}**")
    # Styler 사용 안 함 - column_config로 충분
    st.dataframe(
        sub,
        use_container_width=True,
        hide_index=True,
        column_config={
            "결과": st.column_config.TextColumn("결과", width="small"),
            "근거": st.column_config.TextColumn("근거", width="large"),
        }
    )

# ----- CSV 다운로드 -----
st.markdown("### 결과 내보내기")
csv = df.to_csv(index=False).encode('utf-8-sig')
st.download_button(
    label="검토 결과 CSV 다운로드",
    data=csv,
    file_name=f"{parsed['school']}_검토결과.csv",
    mime="text/csv"
)

# ----- 디버그 정보 (접힘) -----
with st.expander("디버그 정보"):
    st.json({
        "시트명": parsed['sheet'],
        "header_row": parsed['header_row'],
        "data_start": parsed['data_start'],
        "summary_start": parsed['summary_start'],
        "summary": parsed['summary'],
        "과목수": len(parsed['rows']),
    })
