# parser.py — 4개 학교 파일 실측 검증 완료
import pandas as pd
import openpyxl, re, unicodedata

def normalize(s):
    """문자열 정규화: 유니코드 통일+공백 압축. 표기 차이 흡수."""
    if s is None: return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", s).strip()

def find_data_sheet(wb):
    """시트명 자동 탐지: '입학생' 키워드 우선, 다음 작성요령·데이터베이스 제외."""
    for n in wb.sheetnames:
        if "입학생" in n: return n
    for n in wb.sheetnames:
        if "작성" not in n and "데이터" not in n: return n
    return wb.sheetnames[0]

def load_sheet(file_or_path):
    """파일 경로 또는 업로드 파일 객체에서 16열 전체를 데이터프레임으로 로드."""
    wb = openpyxl.load_workbook(file_or_path, data_only=True)
    sn = find_data_sheet(wb)
    ws = wb[sn]
    rows = [list(r) for r in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=16, values_only=True)]
    return pd.DataFrame(rows), sn

def detect_anchors(df):
    """키워드 기반 앵커행 자동 탐지: 합계시작, 창체, 학년별 총계."""
    a = {}
    for i, row in df.iterrows():
        joined = " ".join(normalize(v) for v in row if v is not None)
        if "교과 이수 학점 소계" in joined and "sum_start" not in a: a["sum_start"] = i
        if "창의적 체험활동" in joined and "cea" not in a: a["cea"] = i
        if "학년별 총 이수 학점" in joined and "total" not in a: a["total"] = i
    a["data_start"] = 6  # 헤더 R1~R5 다음
    a["data_end"] = a.get("sum_start", len(df)) - 1
    return a

def parse_subjects(df, a):
    """과목 데이터 추출 + 16개 컬럼 의미 부여 + 병합셀 forward-fill."""
    sub = df.iloc[a["data_start"]:a["data_end"]+1].copy()
    sub.columns = ["A_grade","B_group","C_type","D_name","E_base","F_op",
                   "G_1_1","H_1_2","I_2_1","J_2_2","K_3_1","L_3_2",
                   "M_note","N_open","O_credit","P_required"]
    for c in ["A_grade","B_group","O_credit","P_required"]:
        sub[c] = sub[c].ffill()
    for c in ["B_group","C_type","D_name","M_note"]:
        sub[c] = sub[c].apply(normalize)
    return sub.reset_index(drop=True)

def parse_file(file_or_path):
    """상위 함수: 파일 → (원본df, 앵커, 과목df, 시트명)."""
    df_raw, sheet = load_sheet(file_or_path)
    anchors = detect_anchors(df_raw)
    subjects = parse_subjects(df_raw, anchors)
    return df_raw, anchors, subjects, sheet
