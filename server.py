"""고등학교 교육과정 자동 검토 - Flask 서버 (Streamlit 대체, 경량)"""
import os
import io
import re
import csv
import uuid
import hmac
import shutil
import traceback
from collections import OrderedDict
from urllib.parse import quote

from flask import (
    Flask, request, render_template, redirect, url_for, abort, Response,
    send_file, session
)
from werkzeug.security import generate_password_hash, check_password_hash

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

# 검토 상세 결과 임시 캐시(즉시 보기/CSV용). DB엔 상세를 저장하지 않으므로
# 방금 검토한 건만 상세 표를 보여주고, 이후엔 원본 파일로 대체.
_RESULT_CACHE = OrderedDict()
_RESULT_CACHE_MAX = 50

RESULT_ORDER = ["PASS", "FAIL", "WARN", "INFO", "N/A"]

# 로그인 없이 접근 가능한 엔드포인트
PUBLIC_ENDPOINTS = {"login", "logout", "static"}
MASTER_USERNAME = "master"


def _load_password():
    """마스터 비밀번호: 환경변수 CURRI_PASSWORD 우선, 없으면 .auth_password 파일."""
    pw = os.environ.get("CURRI_PASSWORD")
    if pw and pw.strip():
        return pw.strip()
    path = os.path.join(BASE_DIR, ".auth_password")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            val = fh.read().strip()
            return val or None
    return None


MASTER_PASSWORD = _load_password()


def _load_secret():
    """세션 서명 키: .flask_secret 파일에 영구 보관(없으면 생성)."""
    path = os.path.join(BASE_DIR, ".flask_secret")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            data = fh.read().strip()
            if data:
                return data
    secret = os.urandom(32).hex().encode()
    with open(path, "wb") as fh:
        fh.write(secret)
    os.chmod(path, 0o600)
    return secret


app.secret_key = _load_secret()

# 업데이트 내역(최신순). 새 기능/수정 시 맨 위에 추가.
CHANGELOG = [
    {"date": "2026-06-04", "items": [
        "검토 이력 학교명 표시 개선 — 파일명에서 학교 약칭과 학년도를 뽑아 ‘광영여고 2026’처럼 표시(이전엔 ‘서울특별시교육청’으로 나오던 문제)",
        "로그인 기능 도입 — 아이디·비밀번호로 로그인. 새 아이디는 가입 신청 후 마스터 승인을 받아야 사용 가능. 자기가 올려 검토한 자료만 열람·삭제, 마스터는 전체 열람·삭제와 가입 승인 관리.",
        "이력 상세에 ‘다시 검토’ 버튼 — 보관된 원본으로 즉석 재검토해 과거 검토의 상세 결과를 다시 볼 수 있음",
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


def current_user():
    return session.get("user")


def is_master():
    return session.get("user") == MASTER_USERNAME


def _can_access(rec):
    """마스터는 전체, 일반 사용자는 본인 검토만."""
    return is_master() or (rec.get("owner") == current_user())


@app.before_request
def _require_login():
    """로그인 필수. 로그인/정적 외 모든 경로는 로그인해야 접근."""
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not current_user():
        return redirect(url_for("login", next=request.path))
    return None


def _cache_results(rec_id, results):
    _RESULT_CACHE[rec_id] = results
    while len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
        _RESULT_CACHE.popitem(last=False)


@app.context_processor
def _inject_globals():
    """모든 템플릿에서 최신 업데이트 날짜·로그인 정보를 쓸 수 있게 주입."""
    pending = 0
    if is_master():
        pending = sum(1 for u in db.list_users() if not u["approved"])
    return {
        "latest_update": CHANGELOG[0]["date"] if CHANGELOG else "",
        "user": current_user(),
        "is_master": is_master(),
        "pending_count": pending,
    }


# 파일명에서 학교 표시명을 뽑을 때 "설명" 구간으로 보고 제외할 키워드
_DESC_KEYWORDS = ("학점", "배당", "교육과정", "입학생", "학년도", "편제", "개정", "배당표", "점검")


def _display_school(filename):
    """파일명에서 '약칭학교명 + 학년도'를 추출. 예) 서울특별시교육청_광영여자고등학교_
    2026학년도 ... _광영여고.xlsx → '광영여고 2026'."""
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    m = re.search(r"(20\d{2})\s*학년도", stem) or re.search(r"(20\d{2})", stem)
    year = m.group(1) if m else ""
    parts = [p.strip() for p in stem.split("_") if p.strip()]
    parts = [p for p in parts if "교육청" not in p]  # 행정기관 구간 제외
    # 학교명처럼 보이는(고/중/초/학교 포함) + 설명 아닌 구간 중 약칭(짧은 쪽) 우선
    names = [p for p in parts
             if any(k in p for k in ("고", "중", "초", "학교"))
             and not any(k in p for k in _DESC_KEYWORDS)]
    if names:
        school = min(names, key=len)
    elif parts:
        school = min(parts, key=len)
    else:
        school = stem or "업로드 파일"
    return (school + (" " + year if year else "")).strip()


def _counts(results):
    return OrderedDict((k, sum(1 for r in results if r["결과"] == k)) for k in RESULT_ORDER)


def _grouped(results):
    """영역별로 묶어 정렬된 리스트 반환: [(영역, [행...]), ...]"""
    by_area = OrderedDict()
    for area in sorted({r["영역"] for r in results}):
        by_area[area] = [r for r in results if r["영역"] == area]
    return list(by_area.items())


def _sidebar_history():
    """사이드바/목록용 이력 — 마스터는 전체, 일반 사용자는 본인 것만."""
    return db.list_checks(limit=500, owner=None if is_master() else current_user())


def _render_results(school, sheet, results, summary, debug=None, saved_id=None,
                    counts=None, origname=None):
    return render_template(
        "results.html",
        history=_sidebar_history(),
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


@app.route("/login", methods=["GET", "POST"])
def login():
    """로그인 + 자유 가입(처음 보는 아이디면 그 비번으로 가입)."""
    if current_user():
        return redirect(url_for("index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        nxt = request.form.get("next") or url_for("index")
        err = None
        if not username or not password:
            err = "아이디와 비밀번호를 입력하세요."
        elif username == MASTER_USERNAME:
            if MASTER_PASSWORD and hmac.compare_digest(password, MASTER_PASSWORD):
                session["user"] = MASTER_USERNAME
                return redirect(nxt)
            err = "마스터 비밀번호가 올바르지 않습니다."
        else:
            u = db.get_user(username)
            if u is None:  # 처음 보는 아이디 → 가입 신청(승인 대기)
                db.create_user(username, generate_password_hash(password), approved=0)
                return render_template(
                    "login.html", next=nxt,
                    info="가입 신청이 접수되었습니다. 마스터 승인 후 로그인할 수 있습니다.")
            elif not check_password_hash(u["pwhash"], password):
                err = "비밀번호가 올바르지 않습니다."
            elif not u["approved"]:
                err = "아직 승인 대기 중입니다. 마스터 승인을 기다려 주세요."
            else:
                session["user"] = username
                return redirect(nxt)
        return render_template("login.html", error=err, username=username, next=nxt)
    return render_template("login.html", next=request.args.get("next", ""))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _require_master():
    if not is_master():
        abort(403)


@app.route("/admin/users")
def admin_users():
    """가입 승인 관리(마스터 전용)."""
    _require_master()
    return render_template("admin_users.html", users=db.list_users())


@app.route("/admin/approve/<username>", methods=["POST"])
def admin_approve(username):
    _require_master()
    if username != MASTER_USERNAME:
        db.approve_user(username)
    return redirect(url_for("admin_users"))


@app.route("/admin/reject/<username>", methods=["POST"])
def admin_reject(username):
    """가입 거부/사용자 삭제(마스터 전용). 해당 사용자의 검토 기록은 남음."""
    _require_master()
    if username != MASTER_USERNAME:
        db.delete_user(username)
    return redirect(url_for("admin_users"))


@app.route("/")
def index():
    return render_template("index.html", history=_sidebar_history())


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
        return render_template("index.html", history=_sidebar_history(),
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
            school = _display_school(f.filename)  # 파일명 기반 표시명(약칭+학년도)
            rec_id = db.save_check(school, parsed["sheet"], counts,
                                   parsed["summary"], f.filename, owner=current_user())
            # 원본 엑셀을 영구 보관(상세 결과 대신)
            shutil.copyfile(tmp_path, os.path.join(ORIG_DIR, rec_id + ".xlsx"))
            _cache_results(rec_id, results)
            items.append({
                "ok": True, "filename": f.filename, "school": school,
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

    # PRG: 단일 성공은 본인 이력 상세로, 여러 개면 요약(토큰) 페이지로 리다이렉트.
    if len(items) == 1 and items[0].get("ok"):
        return redirect(url_for("history_view", rec_id=items[0]["id"]))
    token = uuid.uuid4().hex
    _RESULT_TOKENS[token] = items
    while len(_RESULT_TOKENS) > _RESULT_TOKENS_MAX:
        _RESULT_TOKENS.popitem(last=False)
    return redirect(url_for("result_view", token=token))


@app.route("/result/<token>")
def result_view(token):
    """방금 일괄 검토한 결과 요약(로그인 사용자). 상세는 각자 이력으로 연결."""
    items = _RESULT_TOKENS.get(token)
    if items is None:  # 재시작 등으로 만료된 토큰
        return redirect(url_for("index"))
    return render_template("batch.html", items=items, history=_sidebar_history())


@app.route("/updates")
def updates():
    latest = CHANGELOG[0]["date"] if CHANGELOG else ""
    return render_template("updates.html", history=_sidebar_history(),
                           changelog=CHANGELOG, latest=latest)


@app.route("/history")
def history_list():
    """검토 이력 목록 — 마스터는 전체, 일반 사용자는 본인 것만."""
    return render_template("history.html", history=_sidebar_history())


@app.route("/history/<rec_id>")
def history_view(rec_id):
    rec = db.get_check(rec_id)
    if not rec:
        abort(404)
    if not _can_access(rec):
        abort(403)
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
    if not _can_access(rec):
        abort(403)
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
    if not _can_access(rec):
        abort(403)
    path = os.path.join(ORIG_DIR, rec_id + ".xlsx")
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=rec["origname"])


@app.route("/delete/<rec_id>", methods=["POST"])
def delete(rec_id):
    rec = db.get_check(rec_id)
    if rec and not _can_access(rec):
        abort(403)
    db.delete_check(rec_id)
    _RESULT_CACHE.pop(rec_id, None)
    try:
        os.unlink(os.path.join(ORIG_DIR, rec_id + ".xlsx"))
    except OSError:
        pass
    return redirect(url_for("history_list"))


@app.route("/export/<rec_id>.csv")
def export_csv(rec_id):
    rec = db.get_check(rec_id)
    if not rec:
        abort(404)
    if not _can_access(rec):
        abort(403)
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
