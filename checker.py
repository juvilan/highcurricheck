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
    typ = lambda x: (x['과목유형'] or '').replace(' ','')  # 과목유형 공백 무시 비교
    # 과목유형 약어/정식 통일: '일반'='일반선택', '진로'='진로선택', '융합'='융합선택', '공통'
    base_type = lambda x: typ(x).replace('선택', '')

    def add_sel_range(id_, item, std, violations, lo):
        """선택과목 학점범위 위반 결과. 하한(lo) 미달 위반은 고시 외 과목(1~2 가능)일 수
        있어 WARN+수동확인, 상한 초과 등 그 외 위반은 FAIL."""
        low = [x for x in violations if x['운영학점'] is not None and x['운영학점'] < lo]
        hard = [x for x in violations if x not in low]
        fmt = lambda V: "; ".join(f"R{x['row']} {x['과목명']}={x['운영학점']}" for x in V)
        if not violations:
            res, ev = "PASS", "이상 없음"
        elif hard:
            res, ev = "FAIL", fmt(violations)
        else:
            res, ev = "WARN", "저학점 위반 — 고시 외 과목이면 1~2학점 정상, 수동확인: " + fmt(low)
        add(id_, "B.학점범위", item, std, f"위반 {len(violations)}건", res, ev)

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

    nb2 = [x for x in rows if base_type(x)=='일반' and not is_체예교(x) and not in_r(x['운영학점'],3,5)]
    add_sel_range("B2","일반선택 3~5","3~5학점", nb2, 3)

    nb3 = [x for x in rows if base_type(x) in ('진로','융합')
           and not is_체예교(x) and not in_r(x['운영학점'],3,5)]
    add_sel_range("B3","진로·융합선택 3~5","3~5학점", nb3, 3)

    nb4 = []
    예외 = {'스포츠 문화','스포츠 과학','생애 설계와 자립'}
    for x in [x for x in rows if is_체예교(x) and typ(x)!='공통']:
        if any(k in x['과목명'] for k in 예외):
            if not in_r(x['운영학점'],1,2): nb4.append((x['row'], x['과목명'], x['운영학점'], '특수≠1~2'))
        elif not in_r(x['운영학점'],2,4):
            nb4.append((x['row'], x['과목명'], x['운영학점'], '체예교≠2~4'))
    # 체예교 하한(2) 미달은 고시 외 과목(1~2 가능) 가능성 → WARN+수동확인
    low4 = [t for t in nb4 if t[3]=='체예교≠2~4' and t[2] is not None and t[2] < 2]
    hard4 = [t for t in nb4 if t not in low4]
    fmt4 = lambda V: "; ".join(f"R{a} {b}={c}({d})" for a,b,c,d in V)
    if not nb4:
        res4, ev4 = "PASS", "이상 없음"
    elif hard4:
        res4, ev4 = "FAIL", fmt4(nb4)
    else:
        res4, ev4 = "WARN", "저학점 위반 — 고시 외 과목이면 1~2학점 정상, 수동확인: " + fmt4(low4)
    add("B4","B.학점범위","체육·예술·교양 2~4 (특수 1~2)","2~4, 특수 1~2",
        f"위반 {len(nb4)}건", res4, ev4)

    name_map = defaultdict(list)
    for x in rows: name_map[x['과목명']].append(x)
    nb5 = []
    for nm, lst in name_map.items():
        cs = set([x['운영학점'] for x in lst if x['운영학점'] is not None])
        if len(cs) > 1: nb5.append((nm, [(x['row'], x['운영학점']) for x in lst]))
    add("B5","B.학점범위","동일 과목 동일 운영학점","동명 다른 학점 금지",
        f"위반 {len(nb5)}건","PASS" if not nb5 else "FAIL",
        "; ".join([f"{nm}: " + ", ".join([f'R{r}={c}' for r,c in p]) for nm,p in nb5]) or "이상 없음")

    # B6: 운영학점 = 학기 배치 합. 교차이수([])·선택그룹(병합 총합)·학기 미배정은 제외.
    nb6 = []
    for x in rows:
        op = x['운영학점']
        if op is None or x.get('교차이수표기') or x.get('그룹배치'):
            continue
        s = x.get('배치합', 0)
        if not s:           # 학기 미배정 → 여기선 제외
            continue
        if abs(s - op) > 1e-6:
            nb6.append((x['row'], x['과목명'], op, s))
    add("B6","B.학점범위","운영학점 = 학기 배치 합","운영학점과 학기배정 합 일치",
        f"불일치 {len(nb6)}건","PASS" if not nb6 else "FAIL",
        "; ".join(f"R{r} {nm}: 운영{o:.0f}≠배치{s:.0f}" for r,nm,o,s in nb6) or "이상 없음")

    # B7: 한국사 Ⅰ·Ⅱ 모두 편성 + 각 3학점 (2022 개정: 한국사1/2 각 3, 총 6)
    ks = [x for x in rows if '한국사' in x['과목명']]
    ks1 = [x for x in ks if '1' in x['과목명'] or 'Ⅰ' in x['과목명']]
    ks2 = [x for x in ks if '2' in x['과목명'] or 'Ⅱ' in x['과목명']]
    ks_bad = [x for x in ks if x['운영학점'] is not None and x['운영학점'] != 3]
    ks_prob = []
    if not ks1: ks_prob.append("한국사1(Ⅰ) 미편성")
    if not ks2: ks_prob.append("한국사2(Ⅱ) 미편성")
    ks_prob += [f"R{x['row']} {x['과목명']}={x['운영학점']}(≠3)" for x in ks_bad]
    add("B7","B.학점범위","한국사 1·2 각 3학점","한국사Ⅰ·Ⅱ 모두 편성, 각 3학점",
        f"한국사 {len(ks)}건",
        "PASS" if (ks1 and ks2 and not ks_bad) else "FAIL",
        "; ".join(ks_prob) if ks_prob
        else "한국사Ⅰ·Ⅱ 각 3학점 정상 (" + ", ".join(f"{x['과목명']}={x['운영학점']}" for x in ks) + ")")

    # ====== C. 편성 순서 ======
    # C1: 교과군별로 공통 과목이 선택 과목보다 앞 행에 와야 함. (표가 교과군별로
    # 정리돼 있으므로 시트 전체 글로벌 비교는 오탐 → 같은 교과군 안에서만 비교)
    gun_co = defaultdict(list); gun_sel = defaultdict(list)
    for x in rows:
        bt = base_type(x); key = x['교과군'].replace(' ', '')
        if bt == '공통': gun_co[key].append(x['row'])
        elif bt in ('일반', '진로', '융합'): gun_sel[key].append(x['row'])
    nc1 = []
    for g in gun_co:
        if gun_co[g] and gun_sel.get(g) and max(gun_co[g]) > min(gun_sel[g]):
            nc1.append((g, max(gun_co[g]), min(gun_sel[g])))
    add("C1","C.편성순서","공통 → 선택 순서(교과군별)","교과군 내 공통 행 < 선택 행",
        f"위반 {len(nc1)}건","PASS" if not nc1 else "FAIL",
        "; ".join(f"{g}: 공통 R{c} > 선택 R{s}" for g,c,s in nc1) or "이상 없음")

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

    g1 = [x for x in rows if base_type(x) in ('일반','진로','융합') and (x['1-1'] or x['1-2'])]
    # 체예교·교차이수([]) 과목은 1학년 편성이 정상일 수 있어 완화(WARN), 그 외는 FAIL.
    완화 = lambda x: is_체예교(x) or bool(x.get('교차이수표기'))
    진짜위반 = [x for x in g1 if not 완화(x)]
    if not g1:
        c4_res, c4_ev = "PASS", "없음"
    elif 진짜위반:
        c4_res = "FAIL"
        c4_ev = "1학년 선택(체예교·교차이수 외): " + "; ".join(f"R{x['row']} {x['과목명']}" for x in 진짜위반)
    else:
        c4_res = "WARN"
        c4_ev = ("1학년 선택과목이나 체예교/교차이수라 정상일 수 있음(수동확인): "
                 + "; ".join(f"R{x['row']} {x['과목명']}" for x in g1))
    add("C4","C.편성순서","1학년 선택과목 지양","1학년 공통 위주",
        f"1학년 선택 {len(g1)}건", c4_res, c4_ev)

    종교 = [x for x in rows if '종교' in x['과목명']]
    add("C5","C.편성순서","종교 과목 복수 편성","종교+종교외",
        f"종교 {len(종교)}건","N/A" if not 종교 else "INFO",
        "종교 미편성" if not 종교 else "수동 확인")

    # C6: 체육 총 운영학점 ≥ 10 (2022 개정: 체육 10학점 이상 + 매 학기[C3])
    체육과목 = [x for x in rows if '체육' in x['교과군'].replace(' ', '')]
    체육합 = sum((x['운영학점'] or 0) for x in 체육과목)
    add("C6","C.편성순서","체육 10학점 이상","체육 총 운영학점 ≥ 10",
        f"{체육합:.0f}학점", "PASS" if 체육합 >= 10 else "FAIL",
        ("체육 과목: " + ", ".join(f"{x['과목명']}={x['운영학점']}" for x in 체육과목))
        if 체육과목 else "체육 과목 없음")

    # ====== D. 균형 ======
    tt = summary.get('총학기') or []
    if tt and all(t is not None for t in tt):
        diff = max(tt) - min(tt)
        add("D1","D.균형","학기 간 차이 ≤ 5","최대-최소 ≤ 5",
            f"차이={diff:.0f}", "PASS" if diff <= 5 else "FAIL", f"학기별={tt}")
    else:
        add("D1","D.균형","학기 간 차이 ≤ 5","≤ 5","미산출","INFO","학기별 누락")

    국영수행 = [x for x in rows if x['교과군'].replace(' ','') in ('국어','수학','영어')]
    KSE = sum([(x['운영학점'] or 0) for x in 국영수행])
    # 운영학점 전체 합은 '선택 조건 미반영 상한값'. 국영수에 선택과목이나 비고 '택'
    # 표기가 있으면 81 초과여도 FAIL이 아닌 WARN(선택에 따라 줄 수 있어 수동확인).
    # 국영수에 선택과목(공통이 아닌 유형)이나 비고 '택'이 있으면 운영학점 합은
    # 선택 미반영 상한값 → 81 초과여도 FAIL 아닌 WARN. (과목유형 공백표기에 견고)
    has_choice = any(typ(x) not in ('공통', '') for x in 국영수행) \
        or any('택' in (x['비고'] or '') for x in 국영수행)
    if KSE <= 81:
        d2_res, d2_ev = "PASS", "국+수+영 운영학점 합 (81 이하)"
    elif has_choice:
        d2_res = "WARN"
        d2_ev = (f"운영학점 전체 합 {KSE:.0f} = 선택/택 조건 미반영 상한값. "
                 f"실제 이수는 선택에 따라 ≤{KSE:.0f}일 수 있음 — 비고·특이사항 수동확인 필요")
    else:
        d2_res, d2_ev = "FAIL", f"국+수+영 운영학점 합 {KSE:.0f} (선택조건 없음, 81 초과)"
    add("D2","D.균형","국·수·영 합계 ≤ 81","≤ 81학점", f"{KSE:.0f}", d2_res, d2_ev)

    add("D3","D.균형","교과 174 초과분 50% 룰","초과분의 50% 진로/융합/체예교",
        "수동확인 권장","INFO","비고 분석 필요")

    # ====== E. 표기 ======
    bad = []
    for x in rows:
        nm = x['과목명']
        if nm != nm.strip(): bad.append((x['row'], nm, '앞뒤 공백'))
        elif '  ' in nm: bad.append((x['row'], nm, '연속 공백'))
        elif re.fullmatch(r'.+[I]{1,2}', nm) and 'Ⅰ' not in nm and 'Ⅱ' not in nm:
            bad.append((x['row'], nm, '영문 I/II'))
    head = "; ".join([f"R{a}: {b} ({c})" for a,b,c in bad[:6]])
    add("E1","E.표기","과목명 표기 정합성","공백 없음, Ⅰ/Ⅱ 로마자",
        f"위반 {len(bad)}건","PASS" if not bad else "WARN",
        head + (f" 외 {len(bad)-6}건" if len(bad)>6 else "") if bad else "이상 없음")
    xb = [x for x in rows if x.get('교차이수표기')]
    if xb:
        detail = "; ".join(
            f"R{x['row']} {x['과목명']}(" +
            ", ".join(f"{lab}: {val}" for lab, val in x['교차이수표기']) + ")"
            for x in xb)
        add("E2","E.표기","교차이수 [ ] 표기 점검","[ ] 표기 과목 전수 확인",
            f"교차이수 표기 {len(xb)}건","INFO", detail)
    else:
        add("E2","E.표기","교차이수 [ ] 표기 점검","[ ] 표기 과목 전수 확인",
            "0건","INFO","교차이수([]) 표기 없음")

    # E3: 정규(표준) 과목명 목록(데이터베이스 시트) 대비 비표준 과목 검출.
    # 정규목록에 없는 과목 = 고시외/교육감승인/특목/전문/오타 → 비고가 있어야 함.
    # 비표준인데 비고가 없으면 표기 누락 의심(WARN). x['과목명']·정규과목 모두 _norm_name 적용됨.
    정규 = parsed.get('정규과목') or set()
    if 정규:
        비표준 = [x for x in rows if x['과목명'] not in 정규]
        누락 = [x for x in 비표준 if not (x['비고'] or '').strip()]
        if 누락:
            res, ev = "WARN", ("정규 과목명 아님 + 비고 없음 → 교육감승인/특목/전문/고시외 표기 "
                               "누락 또는 과목명 오타 의심: "
                               + "; ".join(f"R{x['row']} {x['과목명']}" for x in 누락))
        elif 비표준:
            res, ev = "PASS", ("비표준 과목 " + str(len(비표준)) + "개 모두 비고 표기됨: "
                               + "; ".join(f"R{x['row']} {x['과목명']}({x['비고']})" for x in 비표준))
        else:
            res, ev = "PASS", "모든 과목이 정규 과목명 목록에 있음"
        add("E3","E.표기","비표준 과목 비고 표기","고시외/교육감승인/특목 과목은 비고 필요",
            f"비표준 {len(비표준)}건 / 비고누락 {len(누락)}건", res, ev)
    else:
        add("E3","E.표기","비표준 과목 비고 표기","고시외/교육감승인/특목 과목은 비고 필요",
            "정규목록 없음","INFO",
            "데이터베이스(정규 과목목록) 시트가 없어 검증 생략. 원본(.xlsm 또는 전체 .xlsx) 업로드 시 자동 검증됩니다.")

    # ====== F. 수동 확인 권장 ======
    add("F1","F.수동확인","고시 외 과목 학점 범위","고시외는 1~2학점 편성 가능","수동확인 권장","INFO",
        "고시 외 과목은 표준 범위(예: 2~4) 대신 1~2학점 편성도 가능. "
        "B(학점범위)에서 FAIL로 뜬 선택과목 중 고시 외 과목이 있으면 정상일 수 있으니 직접 확인하세요.")
    add("F2","F.수동확인","과목명 최종 확인","정식 명칭·오타 여부","수동확인 권장","INFO",
        "자동 검증(E1)과 별개로, 과목명이 교육과정 정식 명칭과 일치하는지 사람이 한 번 더 확인 권장.")
    add("F3","F.수동확인","고시 외/교육감 승인 과목 유형","과목유형(일반/진로/융합) 분류 적정","수동확인 권장","INFO",
        "고시 외 과목·교육감 승인 과목은 과목유형(일반/진로/융합) 분류를 잘못 지정하기 쉬움. "
        "전체 자동 검증이 어려우니 해당 과목들의 유형이 맞게 선택됐는지 직접 점검하세요.")

    return R
