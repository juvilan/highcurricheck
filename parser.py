"""교육과정 학점 배당표 엑셀 파서 — BytesIO/경로 모두 지원"""
import warnings
warnings.filterwarnings("ignore")

import openpyxl
import re
import unicodedata
from pathlib import Path
from io import BytesIO


def _norm(s):
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("\n", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip()


def _to_num(v):
    """'28~30', '[2]', '3(택2)' 등에서 첫 숫자 추출"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else None


def find_target_sheet(wb):
    """'xxxx입학생' 시트 탐지 (괄호 부기·공백 허용)"""
    for name in wb.sheetnames:
        if re.search(r"\d{4}\s*입학생", name):
            return name
    return None


def find_data_range(ws):
    """헤더/데이터/합계 영역 행 번호 자동 탐지"""
    header_row, data_start, summary_start = None, None, None
    for r in range(1, min(ws.max_row, 30) + 1):
        if _norm(ws.cell(r, 2).value) == "교과(군)":
            header_row, data_start = r, r + 4
            break
    for r in range(ws.max_row, 0, -1):
        for c in range(1, 5):
            v = _norm(ws.cell(r, c).value).replace(" ", "")
            if "교과이수학점소계" in v:
                summary_start = r
                break
        if summary_start:
            break
    return header_row, data_start, summary_start


def parse_curriculum(source):
    """
    source: 파일 경로(str/Path) 또는 BytesIO 객체 모두 허용
    """
    # ----- 워크북 로드 (타입에 따라 분기) -----
    wb = openpyxl.load_workbook(source, data_only=True)

    sheet = find_target_sheet(wb)
    if not sheet:
        raise ValueError(
            f"'xxxx입학생' 시트를 찾을 수 없습니다. 시트 목록: {wb.sheetnames}"
        )
    ws = wb[sheet]

    h, ds, ss = find_data_range(ws)
    if not (h and ds and ss):
        raise ValueError(
            f"데이터 범위 탐지 실패 (header={h}, data_start={ds}, summary_start={ss})"
        )

    # ----- 병합 셀 forward-fill -----
    mmap = {}
    for mr in ws.merged_cells.ranges:
        top = ws.cell(mr.min_row, mr.min_col).value
        for r in range(mr.min_row, mr.max_row + 1):
            for c in range(mr.min_col, mr.max_col + 1):
                mmap[(r, c)] = top

    def cell(r, c):
        return mmap.get((r, c), ws.cell(r, c).value)

    # ----- 과목 행 파싱 -----
    rows = []
    last_g, last_t = "", ""
    for r in range(ds, ss):
        gun = _norm(cell(r, 2))
        typ = _norm(cell(r, 3))
        subj = _norm(cell(r, 4))
        if gun:
            last_g = gun
        else:
            gun = last_g
        if typ:
            last_t = typ
        else:
            typ = last_t
        if not subj:
            continue
        rows.append({
            "row": r,
            "교과군": gun,
            "과목유형": typ,
            "과목명": subj,
            "기본학점": _to_num(cell(r, 5)),
            "운영학점": _to_num(cell(r, 6)),
            "1-1": _to_num(cell(r, 7)),
            "1-2": _to_num(cell(r, 8)),
            "2-1": _to_num(cell(r, 9)),
            "2-2": _to_num(cell(r, 10)),
            "3-1": _to_num(cell(r, 11)),
            "3-2": _to_num(cell(r, 12)),
            "비고": _norm(cell(r, 13)),
        })

    # ----- 합계 영역 파싱 -----
    summary = {}
    for r in range(ss, min(ws.max_row, ss + 10) + 1):
        for c in range(1, 5):
            lbl = _norm(cell(r, c))
            if not lbl:
                continue
            terms = [_to_num(cell(r, c2)) for c2 in range(7, 13)]
            if "교과 이수 학점 소계" in lbl:
                summary["교과소계"] = _to_num(cell(r, 6))
                summary["교과학기"] = terms
            if "창의적 체험활동" in lbl:
                summary["창체"] = _to_num(cell(r, 6))
                summary["창체학기"] = terms
            if ("총 이수" in lbl or "학년별" in lbl) and "총학기" not in summary:
                summary["총학기"] = terms

    # ----- school 추출 (타입 분기) -----
    if isinstance(source, (str, Path)):
        school = Path(source).stem.split("_")[0]
    else:
        # BytesIO 등 파일 객체 - 호출자가 별도로 school을 채워야 함
        school = "업로드 파일"

    return {
        "school": school,
        "sheet": sheet,
        "header_row": h,
        "data_start": ds,
        "summary_start": ss,
        "rows": rows,
        "summary": summary,
    }
