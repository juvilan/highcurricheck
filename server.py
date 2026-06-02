"""고등학교 교육과정 자동 검토 - Flask 서버 (Streamlit 대체, 경량)"""
import os
import io
import csv
import traceback
from collections import OrderedDict
from urllib.parse import quote

from flask import (
    Flask, request, render_template, redirect, url_for, abort, Response
)

from parser import parse_curriculum
from checker import check_curriculum
import db

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB 업로드 제한
UPLOAD_DIR = "/tmp/curri_uploads"

RESULT_ORDER = ["PASS", "FAIL", "WARN", "INFO", "N/A"]

# 업데이트 내역(최신순). 새 기능/수정 시 맨 위에 추가.
CHANGELOG = [
    {"date": "2026-06-02", "items": [
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


@app.context_processor
def _inject_globals():
    """모든 템플릿에서 최신 업데이트 날짜를 쓸 수 있게 주입."""
    return {"latest_update": CHANGELOG[0]["date"] if CHANGELOG else ""}


def _counts(results):
    return OrderedDict((k, sum(1 for r in results if r["결과"] == k)) for k in RESULT_ORDER)


def _grouped(results):
    """영역별로 묶어 정렬된 리스트 반환: [(영역, [행...]), ...]"""
    by_area = OrderedDict()
    for area in sorted({r["영역"] for r in results}):
        by_area[area] = [r for r in results if r["영역"] == area]
    return list(by_area.items())


def _render_results(school, sheet, results, summary, debug=None, saved_id=None):
    return render_template(
        "results.html",
        history=db.list_checks(limit=200),
        school=school,
        sheet=sheet,
        results=results,
        summary=summary,
        counts=_counts(results),
        fails=[r for r in results if r["결과"] == "FAIL"],
        warns=[r for r in results if r["결과"] == "WARN"],
        grouped=_grouped(results),
        debug=debug,
        saved_id=saved_id,
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
                                   parsed["summary"], results)
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

    # 단일 파일 + 성공 → 기존 상세 페이지(하위호환), 그 외 → 여러 파일 요약 페이지
    if len(items) == 1 and items[0]["ok"]:
        it = items[0]
        return _render_results(it["school"], it["sheet"], it["results"], it["summary"],
                               debug=it["debug"], saved_id=it["id"])
    return render_template("batch.html", history=db.list_checks(limit=200), items=items)


@app.route("/updates")
def updates():
    latest = CHANGELOG[0]["date"] if CHANGELOG else ""
    return render_template("updates.html", history=db.list_checks(limit=200),
                           changelog=CHANGELOG, latest=latest)


@app.route("/history/<rec_id>")
def history_view(rec_id):
    rec = db.get_check(rec_id)
    if not rec:
        abort(404)
    return _render_results(rec["school"], rec["sheet"], rec["results"],
                           rec["summary"], saved_id=rec_id)


@app.route("/delete/<rec_id>", methods=["POST"])
def delete(rec_id):
    db.delete_check(rec_id)
    return redirect(url_for("index"))


@app.route("/export/<rec_id>.csv")
def export_csv(rec_id):
    rec = db.get_check(rec_id)
    if not rec:
        abort(404)
    results = rec["results"]
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
