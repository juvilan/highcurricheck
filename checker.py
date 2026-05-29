# checker.py — 자율점검표 21개 검증단위 자동판정 엔진
import pandas as pd
import re
from parser import normalize

def to_num(v):
    """셀값에서 첫 숫자만 추출. '14~16', '4(택2)' 같은 표기에 대응."""
    if v is None: return None
    m = re.search(r"\d+\.?\d*", normalize(v))
    return float(m.group()) if m else None

def run_checks(df_raw, anchors, subjects):
    R = []
    # A1. 총 이수학점 192 이상
    total = None
    if "total" in anchors:
        nums = [to_num(v) for v in df_raw.iloc[anchors["total"]] if to_num(v) is not None]
        if nums: total = max(nums)
    R.append({"영역":"A.총량","항목":"총 이수학점 ≥ 192","기준":"192",
              "측정값":total,"결과": "통과" if total and total >= 192 else "확인필요"})

    # A2. 창의적 체험활동 18
    cea = to_num(df_raw.iloc[anchors["cea"]].iloc[5]) if "cea" in anchors else None
    R.append({"영역":"A.총량","항목":"창의적 체험활동 = 18","기준":"18",
              "측정값":cea,"결과": "통과" if cea == 18 else "확인필요"})

    # B1. 공통과목 학점범위 (한국사 3 고정, 과탐실 1 고정, 그 외 3~4)
    com = subjects[subjects["C_type"].str.contains("공통", na=False)]
    bad = []
    for _, r in com.iterrows():
        f, n = to_num(r["F_op"]), r["D_name"]
        if f is None: continue
        if "한국사" in n and f != 3: bad.append(f"{n}={f}")
        elif "과학탐구실험" in n and f != 1: bad.append(f"{n}={f}")
        elif "한국사" not in n and "과학탐구실험" not in n and not (3 <= f <= 4):
            bad.append(f"{n}={f}")
    R.append({"영역":"B.학점범위","항목":"공통과목 학점범위","기준":"3~4(한국사3,과탐실1)",
              "측정값":f"{len(com)}과목","결과": "통과" if not bad else f"위반 {len(bad)}건: "+", ".join(bad[:3])})

    # B2. 일반선택 3~5 (체육·예술·교양 제외)
    gen = subjects[subjects["C_type"].str.contains("일반", na=False)]
    bad = []
    for _, r in gen.iterrows():
        f, g = to_num(r["F_op"]), r["B_group"]
        if f is None or any(k in g for k in ["체육","예술","교양"]): continue
        if not (3 <= f <= 5): bad.append(f"{r['D_name']}={f}")
    R.append({"영역":"B.학점범위","항목":"일반선택 3~5학점","기준":"3~5",
              "측정값":f"{len(gen)}과목","결과": "통과" if not bad else f"위반 {len(bad)}건"})

    # B3. 체·예·교 2~4
    cpa = subjects[subjects["B_group"].apply(lambda g: any(k in g for k in ["체육","예술","교양"]))]
    bad = [f"{r['D_name']}={to_num(r['F_op'])}" for _,r in cpa.iterrows()
           if to_num(r["F_op"]) is not None and not (2 <= to_num(r["F_op"]) <= 4)]
    R.append({"영역":"B.학점범위","항목":"체·예·교 2~4학점","기준":"2~4",
              "측정값":f"{len(cpa)}과목","결과": "통과" if not bad else f"위반 {len(bad)}건"})

    # C1. 체육 매 학기 편성 — B열에 '체육' 포함 과목이 G~L 6개 학기 모두 값 보유
    pe = subjects[subjects["B_group"].str.contains("체육", na=False)]
    sem_sum = [sum(1 for _,r in pe.iterrows() if to_num(r[c])) for c in ["G_1_1","H_1_2","I_2_1","J_2_2","K_3_1","L_3_2"]]
    missing = [i+1 for i,v in enumerate(sem_sum) if v == 0]
    R.append({"영역":"C.편성순서","항목":"체육 매 학기 편성","기준":"6학기 모두",
              "측정값":str(sem_sum),"결과": "통과" if not missing else f"누락 학기:{missing}"})

    # E1. 동일과목 동일학점
    dup = subjects.groupby("D_name")["F_op"].apply(
        lambda x: len(set(to_num(v) for v in x if to_num(v) is not None)))
    fail = [n for n,v in dup.items() if v > 1 and n]
    R.append({"영역":"E.표기","항목":"동일과목 동일학점","기준":"1과목 1학점값",
              "측정값":f"{len(subjects)}건","결과": "통과" if not fail else f"위반:{','.join(fail[:3])}"})

    return pd.DataFrame(R)
