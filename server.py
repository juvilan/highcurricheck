"""고등학교 교육과정 자동 검토 - Flask 서버 (Streamlit 대체, 경량)"""
import os
import io
import csv
import uuid
import hmac
import shutil
import traceback
from collections import OrderedDict
from urllib.parse import quote

from flask import (
    Flask, request, render_template, redirect, url_for, abort, Response,
    send_file
)

from parser import parse_curriculum
from checker import check_curriculum
import db

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB 업로드 제한
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = "/tmp/curri_uploads"        # 파싱용 임시 저장(처리 후 삭제)
ORIG_DIR = os.path.join(BASE_DIR, "uploads")  # 원본 엑셀 영구 보관(<rec_id>.xlsx)

# 방금 검토한 결과(공개)를 토큰으로 잠깐 보관(PRG용). 토큰을 가진(=방금 업로드한)
# 사람만 접근. 뒤로가기/새로고침 시 양식 재제출 방지. 재시작 시 비워지고 최근 N개만 유지.
_RESULT_TOKENS = OrderedDict()
_RESULT_TOKENS_MAX = 50

# 비번이 필요한 경로(저장된 이력·원본 열람/관리). 그 외(검증 등)는 공개.
PROTECTED_PREFIXES = ("/history", "/original", "/export", "/delete", "/recheck")

# 검토 상세 결과 임시 캐시(즉시 보기/CSV용). DB엔 상세를 저장하지 않으므로
# 방금 검토한 건만 상세 표를 보여주고, 이후엔 원본 파일로 대체.
_RESULT_CACHE = OrderedDict()
_RESULT_CACHE_MAX = 50

RESULT_ORDER = ["PASS", "FAIL", "WARN", "INFO", "N/A"]


def _load_password():
    """접근 비밀번호: 환경변수 CURRI_PASSWORD 우선, 없으면 .auth_password 파일."""
    pw = os.environ.get("CURRI_PASSWORD")
    if pw and pw.strip():
        return pw.strip()
    path = os.path.join(BASE_DIR, ".auth_password")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            val = fh.read().strip()
            return val or None
    return None


AUTH_PASSWORD = _load_password()

# 업데이트 내역(최신순). 새 기능/수정 시 맨 위에 추가.
CHANGELOG = [
    {"date": "2026-06-04", "items": [
        "이력 상세에 ‘다시 검토’ 버튼 — 보관된 원본으로 즉석 재검토해 과거 검토의 상세 결과를 다시 볼 수 있음(비번 필요)",
        "접근 권한 분리 — 검토(업로드·결과 보기)는 비번 없이 누구나, 저장된 이력 목록·과거 기록 열람·원본 다운로드는 비번 필요",
        "비밀번호 접근 제한 추가 — 공용 비밀번호 인증",
        "검토 이력에 업로드한 원본 엑셀 파일을 보관(다시 내려받기 가능), 상세 결과 데이터는 더 이상 저장하지 않음",
    ]},
    {"date": "2026-06-02", "items": [
        "상세 보기 후 뒤로가기 정상화 — 결과 화면에 '← 뒤로' 버튼 추가, 일괄검토 결과를 GET 페이지로 전환해 뒤로가기/새로고침 시 재검토되던 문제 해결",
        "CSV 내보내기 한글 파일명 오류 수정 — 학교명이 한글인 검토결과 CSV가 받아지지 않던 문제 해결",
        "여러 파일 한꺼번에 업로드(일괄 검토 요약) 지원",
        "[신규] E3 — 비표준 과목(고시외/교육감승인/특목) 비고 표기 검증: 데이터베이스 시트의 정규 과목명 목록과 대조해, 목록에 없는 과목인데 비고가 없으면 경고",
        "[신규] B6 — 운영학점 = 학기 배치 합 검사(선택그룹·교차이수 제외)",
        "[신규] E2 — 교차이수 [ ] 표기 전수 점검(행·칸·원본값 명시)",
        "국·수·영 81학점(D2): 선택조건 있으면 FAIL 대신 WARN(상한값·수동확인)",
        "고시 외 과목 저학점(1~2): B2/B3/B4에서 FAIL 대신 WARN(수동확인)",
        "공통→선택 순서(C1): 교과군별 비교로 수정(오탐 제거)",
        "1학년 선택과목 지양(C4): 체예교·교차이수 과목은 정상일 수 있어 FAIL 대신 WARN(수동확인)",
        "과목유형 약어(일반/진로/융합) 인식 수정 — 이전엔 일부 검사가 헛돌았음",
        "과목명 로마숫자 Ⅰ/Ⅱ 오인식(영문 I로 잘못 경고) 수정",
        "[신규] F3 — 고시외/교육감 승인 과목의 과목유형 수동점검 안내",
        "엔진 경량화: Streamlit → Flask 전환",
    ]},
]

db.init_db()


def _is_authed():
    """비번 일치 여부. 비번 미설정이면 항상 통과."""
    if AUTH_PASSWORD is None:
        return True
    a = request.authorization
    return bool(a and hmac.compare_digest((a.password or ""), AUTH_PASSWORD))


@app.before_request
def _require_auth():
    """보호 경로(이력·원본)만 Basic Auth. 검증 등 그 외 경로는 공개."""
    if AUTH_PASSWORD is None:
        return None
    if not any(request.path.startswith(p) for p in PROTECTED_PREFIXES):
        return None
    if _is_authed():
        return None
    resp = Response("인증이 필요합니다.", 401)
    resp.headers["WWW-Authenticate"] = 'Basic realm="curri-check", charset="UTF-8"'
    return resp


def _cache_results(rec_id, results):
    _RESULT_CACHE[rec_id] = results
    while len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
        _RESULT_CACHE.popitem(last=False)


@app.context_processor
def _inject_globals():
    """모든 템플릿에서 최신 업데이트 날짜·인증여부를 쓸 수 있게 주입."""
    return {
        "latest_update": CHANGELOG[0]["date"] if CHANGELOG else "",
        "authed": _is_authed(),
    }


def _counts(results):
    return OrderedDict((k, sum(1 for r in results if r["결과"] == k)) for k in RESULT_ORDER)


def _grouped(results):
    """영역별로 묶어 정렬된 리스트 반환: [(영역, [행...]), ...]"""
    by_area = OrderedDict()
    for area in sorted({r["영역"] for r in results}):
        by_area[area] = [r for r in results if r["영역"] == area]
    return list(by_area.items())


def _render_results(school, sheet, results, summary, debug=None, saved_id=None,
                    counts=None, origname=None):
    return render_template(
        "results.html",
        history=db.list_checks(limit=200),
        school=school,
        sheet=sheet,
        results=results,
        summary=summary,
        counts=counts if counts is not None else _counts(results),
        fails=[r for r in results if r["결과"] == "FAIL"],
        warns=[r for r in results if r["결과"] == "WARN"],
        grouped=_grouped(results),
        debug=debug,
        saved_id=saved_id,
        origname=origname,
    )


@app.route("/")
def index():
    return render_template("index.html", history=db.list_checks(limit=200))


@app.route("/check", methods=["POST"])
def check():
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:  # 하위호환: 옛 단일 input(name="file")
        f = request.files.get("file")
        if f and f.filename:
            files = [f]
    if not files:
        return redirect(url_for("index"))

    bad = [f.filename for f in files if not f.filename.lower().endswith(".xlsx")]
    if bad:
        return render_template("index.html", history=db.list_checks(limit=200),
                               error="`.xlsx` 파일만 업로드할 수 있습니다: " + ", ".join(bad))

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(ORIG_DIR, exist_ok=True)
    items = []
    for f in files:
        safe_name = f.filename.replace("/", "_").replace("\\", "_")
        tmp_path = os.path.join(UPLOAD_DIR, safe_name)
        f.save(tmp_path)
        try:
            parsed = parse_curriculum(tmp_path)
            results = check_curriculum(parsed)
            counts = _counts(results)
            rec_id = db.save_check(parsed["school"], parsed["sheet"], counts,
                                   parsed["summary"], f.filename)
            # 원본 엑셀을 영구 보관(상세 결과 대신)
            shutil.copyfile(tmp_path, os.path.join(ORIG_DIR, rec_id + ".xlsx"))
            _cache_results(rec_id, results)
            items.append({
                "ok": True, "filename": f.filename, "school": parsed["school"],
                "sheet": parsed["sheet"], "counts": counts, "id": rec_id,
                "results": results, "summary": parsed["summary"],
                "debug": {"header_row": parsed["header_row"],
                          "data_start": parsed["data_start"],
                          "summary_start": parsed["summary_start"]},
                "fails": [r for r in results if r["결과"] == "FAIL"],
                "warns": [r for r in results if r["결과"] == "WARN"],
            })
        except Exception as e:
            sheets = None
            try:
                import openpyxl
                wb = openpyxl.load_workbook(tmp_path, data_only=True, read_only=True)
                sheets = wb.sheetnames
            except Exception:
                pass
            items.append({"ok": False, "filename": f.filename, "error": str(e), "sheets": sheets})
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # PRG: POST 결과를 직접 렌더링하지 않고 공개 결과 페이지(토큰)로 리다이렉트.
    # 토큰을 가진 사람(=방금 업로드한 본인)만 결과를 보며, 비번 없이 열람 가능.
    token = uuid.uuid4().hex
    _RESULT_TOKENS[token] = items
    while len(_RESULT_TOKENS) > _RESULT_TOKENS_MAX:
        _RESULT_TOKENS.popitem(last=False)
    return redirect(url_for("result_view", token=token))


@app.route("/result/<token>")
def result_view(token):
    """방금 검토한 결과(공개). 단일이면 상세, 여러 개면 요약 카드."""
    items = _RESULT_TOKENS.get(token)
    if items is None:  # 재시작 등으로 만료된 토큰
        return redirect(url_for("index"))
    if len(items) == 1 and items[0].get("ok"):
        it = items[0]
        return _render_results(it["school"], it["sheet"], it["results"],
                               it["summary"], debug=it.get("debug"))
    return render_template("batch.html", items=items, token=token)


@app.route("/result/<token>/<int:idx>")
def result_detail(token, idx):
    """일괄 결과에서 개별 파일 상세(공개)."""
    items = _RESULT_TOKENS.get(token)
    if items is None or idx < 0 or idx >= len(items) or not items[idx].get("ok"):
        return redirect(url_for("index"))
    it = items[idx]
    return _render_results(it["school"], it["sheet"], it["results"],
                           it["summary"], debug=it.get("debug"))


@app.route("/updates")
def updates():
    latest = CHANGELOG[0]["date"] if CHANGELOG else ""
    return render_template("updates.html", history=db.list_checks(limit=200),
                           changelog=CHANGELOG, latest=latest)


@app.route("/history")
def history_list():
    """저장된 검토 이력 목록(비번 보호)."""
    return render_template("history.html", history=db.list_checks(limit=500))


@app.route("/history/<rec_id>")
def history_view(rec_id):
    rec = db.get_check(rec_id)
    if not rec:
        abort(404)
    # 상세 결과는 보관하지 않으므로, 방금 검토한 건(캐시)만 상세 표를 보여주고
    # 그 외에는 DB의 카운트만 표시 + 원본 다운로드로 안내.
    results = _RESULT_CACHE.get(rec_id, [])
    counts = None if results else OrderedDict(
        (k, rec[c]) for k, c in
        [("PASS", "pass"), ("FAIL", "fail"), ("WARN", "warn"),
         ("INFO", "info"), ("N/A", "na")]
    )
    return _render_results(rec["school"], rec["sheet"], results,
                           rec["summary"], saved_id=rec_id, counts=counts,
                           origname=rec.get("origname"))


@app.route("/recheck/<rec_id>", methods=["POST"])
def recheck(rec_id):
    """보관된 원본으로 다시 검토 → 상세 결과를 캐시에 채우고 상세 화면으로."""
    rec = db.get_check(rec_id)
    if not rec:
        abort(404)
    path = os.path.join(ORIG_DIR, rec_id + ".xlsx")
    if not os.path.exists(path):
        abort(404)
    try:
        parsed = parse_curriculum(path)
        _cache_results(rec_id, check_curriculum(parsed))
    except Exception:
        return redirect(url_for("history_view", rec_id=rec_id, recheck_error=1))
    return redirect(url_for("history_view", rec_id=rec_id))


@app.route("/original/<rec_id>.xlsx")
def download_original(rec_id):
    rec = db.get_check(rec_id)
    if not rec or not rec.get("origname"):
        abort(404)
    path = os.path.join(ORIG_DIR, rec_id + ".xlsx")
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=rec["origname"])


@app.route("/delete/<rec_id>", methods=["POST"])
def delete(rec_id):
    db.delete_check(rec_id)
    _RESULT_CACHE.pop(rec_id, None)
    try:
        os.unlink(os.path.join(ORIG_DIR, rec_id + ".xlsx"))
    except OSError:
        pass
    return redirect(url_for("index"))


@app.route("/export/<rec_id>.csv")
def export_csv(rec_id):
    rec = db.get_check(rec_id)
    if not rec:
        abort(404)
    results = _RESULT_CACHE.get(rec_id) or rec["results"]
    if not results:  # 상세 미보관 → 원본 파일로 대체
        return redirect(url_for("download_original", rec_id=rec_id))
    cols = ["id", "영역", "항목", "기준", "측정값", "결과", "근거"]
    buf = io.StringIO()
    buf.write("﻿")  # Excel 한글용 BOM
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(results)
    fname = f"{rec['school']}_검토결과.csv"
    fname_q = quote(fname)  # RFC 5987: 헤더에 들어가는 값은 퍼센트 인코딩 필요
    return Response(
        buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=download.csv; filename*=UTF-8''{fname_q}"
            )
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 4001))
    from waitress import serve
    print(f"highcurricheck (Flask/waitress) listening on 0.0.0.0:{port}")
    serve(app, host="0.0.0.0", port=port, threads=8)
