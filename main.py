import os
import re
import json
import time
import base64
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from PIL import Image

# Optional parsers
try:
    import docx  # python-docx
except Exception:
    docx = None

try:
    import PyPDF2
except Exception:
    PyPDF2 = None

# OpenAI
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================
# App Config
# =========================
APP_TITLE = "CodeClass Hub"
DB_PATH = "codeclass_hub.sqlite3"
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

st.set_page_config(page_title=APP_TITLE, layout="wide")


# =========================
# CSS (대시보드 스타일)
# =========================
st.markdown(
    """
<style>
.main { background-color: #f4f6f8; }
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }

/* top navbar */
.navbar {
  background: #2f3337;
  color: #fff;
  border-radius: 10px;
  padding: 0.9rem 1.1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.1rem;
}
.nav-left { display: flex; flex-direction: column; gap: 0.2rem; }
.nav-title { font-weight: 800; font-size: 1.15rem; line-height: 1.1; }
.nav-sub { opacity: 0.9; font-size: 0.9rem; }

.pills { display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: flex-end; }
.pill {
  padding: 0.35rem 0.6rem;
  border-radius: 8px;
  font-weight: 700;
  font-size: 0.85rem;
  color: #fff;
  display: inline-block;
}
.pill-blue { background: #2d79ff; }
.pill-gray { background: #6c757d; }
.pill-orange { background: #ff9f2d; }
.pill-red { background: #ff4d4f; }
.pill-green { background: #2bb673; }

/* cards */
.card {
  background: #fff;
  border: 1px solid #e6e8eb;
  border-radius: 12px;
  padding: 1rem 1.1rem;
  box-shadow: 0 1px 0 rgba(0,0,0,0.02);
}
.section-title {
  font-size: 1.05rem;
  font-weight: 900;
  margin: 0.2rem 0 0.6rem 0;
}
.tag {
  display: inline-block;
  padding: 0.2rem 0.45rem;
  border-radius: 999px;
  background: #eef2ff;
  border: 1px solid #dfe6ff;
  color: #2d4bd3;
  font-size: 0.75rem;
  font-weight: 700;
  margin-right: 0.3rem;
}
.small { font-size: 0.85rem; color: #4b5563; }
hr.soft { border: none; border-top: 1px solid #eef0f2; margin: 0.8rem 0; }
</style>
""",
    unsafe_allow_html=True,
)


# =========================
# DB Utils
# =========================
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            unit TEXT NOT NULL,
            lesson TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS live_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            title TEXT NOT NULL,
            tags TEXT NOT NULL,
            status TEXT NOT NULL,         -- 완료/도움요청/공유
            code_text TEXT,
            screenshot_path TEXT,
            description TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS debug_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            mode TEXT NOT NULL,           -- text/image
            code_text TEXT,
            error_text TEXT,
            image_path TEXT,
            environment TEXT,
            ai_result TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            due_date TEXT,
            rubric_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            user_name TEXT NOT NULL,
            report_path TEXT,
            code_path TEXT,
            images_json TEXT,
            note TEXT,
            status TEXT NOT NULL,          -- 제출/분석중/완료
            ai_json TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()


def seed_demo_data() -> None:
    conn = db()
    cur = conn.cursor()

    # Courses
    cur.execute("SELECT COUNT(*) as c FROM courses;")
    if cur.fetchone()["c"] == 0:
        cur.execute(
            "INSERT INTO courses(name, unit, lesson) VALUES(?,?,?)",
            ("6-1 정보", "반복문", "누적합 실습"),
        )
        cur.execute(
            "INSERT INTO courses(name, unit, lesson) VALUES(?,?,?)",
            ("6-2 정보", "조건문", "분기 실습"),
        )

    # Users
    cur.execute("SELECT COUNT(*) as c FROM users;")
    if cur.fetchone()["c"] == 0:
        for s in ["홍길동", "김철수", "이영희"]:
            cur.execute("INSERT INTO users(name, role) VALUES(?,?)", (s, "student"))
        cur.execute("INSERT INTO users(name, role) VALUES(?,?)", ("교사", "teacher"))

    # Assignment
    cur.execute("SELECT COUNT(*) as c FROM assignments;")
    if cur.fetchone()["c"] == 0:
        rubric = default_rubric_A01()
        cur.execute(
            """
            INSERT INTO assignments(course_id, title, due_date, rubric_json, created_at)
            VALUES(?,?,?,?,?)
            """,
            (1, "A01 반복문 누적합(1~10)", "2026-02-01", json.dumps(rubric, ensure_ascii=False), now()),
        )

    conn.commit()
    conn.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================
# Rubric (정보 과목용)
# =========================
def default_rubric_A01() -> Dict[str, Any]:
    return {
        "assignment": "A01 반복문 누적합(1~10)",
        "max_total": 100,
        "items": [
            {"id": "R1", "name": "문제 접근 설명", "max": 10, "hint": "보고서/설명에 접근 방법을 2~3줄로 설명"},
            {"id": "R2", "name": "반복문 범위 정확", "max": 15, "hint": "range(1, 11) 등 범위가 1~10인지"},
            {"id": "R3", "name": "누적 로직", "max": 20, "hint": "total 초기화 및 total += i 패턴"},
            {"id": "R4", "name": "출력 증거", "max": 20, "hint": "결과 캡처에 출력값(55)과 실행 맥락이 보이는지"},
            {"id": "R5", "name": "코드 가독성", "max": 15, "hint": "변수명/주석/구조(불필요한 중복 최소)"},
            {"id": "R6", "name": "테스트/검증", "max": 10, "hint": "예상/실제 결과를 간단히라도 점검"},
            {"id": "R7", "name": "회고/개선점", "max": 10, "hint": "어려웠던 점/개선점을 1가지 이상"},
        ],
        "policy": {
            "no_code_execution": True,
            "evidence_based": True,
            "no_full_solution": True,
        },
    }


# =========================
# File Utils
# =========================
def save_upload(file, subdir: str) -> Optional[str]:
    if file is None:
        return None
    safe_dir = UPLOAD_DIR / subdir
    safe_dir.mkdir(parents=True, exist_ok=True)

    # make safe filename
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", file.name)
    path = safe_dir / f"{int(time.time())}_{name}"
    with open(path, "wb") as f:
        f.write(file.getbuffer())
    return str(path)


def read_text_from_doc(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""

    suffix = p.suffix.lower()
    if suffix == ".docx" and docx is not None:
        d = docx.Document(path)
        return "\n".join([para.text for para in d.paragraphs]).strip()

    if suffix == ".pdf" and PyPDF2 is not None:
        text = []
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages[:10]:  # limit pages for safety
                try:
                    text.append(page.extract_text() or "")
                except Exception:
                    continue
        return "\n".join(text).strip()

    return ""


def image_to_data_url(path: str) -> Optional[str]:
    try:
        p = Path(path)
        if not p.exists():
            return None
        mime = "image/png"
        if p.suffix.lower() in [".jpg", ".jpeg"]:
            mime = "image/jpeg"

        b = p.read_bytes()
        b64 = base64.b64encode(b).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


# =========================
# OpenAI Utils (Responses API)
# =========================
def get_openai_client() -> Optional[Any]:
    if OpenAI is None:
        return None
    key = None
    try:
        key = st.secrets.get("OPENAI_API_KEY")
    except Exception:
        key = None
    key = key or os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    return OpenAI(api_key=key)


def get_model_name() -> str:
    # user can override in secrets/env
    model = None
    try:
        model = st.secrets.get("OPENAI_MODEL")
    except Exception:
        model = None
    model = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    return model


def call_ai_json(
    instructions: str,
    user_text: str,
    image_paths: Optional[List[str]] = None,
    temperature: float = 0.2,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Returns: (json_obj, raw_text_if_failed)
    """
    client = get_openai_client()
    if client is None:
        return None, "OPENAI_API_KEY가 설정되지 않았거나 openai 패키지가 없습니다."

    model = get_model_name()

    # Build multimodal input for Responses API
    content = [{"type": "input_text", "text": user_text}]
    if image_paths:
        for ip in image_paths[:3]:
            url = image_to_data_url(ip)
            if url:
                content.append({"type": "input_image", "image_url": url})

    try:
        resp = client.responses.create(
            model=model,
            instructions=instructions,
            input=[{"role": "user", "content": content}],
            # (옵션) reasoning effort를 낮춰 비용/지연을 줄일 수 있음
            # reasoning={"effort": "low"},
        )
        text = getattr(resp, "output_text", None) or ""
    except Exception as e:
        return None, f"OpenAI 호출 실패: {e}"

    # Try parse JSON
    text_stripped = text.strip()
    # If model returns fenced code block
    if text_stripped.startswith("```"):
        text_stripped = re.sub(r"^```[a-zA-Z]*\n", "", text_stripped)
        text_stripped = re.sub(r"\n```$", "", text_stripped).strip()

    try:
        data = json.loads(text_stripped)
        return data, None
    except Exception:
        return None, text  # return raw


# =========================
# UI Helpers
# =========================
def top_navbar(title: str, subtitle: str, pills: List[Tuple[str, str]]) -> None:
    pill_html = "\n".join([f'<span class="pill {cls}">{txt}</span>' for txt, cls in pills])
    st.markdown(
        f"""
<div class="navbar">
  <div class="nav-left">
    <div class="nav-title">{title}</div>
    <div class="nav-sub">{subtitle}</div>
  </div>
  <div class="pills">
    {pill_html}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def card_open(title: str) -> None:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# Data Queries
# =========================
def list_courses() -> List[sqlite3.Row]:
    conn = db()
    rows = conn.execute("SELECT * FROM courses ORDER BY id").fetchall()
    conn.close()
    return rows


def list_students() -> List[str]:
    conn = db()
    rows = conn.execute("SELECT name FROM users WHERE role='student' ORDER BY name").fetchall()
    conn.close()
    return [r["name"] for r in rows]


def count_live_cards(course_id: int, user_name: Optional[str] = None) -> int:
    conn = db()
    if user_name:
        c = conn.execute(
            "SELECT COUNT(*) as c FROM live_cards WHERE course_id=? AND user_name=?",
            (course_id, user_name),
        ).fetchone()["c"]
    else:
        c = conn.execute(
            "SELECT COUNT(*) as c FROM live_cards WHERE course_id=?",
            (course_id,),
        ).fetchone()["c"]
    conn.close()
    return int(c)


def count_debug_requests(course_id: int, user_name: Optional[str] = None) -> int:
    conn = db()
    if user_name:
        c = conn.execute(
            "SELECT COUNT(*) as c FROM debug_requests WHERE course_id=? AND user_name=?",
            (course_id, user_name),
        ).fetchone()["c"]
    else:
        c = conn.execute(
            "SELECT COUNT(*) as c FROM debug_requests WHERE course_id=?",
            (course_id,),
        ).fetchone()["c"]
    conn.close()
    return int(c)


def latest_assignment(course_id: int) -> Optional[sqlite3.Row]:
    conn = db()
    row = conn.execute(
        "SELECT * FROM assignments WHERE course_id=? ORDER BY id DESC LIMIT 1",
        (course_id,),
    ).fetchone()
    conn.close()
    return row


def my_latest_submission(course_id: int, user_name: str, assignment_id: int) -> Optional[sqlite3.Row]:
    conn = db()
    row = conn.execute(
        """
        SELECT * FROM submissions
        WHERE course_id=? AND user_name=? AND assignment_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (course_id, user_name, assignment_id),
    ).fetchone()
    conn.close()
    return row


# =========================
# Core Features
# =========================
def create_live_card(
    course_id: int,
    user_name: str,
    title: str,
    tags: str,
    status: str,
    code_text: str,
    screenshot_path: Optional[str],
    description: str,
) -> None:
    conn = db()
    conn.execute(
        """
        INSERT INTO live_cards(course_id, user_name, title, tags, status, code_text, screenshot_path, description, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (course_id, user_name, title, tags, status, code_text, screenshot_path, description, now()),
    )
    conn.commit()
    conn.close()


def list_live_cards(
    course_id: int,
    status: str = "전체",
    only_mine: bool = False,
    user_name: Optional[str] = None,
    query: str = "",
) -> List[sqlite3.Row]:
    conn = db()

    sql = "SELECT * FROM live_cards WHERE course_id=?"
    params: List[Any] = [course_id]

    if status != "전체":
        sql += " AND status=?"
        params.append(status)

    if only_mine and user_name:
        sql += " AND user_name=?"
        params.append(user_name)

    if query.strip():
        sql += " AND (title LIKE ? OR tags LIKE ? OR description LIKE ?)"
        q = f"%{query.strip()}%"
        params.extend([q, q, q])

    sql += " ORDER BY id DESC LIMIT 40"
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    return rows


def create_debug_request(
    course_id: int,
    user_name: str,
    mode: str,
    code_text: str,
    error_text: str,
    image_path: Optional[str],
    environment: str,
    ai_result: Optional[str],
) -> None:
    conn = db()
    conn.execute(
        """
        INSERT INTO debug_requests(course_id, user_name, mode, code_text, error_text, image_path, environment, ai_result, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (course_id, user_name, mode, code_text, error_text, image_path, environment, ai_result, now()),
    )
    conn.commit()
    conn.close()


def submit_assignment(
    assignment: sqlite3.Row,
    course_id: int,
    user_name: str,
    report_path: Optional[str],
    code_path: Optional[str],
    image_paths: List[str],
    note: str,
) -> int:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO submissions(assignment_id, course_id, user_name, report_path, code_path, images_json, note, status, ai_json, created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            assignment["id"],
            course_id,
            user_name,
            report_path,
            code_path,
            json.dumps(image_paths, ensure_ascii=False),
            note,
            "제출",
            None,
            now(),
        ),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return int(sid)


def run_ai_grading(
    assignment: sqlite3.Row,
    submission_id: int,
) -> Tuple[bool, str]:
    """
    Store ai_json into submissions.ai_json, status=완료
    """
    conn = db()
    sub = conn.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
    if sub is None:
        conn.close()
        return False, "제출을 찾지 못했습니다."

    rubric = json.loads(assignment["rubric_json"])
    report_text = read_text_from_doc(sub["report_path"]) if sub["report_path"] else ""
    code_text = ""
    if sub["code_path"]:
        try:
            code_text = Path(sub["code_path"]).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            code_text = ""

    images = []
    try:
        images = json.loads(sub["images_json"] or "[]")
    except Exception:
        images = []

    # If report text empty, still proceed, but warn in prompt
    user_text = f"""
[과제]
- 제목: {assignment['title']}
- 정책: 코드 실행 금지(정적/증거 기반), 정답 전체 코드 제공 금지

[루브릭(JSON)]
{json.dumps(rubric, ensure_ascii=False, indent=2)}

[제출물]
- 학생: {sub['user_name']}
- 학생 한줄 설명(note): {sub['note']}

[보고서 텍스트 추출]
{report_text if report_text else "(텍스트 추출 실패 또는 비어 있음. 평가 시 '설명/회고' 항목은 증거 부족으로 처리하세요.)"}

[코드 텍스트(선택)]
{code_text if code_text else "(코드 파일이 없거나 읽지 못함. 코드 패턴 평가는 제한적으로 수행하세요.)"}

[요청]
1) 루브릭 항목별 점수(0~max)와 근거를 생성
2) 학생용 피드백(잘한점/개선점/다음 액션)을 간단히(6~10줄)
3) 교사용 요약(취약 개념/수업 처방 2개)
4) 결과는 반드시 JSON으로만 출력

[출력 JSON 스키마]
{{
  "overall_score": int,
  "rubric": [{{"id": str, "name": str, "score": int, "max": int, "rationale": str}}],
  "strengths": [str, ...],
  "improvements": [str, ...],
  "next_steps": [str, ...],
  "teacher_summary": {{
      "common_mistakes": [str, ...],
      "teaching_moves": [str, ...]
  }},
  "evidence_warnings": [str, ...]
}}
""".strip()

    instructions = (
        "너는 정보(코딩) 수업의 수행평가 보조 교사다. "
        "반드시 '코드 실행 없이' 제출물의 증거(문서/코드텍스트/스크린샷) 기반으로 평가한다. "
        "정답 전체 코드를 제공하지 말고, 수정 방향/체크리스트 중심으로 피드백한다. "
        "출력은 반드시 JSON만 반환한다."
    )

    # Mark as analyzing
    conn.execute("UPDATE submissions SET status=? WHERE id=?", ("분석중", submission_id))
    conn.commit()

    data, err = call_ai_json(instructions=instructions, user_text=user_text, image_paths=images)
    if data is None:
        conn.execute("UPDATE submissions SET status=?, ai_json=? WHERE id=?", ("제출", json.dumps({"error": err}, ensure_ascii=False), submission_id))
        conn.commit()
        conn.close()
        return False, f"AI 평가 실패: {err}"

    conn.execute(
        "UPDATE submissions SET status=?, ai_json=? WHERE id=?",
        ("완료", json.dumps(data, ensure_ascii=False), submission_id),
    )
    conn.commit()
    conn.close()
    return True, "AI 평가가 완료되었습니다."


def run_ai_debug(
    course_name: str,
    unit: str,
    lesson: str,
    mode: str,
    code_text: str,
    error_text: str,
    env: str,
    image_paths: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (ai_text, err)
    ai_text는 JSON이 아니라 사용자에게 바로 보여줄 텍스트(체크리스트 중심)
    """
    client = get_openai_client()
    if client is None:
        return None, "OPENAI_API_KEY가 설정되지 않았습니다."

    model = get_model_name()

    user_prompt = f"""
[수업 맥락] {course_name} / {unit} / {lesson}
[입력 방식] {mode}
[환경] {env}

[에러 메시지]
{error_text if error_text else "(없음)"}

[코드(선택)]
{code_text if code_text else "(없음)"}

[요청]
- 코드 실행 없이, 에러 유형 추정 + 원인 후보(상위 2개) + 확인 질문(1~2개)
- 수정 체크리스트(3~5단계) + 부분 예시(정답 전체 X)
- 출력은 보기 좋은 한국어 bullet 형식으로
""".strip()

    instructions = (
        "너는 정보(코딩) 수업의 디버깅 도우미다. "
        "학생에게 정답 전체 코드를 주지 말고, 원인 진단과 수정 단계(체크리스트) 중심으로 안내한다. "
        "코드 실행은 하지 않는다."
    )

    content = [{"type": "input_text", "text": user_prompt}]
    if image_paths:
        for ip in image_paths[:2]:
            url = image_to_data_url(ip)
            if url:
                content.append({"type": "input_image", "image_url": url})

    try:
        resp = client.responses.create(
            model=model,
            instructions=instructions,
            input=[{"role": "user", "content": content}],
        )
        text = getattr(resp, "output_text", None) or ""
        return text.strip(), None
    except Exception as e:
        return None, f"OpenAI 호출 실패: {e}"


# =========================
# Pages (Student / Teacher)
# =========================
def student_dashboard(course_row, user_name: str) -> None:
    course_id = course_row["id"]
    assignment = latest_assignment(course_id)
    a_id = assignment["id"] if assignment else None

    live_cnt = count_live_cards(course_id, user_name=user_name)
    debug_cnt = count_debug_requests(course_id, user_name=user_name)

    sub_status = "과제 없음"
    if assignment:
        my_sub = my_latest_submission(course_id, user_name, assignment["id"])
        sub_status = (my_sub["status"] if my_sub else "미제출")

    pills = [
        (f"실습카드 {live_cnt}", "pill-blue"),
        (f"오류/도움요청 {debug_cnt}", "pill-gray"),
        (f"과제: {sub_status}", "pill-orange"),
        ("퀴즈: (확장)", "pill-red"),
    ]
    top_navbar(
        title=f"{APP_TITLE} (Student)",
        subtitle=f"반: {course_row['name']} | 단원: {course_row['unit']} | 오늘: {course_row['lesson']}",
        pills=pills,
    )

    # 1) 오늘 안내 + 시작 코드
    left, right = st.columns([1.1, 1.0], gap="large")
    with left:
        card_open("[오늘 안내]")
        st.markdown("**학습 목표:** `for` 반복문으로 1~10 합 구하기")
        st.markdown("- 변수 초기화 → 누적 → 출력")
        st.markdown("**핵심 체크:** 범위(range), 누적 변수(total), print 위치")
        st.markdown('<hr class="soft">', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.button("시작 코드 보기", use_container_width=True)
        with c2:
            st.button("실습카드 올리기(아래 폼)", use_container_width=True)
        card_close()

    with right:
        card_open("[실습 1] 1~10 합(기본)")
        st.code(
            """total = 0
for i in range(1, 11):
    # 누적 코드를 작성하세요
    pass
print(total)""",
            language="python",
        )
        st.markdown("**시작 코드(힌트)**")
        st.markdown('<span class="tag">체크리스트</span> 범위 정확 · 초기화 · 누적 · 출력', unsafe_allow_html=True)
        card_close()

    st.write("")

    # 2) 실습 공유 보드 + 실습카드 업로드
    card_open("[라이브] 실습 공유 보드(패들렛 대체)")
    f1, f2, f3, f4, f5 = st.columns([1.1, 1.1, 1.0, 1.0, 1.6])
    with f1:
        status = st.selectbox("상태", ["전체", "완료", "도움요청", "공유"], index=0)
    with f2:
        sort = st.selectbox("정렬", ["최신", "도움요청 우선"], index=0)
    with f3:
        only_mine = st.checkbox("내 것만", value=False)
    with f4:
        show_form = st.checkbox("내 카드 올리기", value=True)
    with f5:
        query = st.text_input("검색", placeholder="키워드", label_visibility="collapsed")

    st.markdown('<hr class="soft">', unsafe_allow_html=True)

    if show_form:
        with st.expander("➕ 실습카드 업로드", expanded=True):
            title = st.text_input("제목", value="1~10 누적합 실습")
            tags = st.text_input("태그(예: #반복문 #누적합)", value="#반복문 #누적합")
            stt = st.selectbox("상태", ["완료", "도움요청", "공유"])
            code_text = st.text_area("코드 텍스트(선택)", height=120)
            shot = st.file_uploader("결과/에러 스크린샷(선택)", type=["png", "jpg", "jpeg"])
            desc = st.text_input("한 줄 설명(필수)", value="출력 55 확인")
            if st.button("업로드", type="primary"):
                sp = save_upload(shot, f"{course_id}/live_cards/{user_name}") if shot else None
                create_live_card(course_id, user_name, title, tags, stt, code_text, sp, desc)
                st.success("실습카드가 업로드되었습니다.")
                st.rerun()

    rows = list_live_cards(
        course_id=course_id,
        status=("전체" if status == "전체" else status),
        only_mine=only_mine,
        user_name=user_name,
        query=query,
    )

    # cards grid
    cols = st.columns(4, gap="medium")
    for i, r in enumerate(rows):
        col = cols[i % 4]
        with col:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown(f"**{r['title']}**")
            st.markdown(
                f'<span class="tag">{r["tags"]}</span> <span class="small">{r["status"]} · {r["user_name"]}</span>',
                unsafe_allow_html=True,
            )
            if r["screenshot_path"] and Path(r["screenshot_path"]).exists():
                st.image(r["screenshot_path"], use_container_width=True)
            else:
                st.image("https://via.placeholder.com/260x120.png?text=Screenshot", use_container_width=True)
            st.markdown(f"<div class='small'>{r['description'] or ''}</div>", unsafe_allow_html=True)

            if r["status"] == "도움요청":
                if st.button("🤖 AI진단보기", key=f"ai_diag_{r['id']}", use_container_width=True):
                    # Quick debug from card if contains clue
                    ai_text, err = run_ai_debug(
                        course_name=course_row["name"],
                        unit=course_row["unit"],
                        lesson=course_row["lesson"],
                        mode="text+image",
                        code_text=r["code_text"] or "",
                        error_text="(실습카드 도움요청) 에러 메시지가 있으면 함께 올려주세요.",
                        env="Unknown",
                        image_paths=[r["screenshot_path"]] if r["screenshot_path"] else None,
                    )
                    if err:
                        st.error(err)
                    else:
                        st.info(ai_text)
            else:
                st.button("💬 댓글(확장)", key=f"cmt_{r['id']}", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

    card_close()

    st.write("")

    # 3) 오류 도우미 + 내 피드백(하단 2열)
    left2, right2 = st.columns([1.05, 1.0], gap="large")

    with left2:
        card_open("[오류 도우미] 에러/디버깅(코드 실행 없음)")
        mode = st.radio("입력 방식", ["텍스트", "스크린샷"], horizontal=True)
        code_text = ""
        error_text = ""
        img_path = None

        if mode == "텍스트":
            code_text = st.text_area("코드(선택)", height=110, placeholder="문제 되는 코드 일부를 붙여넣어 주세요.")
            error_text = st.text_area("에러 메시지(필수)", height=80, placeholder="예: NameError: name 'total' is not defined")
        else:
            up = st.file_uploader("에러 포함 스크린샷 업로드(필수)", type=["png", "jpg", "jpeg"])
            if up:
                img_path = save_upload(up, f"{course_id}/debug/{user_name}")

        env = st.selectbox("환경(선택)", ["VSCode", "Colab", "IDLE", "기타"], index=0)

        if st.button("진단 요청", type="primary", use_container_width=True):
            imgs = [img_path] if img_path else None
            ai_text, err = run_ai_debug(
                course_name=course_row["name"],
                unit=course_row["unit"],
                lesson=course_row["lesson"],
                mode=("text" if mode == "텍스트" else "image"),
                code_text=code_text,
                error_text=error_text,
                env=env,
                image_paths=imgs,
            )
            if err:
                st.error(err)
                create_debug_request(course_id, user_name, "text" if mode == "텍스트" else "image",
                                    code_text, error_text, img_path, env, json.dumps({"error": err}, ensure_ascii=False))
            else:
                st.success("진단 완료!")
                st.info(ai_text)
                create_debug_request(course_id, user_name, "text" if mode == "텍스트" else "image",
                                    code_text, error_text, img_path, env, ai_text)

        card_close()

    with right2:
        card_open("[내 피드백] 루브릭/AI")
        if assignment is None:
            st.warning("과제가 아직 생성되지 않았습니다(데모에서는 자동 생성됨).")
            card_close()
        else:
            st.markdown(f"**과제:** {assignment['title']}  ·  마감: {assignment['due_date']}")
            my_sub = my_latest_submission(course_id, user_name, assignment["id"])
            if my_sub is None:
                st.info("아직 제출이 없습니다. 아래 '과제 제출' 메뉴에서 제출해 주세요.")
            else:
                st.markdown(f"**상태:** {my_sub['status']}  ·  제출일: {my_sub['created_at']}")
                if my_sub["ai_json"]:
                    try:
                        ai = json.loads(my_sub["ai_json"])
                    except Exception:
                        ai = {"raw": my_sub["ai_json"]}

                    if "error" in ai:
                        st.error(f"AI 오류: {ai['error']}")
                    else:
                        st.metric("종합 점수", f"{ai.get('overall_score', '-') } / 100")
                        st.markdown("**루브릭 항목별**")
                        for item in ai.get("rubric", []):
                            score = item.get("score", 0)
                            mx = item.get("max", 1)
                            p = 0 if mx == 0 else min(max(score / mx, 0), 1)
                            st.progress(p, text=f"{item.get('name','')} ({score}/{mx})")
                        st.info("AI 요약 피드백\n- " + "\n- ".join(ai.get("next_steps", [])[:3]))
                else:
                    st.info("AI 평가 결과가 없습니다. 교사/학생이 'AI 평가 실행'을 눌러 생성할 수 있어요.")
        card_close()


def student_assignment_submit(course_row, user_name: str) -> None:
    course_id = course_row["id"]
    assignment = latest_assignment(course_id)
    if assignment is None:
        st.warning("과제가 없습니다. 교사 모드에서 과제를 생성해 주세요.")
        return

    pills = [
        ("과제 제출", "pill-blue"),
        ("코드 실행 없음", "pill-gray"),
        ("루브릭 자동 평가", "pill-orange"),
        ("AI 피드백", "pill-green"),
    ]
    top_navbar(
        title=f"{APP_TITLE} (Student)",
        subtitle=f"반: {course_row['name']} | 과제: {assignment['title']}",
        pills=pills,
    )

    card_open("과제 제출(LMS)")
    st.markdown("제출물: **보고서(PDF/DOCX)** + **결과 캡처(1장 이상)** + (선택) **코드파일(.py)**")
    st.markdown("<span class='small'>*Streamlit Cloud에서는 파일이 영구 저장되지 않을 수 있어요(텀 프로젝트 데모는 OK).</span>", unsafe_allow_html=True)

    report = st.file_uploader("보고서(PDF/DOCX) 업로드(필수)", type=["pdf", "docx"])
    images = st.file_uploader("결과 캡처 이미지 업로드(필수, 1장 이상)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
    code_file = st.file_uploader("코드 파일(.py) 업로드(선택)", type=["py"])
    note = st.text_input("한 줄 설명(필수)", value="출력 결과(55) 캡처 포함")

    c1, c2 = st.columns([1, 1])
    with c1:
        do_submit = st.button("제출하기", type="primary", use_container_width=True)
    with c2:
        do_ai = st.button("제출+AI평가(바로)", use_container_width=True)

    if do_submit or do_ai:
        if report is None:
            st.error("보고서를 업로드해 주세요.")
            card_close()
            return
        if not images or len(images) == 0:
            st.error("결과 캡처 이미지를 1장 이상 업로드해 주세요.")
            card_close()
            return
        if not note.strip():
            st.error("한 줄 설명을 입력해 주세요.")
            card_close()
            return

        report_path = save_upload(report, f"{course_id}/submissions/{user_name}/report")
        code_path = save_upload(code_file, f"{course_id}/submissions/{user_name}/code") if code_file else None

        image_paths = []
        for im in images:
            ip = save_upload(im, f"{course_id}/submissions/{user_name}/images")
            if ip:
                image_paths.append(ip)

        sid = submit_assignment(assignment, course_id, user_name, report_path, code_path, image_paths, note)
        st.success(f"제출 완료! (submission_id={sid})")

        if do_ai:
            ok, msg = run_ai_grading(assignment, sid)
            if ok:
                st.success(msg)
            else:
                st.error(msg)

        st.rerun()

    card_close()


def teacher_console(course_row) -> None:
    course_id = course_row["id"]
    assignment = latest_assignment(course_id)

    pills = [
        (f"실습카드 {count_live_cards(course_id)}", "pill-blue"),
        (f"오류요청 {count_debug_requests(course_id)}", "pill-gray"),
        ("과제/루브릭", "pill-orange"),
        ("AI 리포트", "pill-green"),
    ]
    top_navbar(
        title=f"{APP_TITLE} (Teacher)",
        subtitle=f"반: {course_row['name']} | 단원: {course_row['unit']} | 오늘: {course_row['lesson']}",
        pills=pills,
    )

    tabs = st.tabs(["수업 대시보드", "과제/루브릭", "제출/평가", "오류 통계"])

    # ---- Dashboard
    with tabs[0]:
        left, right = st.columns([1, 1], gap="large")
        with left:
            card_open("Top 오류(최근 10건 요약)")
            conn = db()
            rows = conn.execute(
                "SELECT * FROM debug_requests WHERE course_id=? ORDER BY id DESC LIMIT 10",
                (course_id,),
            ).fetchall()
            conn.close()

            if not rows:
                st.info("오류 요청이 없습니다.")
            else:
                for r in rows:
                    st.markdown(f"- **{r['user_name']}** · {r['created_at']} · {r['environment']}")
                    if r["error_text"]:
                        st.code(r["error_text"][:200])
            card_close()

        with right:
            card_open("라이브 보드 요약(최근 8개)")
            conn = db()
            rows = conn.execute(
                "SELECT * FROM live_cards WHERE course_id=? ORDER BY id DESC LIMIT 8",
                (course_id,),
            ).fetchall()
            conn.close()
            if not rows:
                st.info("실습 카드가 없습니다.")
            else:
                for r in rows:
                    st.markdown(f"- **{r['title']}** · {r['status']} · {r['user_name']}")
            card_close()

    # ---- Assignment / Rubric
    with tabs[1]:
        card_open("과제/루브릭 관리")
        st.markdown("텀 프로젝트 MVP: 과제 1개(A01) + 루브릭 수정/저장")

        if assignment:
            st.markdown(f"**현재 과제:** {assignment['title']} (마감: {assignment['due_date']})")
            rubric = json.loads(assignment["rubric_json"])
        else:
            st.warning("과제가 없습니다. 아래에서 생성하세요.")
            rubric = default_rubric_A01()

        with st.expander("루브릭 JSON 편집", expanded=True):
            rubric_text = st.text_area("rubric_json", value=json.dumps(rubric, ensure_ascii=False, indent=2), height=300)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("루브릭 저장", type="primary"):
                    try:
                        rb = json.loads(rubric_text)
                        conn = db()
                        if assignment:
                            conn.execute(
                                "UPDATE assignments SET rubric_json=? WHERE id=?",
                                (json.dumps(rb, ensure_ascii=False), assignment["id"]),
                            )
                        else:
                            conn.execute(
                                """
                                INSERT INTO assignments(course_id, title, due_date, rubric_json, created_at)
                                VALUES(?,?,?,?,?)
                                """,
                                (course_id, "A01 반복문 누적합(1~10)", "2026-02-01", json.dumps(rb, ensure_ascii=False), now()),
                            )
                        conn.commit()
                        conn.close()
                        st.success("저장 완료")
                        st.rerun()
                    except Exception as e:
                        st.error(f"JSON 파싱 실패: {e}")

            with c2:
                if st.button("기본 루브릭 되돌리기"):
                    st.session_state["__reset_rubric"] = True
                    st.rerun()

        if st.session_state.get("__reset_rubric"):
            st.session_state.pop("__reset_rubric", None)
            st.info("기본 루브릭을 다시 불러오려면 페이지를 새로고침 후 저장하세요.")

        card_close()

    # ---- Submissions / Grading
    with tabs[2]:
        card_open("제출 목록/AI 평가 실행")
        if not assignment:
            st.warning("과제가 없습니다.")
            card_close()
        else:
            conn = db()
            subs = conn.execute(
                "SELECT * FROM submissions WHERE assignment_id=? ORDER BY id DESC LIMIT 50",
                (assignment["id"],),
            ).fetchall()
            conn.close()

            if not subs:
                st.info("제출이 없습니다.")
            else:
                for sub in subs:
                    with st.expander(f"#{sub['id']} · {sub['user_name']} · 상태: {sub['status']} · {sub['created_at']}", expanded=False):
                        st.write(f"note: {sub['note']}")
                        if sub["report_path"]:
                            st.write("보고서:", sub["report_path"])
                        if sub["images_json"]:
                            try:
                                ips = json.loads(sub["images_json"])
                            except Exception:
                                ips = []
                            if ips:
                                st.image(ips[0], caption="결과 캡처(첫 장)", use_container_width=True)

                        c1, c2 = st.columns([1, 1])
                        with c1:
                            if st.button("AI 평가 실행", key=f"grade_{sub['id']}", use_container_width=True):
                                ok, msg = run_ai_grading(assignment, sub["id"])
                                if ok:
                                    st.success(msg)
                                else:
                                    st.error(msg)
                                st.rerun()
                        with c2:
                            if sub["ai_json"]:
                                try:
                                    ai = json.loads(sub["ai_json"])
                                except Exception:
                                    ai = {"raw": sub["ai_json"]}
                                if "overall_score" in ai:
                                    st.metric("점수", f"{ai['overall_score']} / 100")
                                    st.markdown("**교사용 요약**")
                                    ts = ai.get("teacher_summary", {})
                                    st.markdown("- 흔한 실수: " + ", ".join(ts.get("common_mistakes", [])[:3]))
                                    st.markdown("- 처방: " + " / ".join(ts.get("teaching_moves", [])[:2]))
                                elif "error" in ai:
                                    st.error(ai["error"])
                                else:
                                    st.code(str(ai)[:800])
        card_close()

    # ---- Debug Stats
    with tabs[3]:
        card_open("오류 통계(간단)")
        conn = db()
        rows = conn.execute(
            "SELECT environment, COUNT(*) as c FROM debug_requests WHERE course_id=? GROUP BY environment ORDER BY c DESC",
            (course_id,),
        ).fetchall()
        conn.close()

        if not rows:
            st.info("오류 요청이 없습니다.")
        else:
            for r in rows:
                st.markdown(f"- **{r['environment']}**: {r['c']}건")

        card_close()


# =========================
# App Start
# =========================
init_db()
seed_demo_data()

courses = list_courses()
course_map = {c["name"]: c for c in courses}

with st.sidebar:
    st.markdown(f"### {APP_TITLE}")
    role = st.radio("모드", ["학생(Student)", "교사(Teacher)"], index=0)
    st.divider()

    course_name = st.selectbox("코스 선택", list(course_map.keys()), index=0)
    course_row = course_map[course_name]

    if role.startswith("학생"):
        user_name = st.selectbox("학생", list_students(), index=0)
    else:
        user_name = "교사"

    st.divider()
    menu = st.radio(
        "메뉴",
        ["대시보드(한 화면)", "과제 제출", "교사용 콘솔"],
        index=0,
    )

# Route
if role.startswith("교사"):
    # Teacher mode
    teacher_console(course_row)
else:
    # Student mode
    if menu == "과제 제출":
        student_assignment_submit(course_row, user_name)
    elif menu == "교사용 콘솔":
        st.info("학생 모드에서는 교사용 콘솔을 사용할 수 없습니다.")
    else:
        student_dashboard(course_row, user_name)

# Footer note
st.caption("※ CodeClass Hub MVP: 코드 실행 없이(정적/증거 기반) 평가·피드백을 제공합니다. 민감정보 업로드는 피해주세요.")
