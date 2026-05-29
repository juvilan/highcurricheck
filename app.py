"""Streamlit 교육과정 자동 검토 앱 - 디스크 파일 방식"""
import warnings
warnings.filterwarnings("ignore")

import streamlit as st
import pandas as pd
import os
import traceback

st.set_page_config(page_title="교육과정 검토", layout="wide")
st.title("고등학교 교육과정 자동 검토")
st.caption("2022 개정 교육과정 · 자율점검표 기반")

# ----- 모듈 임포트 -----
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
    type=["xlsx"]
)

if not uploaded:
    st.info("파일을 업로드하면 자동으로 검토가 시작됩니다.")
    st.stop()

# ----- 디스크에 저장 (BytesIO 사용 금지) -----
UPLOAD_DIR = "/tmp/curri_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
safe_name = uploaded.name.replace("/", "_").replace("\\", "_")
tmp_path = os.path.join(UPLOAD_DIR, safe_name)

with open(tmp_path, "wb") as f:
    f.write(uploaded.getvalue())

st.caption(f"임시 저장 경로: `{tmp_path}`")

# ----- 파싱 -----
with st.spinner("파일 파싱 중..."):
    try:
        parsed = parse_curriculum(tmp_path)
    except Exception as e:
        st.error(f"파싱 실패: {e}")
        with st.expander("오류 상세"):
            st.code(traceback.format_exc())
        # 진단 정보
        try:
            import openpyxl
            wb_probe = openpyxl.load_workbook(tmp_path, data_only=True, read_only=True)
            st.write("워크북 시트 목록:", wb_probe.sheetnames)
        except Exception as e2:
            st.write(f"진단도 실패: {e2}")
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

# ----- 임시 파일 삭제 -----
try:
    os.unlink(tmp_path)
except Exception:
    pass

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

# ----- 영역별 상세 -----
st.markdown("### 영역별 상세 검토 결과")
df = pd.DataFrame(results)

for area in sorted(df['영역'].unique()):
    sub = df[df['영역'] == area][['id','항목','기준','측정값','결과','근거']].reset_index(drop=True)
    st.markdown(f"**{area}**")
    st.dataframe(sub, use_container_width=True, hide_index=True)

# ----- CSV 다운로드 -----
st.markdown("### 결과 내보내기")
csv = df.to_csv(index=False).encode('utf-8-sig')
st.download_button(
    label="검토 결과 CSV 다운로드",
    data=csv,
    file_name=f"{parsed['school']}_검토결과.csv",
    mime="text/csv"
)

# ----- 디버그 정보 -----
with st.expander("디버그 정보"):
    st.json({
        "시트명": parsed['sheet'],
        "header_row": parsed['header_row'],
        "data_start": parsed['data_start'],
        "summary_start": parsed['summary_start'],
        "summary": parsed['summary'],
        "과목수": len(parsed['rows']),
    })
