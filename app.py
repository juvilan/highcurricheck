import streamlit as st
import pandas as pd
from parser import parse_curriculum
from checker import check_curriculum
import tempfile, os

st.set_page_config(page_title="교육과정 검토", layout="wide")
st.title("고등학교 교육과정 자동 검토")
st.caption("자율점검표 19개 검토 단위 자동 판정 · 2022 개정 교육과정")

f = st.file_uploader("학점 배당표 엑셀 파일 업로드 (.xlsx)", type=["xlsx"])
if not f:
    st.info("학교에서 작성한 '○○고등학교_2026학년도 입학생 ...xlsx' 파일을 업로드하세요.")
    st.stop()

# 임시 파일로 저장 후 파싱
with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
    tmp.write(f.read()); path = tmp.name
try:
    parsed = parse_curriculum(path)
    results = check_curriculum(parsed)
finally:
    os.unlink(path)

# 헤더
c1, c2 = st.columns([3, 2])
with c1:
    st.subheader(f"{parsed['school']} 교육과정 검토 결과")
    st.caption(f"시트: {parsed['sheet']} · 과목 행: {len(parsed['rows'])}개 · 검토 단위: {len(results)}개")

# 종합 판정 카드 5개
counts = {k: sum(1 for r in results if r['결과'] == k)
          for k in ['PASS','FAIL','WARN','INFO','N/A']}
cols = st.columns(5)
colors = {'PASS':'#15803d','FAIL':'#b91c1c','WARN':'#b45309','INFO':'#4b5563','N/A':'#6b7280'}
for col, (k, v) in zip(cols, counts.items()):
    col.markdown(f"""
    <div style='border:1px solid #d1d5db;border-radius:8px;padding:12px;'>
      <div style='font-size:11px;color:#6b7280'>{k}</div>
      <div style='font-size:24px;font-weight:600;color:{colors[k]};margin-top:4px'>{v}</div>
    </div>""", unsafe_allow_html=True)

# FAIL·WARN 콜아웃 (시뮬레이션의 빨간/노란 박스)
st.markdown("### 주요 발견 사항")
fails = [r for r in results if r['결과'] == 'FAIL']
warns = [r for r in results if r['결과'] == 'WARN']
if not fails and not warns:
    st.success("FAIL/WARN 항목 없음. 모든 정량 기준 통과.")
for r in fails:
    st.error(f"**FAIL · {r['id']}** {r['항목']} — {r['근거']}")
for r in warns:
    st.warning(f"**WARN · {r['id']}** {r['항목']} — {r['근거']}")

# 영역별 상세 테이블
st.markdown("### 영역별 상세 검토 결과")
df = pd.DataFrame(results)
def color_result(v):
    return f"background-color: {'#dcfce7' if v=='PASS' else '#fee2e2' if v=='FAIL' else '#fef3c7' if v=='WARN' else '#e5e7eb' if v=='INFO' else '#f3f4f6'}"

for area in ['A.총량','B.학점범위','C.편성순서','D.균형','E.표기']:
    sub = df[df['영역'] == area][['id','항목','기준','측정값','결과','근거']]
    if sub.empty: continue
    st.markdown(f"**{area}**")
    st.dataframe(sub.style.applymap(color_result, subset=['결과']),
                 use_container_width=True, hide_index=True)

# CSV 다운로드 버튼
st.markdown("### 결과 내보내기")
csv = df.to_csv(index=False).encode('utf-8-sig')
st.download_button("검토 결과 CSV 다운로드", csv,
                   file_name=f"{parsed['school']}_검토결과.csv", mime="text/csv")
