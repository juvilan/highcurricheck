"""parser/checker 회귀 테스트.

표본 학점배당표(test/fixtures/sample_curriculum.xlsx)를 기준으로,
과거에 결과가 틀렸던 두 버그가 재발하지 않는지 고정한다.

  - 과목유형 어휘 불일치: 파일은 '일반/진로/융합' 표기인데 checker는
    '일반선택/진로선택/융합선택'을 기대 → 선택과목 검사가 통째로 누락됐다.
  - data_start 고정 오프셋(header+4): 헤더가 3행인 파일에서 첫 과목(공통국어1)이
    누락돼 과목수가 1개 모자랐다.
"""
import os
from collections import Counter

import pytest

from parser import parse_curriculum
from checker import check_curriculum

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_curriculum.xlsx")


@pytest.fixture(scope="module")
def parsed():
    return parse_curriculum(FIXTURE)


def test_parse_does_not_drop_first_subject(parsed):
    """data_start 스캔으로 첫 과목(공통국어1)이 누락되지 않는다 (과목수 95)."""
    names = [r["과목명"] for r in parsed["rows"]]
    assert "공통국어1" in names
    assert len(parsed["rows"]) == 95


def test_subject_types_are_normalized(parsed):
    """과목유형이 자율점검표 표준어로 정규화된다 (raw '일반/진로/융합' 잔존 금지)."""
    counts = Counter(r["과목유형"] for r in parsed["rows"])
    assert counts == {"공통": 14, "일반선택": 26, "융합선택": 18, "진로선택": 37}
    assert not any(r["과목유형"] in ("일반", "진로", "융합") for r in parsed["rows"])


def test_checker_actually_evaluates_electives(parsed):
    """선택과목이 실제로 검사된다.

    수정 전에는 과목유형 불일치로 1학년 선택과목이 0건 매칭되어 C4가 거짓 PASS였다.
    수정 후에는 6건(체육1·체육2·음악·미술·정보·로봇과 공학세계)을 탐지한다.
    C4는 '지양' 권고이므로 발견 시 FAIL이 아니라 WARN으로 표시한다.
    """
    results = check_curriculum(parsed)
    # 규칙 개수는 늘어난다(작성 당시 19개 → 이후 29개). 개수로 고정하면 규칙을
    # 추가할 때마다 무관한 테스트가 깨지므로, 이 테스트가 보려는 규칙만 확인한다.
    ids = {r["id"] for r in results}
    assert {"A3", "C1", "C4", "D2"} <= ids
    c4 = next(r for r in results if r["id"] == "C4")
    assert c4["결과"] == "WARN"
    assert "6건" in c4["측정값"]


def test_d2_current_behavior_is_국수영_vs_81(parsed):
    """현재 D2는 국·수·영 합만 고정 상한 81과 비교한다 — 지금 동작을 고정해 둔다.

    81은 174×50% − 한국사 6을 미리 빼 둔 값이다. 즉 교과총 174, 한국사 6이라는
    두 가정이 박혀 있다.
    """
    d2 = next(r for r in check_curriculum(parsed) if r["id"] == "D2")
    assert d2["측정값"] == "105"          # 국·수·영만
    assert "81" in d2["기준"]


@pytest.mark.xfail(reason="D2가 한국사를 합산하지 않고 상한을 교과총의 50%로 계산하지 않는다 "
                          "— 교육과정 규정 해석이 필요한 미해결 항목", strict=True)
def test_d2_should_use_기초교과_50_percent_rule(parsed):
    """규정대로라면 기초교과(국·수·영·한국사) ≤ 교과 총 이수학점의 50%여야 한다.

    표본: 국·수·영 105 + 한국사 6 = 111 > 87(174의 50%) → FAIL.
    현재 구현은 한국사를 빼고 105 ≤ 81 만 보므로 이 기대를 만족하지 못한다.
    fix/parser-robustness 브랜치에는 이 방식으로 계산하는 구현이 있었다.
    """
    d2 = next(r for r in check_curriculum(parsed) if r["id"] == "D2")
    assert "한국사" in d2["항목"]
    assert d2["측정값"] == "111"
    assert "87" in d2["기준"]


def test_a3_auto_detects_required_credits(parsed):
    """A3는 소계행의 필수 이수 학점 열을 헤더 기반으로 탐지해 자동 판정한다.

    예전에는 INFO(수동확인)였다. 표본은 필수이수 84 → PASS.
    """
    assert parsed["summary"].get("필수이수") == 84
    a3 = next(r for r in check_curriculum(parsed) if r["id"] == "A3")
    assert a3["측정값"] == "84"
    assert a3["결과"] == "PASS"


def test_c1_checks_order_per_subject_area(parsed):
    """C1은 교과군별로 공통→선택 순서를 본다.

    배당표는 교과군별로 정렬되어 공통·선택이 번갈아 나오므로, 전체 행 비교는
    원칙을 지킨 표도 거짓 FAIL을 냈다. 표본은 모든 교과군에서 공통이 선택보다
    먼저라 PASS여야 한다.
    """
    c1 = next(r for r in check_curriculum(parsed) if r["id"] == "C1")
    assert "교과군" in c1["항목"]
    assert c1["결과"] == "PASS"
