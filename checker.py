"""자율점검표 19개 검토 단위 자동 판정"""
import re
from collections import defaultdict

def check_curriculum(parsed):
    R, rows, summary = [], parsed['rows'], parsed['summary']

    def add(id_, area, item, std, val, result, ev):
        R.append({"id": id_, "영역": area, "항목": item, "기준": std,
                  "측정값": val, "결과": result, "근거": ev})

    # ====== A. 총량 ======
    total = sum(summary.get('총학기') or [])
    gyo = sum(summary.get('교과학기') or []) or summary.get('교과소계')
    chang = summary.get('창체')
    add("A1","A.총량","총 이수 학점 ≥ 192","192학점 이상",
        f"{total:.0f}" if total else "미산출",
        "PASS" if total and total >= 192 else "FAIL",
        f"학기별 합 = {summary.get('총학기')}")
    add("A2","A.총량","교과 174학점","174학점",
        f"{gyo:.0f}" if gyo else "미산출",
        "PASS" if gyo == 174 else "FAIL", "교과 이수 학점 소계")
    add("A3","A.총량","필수 이수 학점 ≥ 84","84학점 이상",
        "수동확인 권장","INFO","비고/색상 마킹 분석 필요")
    add("A4","A.총량","창의적 체험활동 18학점","18학점(288시간)",
        f"{chang:.0f}" if chang else "미산출",
        "PASS" if chang == 18 else "FAIL", f"학기별 = {summary.get('창체학기')}")

    # ====== B. 학점 범위 ======
    in_r = lambda v,lo,hi: v is not None and lo <= v <= hi
    체예교군 = {'체육','예술','교양','음악','미술'}
    is_체예교 = lambda x: any(g in x['교과군'].replace(' ','') for g in 체예교군)

    nb1 = []
    for x in [x for x in rows if x['과목유형']=='공통']:
        nm, run = x['과목명'], x['운영학점']
        if '한국사' in nm and run != 3: nb1.append((x['row'], nm, run, '한국사≠3'))
        elif '과학탐구실험' in nm and run != 1: nb1.append((x['row'], nm, run, '과탐실≠1'))
        elif '한국사' not in nm and '과학탐구실험' not in nm and not in_r(run,3,4):
            nb1.append((x['row'], nm, run, '공통≠3~4'))
    add("B1","B.학점범위","공통과목 운영학점","공통 3~4, 한국사 3, 과탐실 1",
        f"위반 {len(nb1)}건","PASS" if not nb1 else "FAIL",
        "; ".join([f"R{a} {b}={c}({d})" for a,b,c,d in nb1]) or "이상 없음")

    nb2 = [x for x in rows if x['과목유형']=='일반선택' and not is_체예교(x) and not in_r(x['운영학점'],3,5)]
    add("B2","B.학점범위","일반선택 3~5","3~5학점",f"위반 {len(nb2)}건",
        "PASS" if not nb2 else "FAIL",
        "; ".join([f"R{x['row']} {x['과목명']}={x['운영학점']}" for x in nb2]) or "이상 없음")

    nb3 = [x for x in rows if x['과목유형'] in ('진로선택','융합선택')
           and not is_체예교(x) and not in_r(x['운영학점'],3,5)]
    add("B3","B.학점범위","진로·융합선택 3~5","3~5학점",f"위반 {len(nb3)}건",
        "PASS" if not nb3 else "FAIL",
        "; ".join([f"R{x['row']} {x['과목명']}={x['운영학점']}" for x in nb3]) or "이상 없음")

    nb4 = []
    예외 = {'스포츠 문화','스포츠 과학','생애 설계와 자립'}
    for x in [x for x in rows if is_체예교(x) and x['과목유형']!='공통']:
        if any(k in x['과목명'] for k in 예외):
            if not in_r(x['운영학점'],1,2): nb4.append((x['row'], x['과목명'], x['운영학점'], '특수≠1~2'))
        elif not in_r(x['운영학점'],2,4):
            nb4.append((x['row'], x['과목명'], x['운영학점'], '체예교≠2~4'))
    add("B4","B.학점범위","체육·예술·교양 2~4 (특수 1~2)","2~4, 특수 1~2",
        f"위반 {len(nb4)}건","PASS" if not nb4 else "FAIL",
        "; ".join([f"R{a} {b}={c}({d})" for a,b,c,d in nb4]) or "이상 없음")

    name_map = defaultdict(list)
    for x in rows: name_map[x['과목명']].append(x)
    nb5 = []
    for nm, lst in name_map.items():
        cs = set([x['운영학점'] for x in lst if x['운영학점'] is not None])
        if len(cs) > 1: nb5.append((nm, [(x['row'], x['운영학점']) for x in lst]))
    add("B5","B.학점범위","동일 과목 동일 운영학점","동명 다른 학점 금지",
        f"위반 {len(nb5)}건","PASS" if not nb5 else "FAIL",
        "; ".join([f"{nm}: " + ", ".join([f'R{r}={c}' for r,c in p]) for nm,p in nb5]) or "이상 없음")

    # ====== C. 편성 순서 ======
    공통_max = max([x['row'] for x in rows if x['과목유형']=='공통'], default=0)
    선택_min = min([x['row'] for x in rows if x['과목유형'] in ('일반선택','진로선택','융합선택')], default=10**9)
    add("C1","C.편성순서","공통 → 선택 순서","공통 행 < 선택 행",
        f"공통 R{공통_max} / 선택 R{선택_min}",
        "PASS" if 공통_max < 선택_min else "FAIL", "행 순서 비교")

    pairs = defaultdict(dict)
    for x in rows:
        m = re.search(r'(.+?)(Ⅰ|Ⅱ|I|II)\s*$', x['과목명'])
        if m:
            pairs[m.group(1).strip()][1 if m.group(2) in ('Ⅰ','I') else 2] = x
    nc2 = [(b, d[1]['row'], d[2]['row']) for b,d in pairs.items()
           if 1 in d and 2 in d and d[1]['row'] > d[2]['row']]
    add("C2","C.편성순서","위계 과목 Ⅰ → Ⅱ 순서","Ⅰ을 Ⅱ보다 먼저",
        f"위반 {len(nc2)}건","PASS" if not nc2 else "FAIL",
        "; ".join([f"{b}: Ⅰ=R{r1}, Ⅱ=R{r2}" for b,r1,r2 in nc2]) or "이상 없음")

    pe = [0]*6
    for x in rows:
        if '체육' in x['교과군'].replace(' ',''):
            for i, k in enumerate(['1-1','1-2','2-1','2-2','3-1','3-2']):
                if x[k]: pe[i] += 1
    miss = [i+1 for i,v in enumerate(pe) if v == 0]
    add("C3","C.편성순서","체육 매 학기 편성","6학기 모두 ≥ 1",
        f"학기별 편성 과목수={pe}","PASS" if not miss else "FAIL",
        "전 학기 편성" if not miss else f"미편성 학기={miss}")

    g1 = [x for x in rows if x['과목유형'] in ('일반선택','진로선택','융합선택') and (x['1-1'] or x['1-2'])]
    add("C4","C.편성순서","1학년 선택과목 지양","1학년 공통 위주",
        f"1학년 선택 {len(g1)}건",
        "PASS" if not g1 else ("WARN" if all(is_체예교(x) for x in g1) else "FAIL"),
        "; ".join([f"R{x['row']} {x['과목명']}" for x in g1]) or "없음")

    종교 = [x for x in rows if '종교' in x['과목명']]
    add("C5","C.편성순서","종교 과목 복수 편성","종교+종교외",
        f"종교 {len(종교)}건","N/A" if not 종교 else "INFO",
        "종교 미편성" if not 종교 else "수동 확인")

    # ====== D. 균형 ======
    tt = summary.get('총학기') or []
    if tt and all(t is not None for t in tt):
        diff = max(tt) - min(tt)
        add("D1","D.균형","학기 간 차이 ≤ 5","최대-최소 ≤ 5",
            f"차이={diff:.0f}", "PASS" if diff <= 5 else "FAIL", f"학기별={tt}")
    else:
        add("D1","D.균형","학기 간 차이 ≤ 5","≤ 5","미산출","INFO","학기별 누락")

    KSE = sum([(x['운영학점'] or 0) for x in rows if x['교과군'].replace(' ','') in ('국어','수학','영어')])
    add("D2","D.균형","국·수·영 합계 ≤ 81","≤ 81학점",f"{KSE:.0f}",
        "PASS" if KSE <= 81 else "FAIL", "국+수+영 운영학점 합")

    add("D3","D.균형","교과 174 초과분 50% 룰","초과분의 50% 진
