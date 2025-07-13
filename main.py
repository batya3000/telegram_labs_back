from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import os
import yaml
import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File
from dotenv import load_dotenv
from itsdangerous import TimestampSigner, BadSignature
import re

load_dotenv()
app = FastAPI()

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body}
    )
COURSES_DIR = "courses"
CREDENTIALS_FILE = "credentials.json"  # Файл с учетными данными Google API
CODES_SHEET = "users"
ADMINS_SHEET = "admins"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Разрешить запросы с любых источников
    allow_credentials=True,
    allow_methods=["*"],  # Разрешить все HTTP-методы
    allow_headers=["*"],  # Разрешить все заголовки
)
signer = TimestampSigner(SECRET_KEY)

class AuthRequest(BaseModel):
    login: str
    password: str


class StudentRegistration(BaseModel):
    name: str = Field(..., min_length=1)
    surname: str = Field(..., min_length=1)
    patronymic: str = ""
    github: str = Field(..., min_length=1)


@app.get("/")
async def read_index():
    return FileResponse("dist/index.html")

@app.post("/api/admin/login")
def admin_login(data: AuthRequest, response: Response):
    if data.login == ADMIN_LOGIN and data.password == ADMIN_PASSWORD:
        token = signer.sign(data.login.encode()).decode()
        response.set_cookie(
            key="admin_session",
            value=token,
            httponly=True,
            max_age=3600,
            path="/",
            secure=False
        )
        return {"authenticated": True}
    raise HTTPException(status_code=401, detail="Неверный логин или пароль")

@app.get("/api/admin/check-auth")
def check_auth(request: Request):
    cookie = request.cookies.get("admin_session")
    if not cookie:
        raise HTTPException(status_code=401, detail="Нет сессии")

    try:
        login = signer.unsign(cookie, max_age=3600).decode()
    except BadSignature:
        raise HTTPException(status_code=401, detail="Невалидная или просроченная сессия")

    if login != ADMIN_LOGIN:
        raise HTTPException(status_code=401, detail="Невалидная сессия")

    return {"authenticated": True}

@app.post("/api/admin/logout")
def logout(response: Response):
    response.delete_cookie("admin_session", path="/")
    return {"message": "Logged out"}


@app.get("/courses")
def get_courses():
    courses = []
    for index, filename in enumerate(sorted(os.listdir(COURSES_DIR)), start=1):
        file_path = os.path.join(COURSES_DIR, filename)
        if filename.endswith(".yaml") and os.path.isfile(file_path):
            with open(file_path, "r", encoding="utf-8") as file:
                try:
                    data = yaml.safe_load(file)
                except yaml.YAMLError as e:
                    print(f"Ошибка при разборе YAML в {filename}: {e}")
                    continue

                if not isinstance(data, dict) or "course" not in data:
                    print(f"Пропускаем файл {filename}: неверная структура")
                    continue

                course_info = data["course"]
                courses.append({
                    "id": str(index),
                    "name": course_info.get("name", "Unknown"),
                    "semester": course_info.get("semester", "Unknown"),
                    "logo": course_info.get("logo", "/assets/default.png"),
                    "email": course_info.get("email", ""),
                })
    return courses


def parse_lab_id(lab_id: str) -> int:
    match = re.search(r"\d+", lab_id)
    if not match:
        raise HTTPException(status_code=400, detail="Некорректный lab_id")
    return int(match.group(0))

@app.get("/courses/{course_id}")
def get_course(course_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        return {
            "id": course_id,
            "config": filename,
            "name": course_info.get("name", "Unknown"),
            "semester": course_info.get("semester", "Unknown"),
            "email": course_info.get("email", "Unknown"),
            "github-organization": course_info.get("github", {}).get("organization", "Unknown"),
            "google-spreadsheet": course_info.get("google", {}).get("spreadsheet", "Unknown"),
        }

@app.delete("/courses/{course_id}")
def delete_course(course_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Курс не найден")

    file_path = os.path.join(COURSES_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"message": "Курс успешно удален"}
    else:
        raise HTTPException(status_code=404, detail="Файл курса не найден")


class EditCourseRequest(BaseModel):
    content: str


@app.get("/courses/{course_id}/edit")
def edit_course_get(course_id: str):
    """Получить YAML содержимое курса для редактирования"""
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Курс не найден")

    file_path = os.path.join(COURSES_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл курса не найден")

    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()

    return {"filename": filename, "content": content}


@app.put("/courses/{course_id}/edit")
def edit_course_put(course_id: str, data: EditCourseRequest):
    """Сохранить изменения в YAML файле курса"""
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Курс не найден")

    file_path = os.path.join(COURSES_DIR, filename)


    try:
        yaml.safe_load(data.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Ошибка в YAML формате: {str(e)}")

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(data.content)

    return {"message": "Изменения успешно сохранены"}


@app.get("/courses/{course_id}/groups")
def get_course_groups(course_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
        info_sheet = course_info.get("google", {}).get("info-sheet")

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID not found in course config")


    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        all_sheets = [sheet.title for sheet in spreadsheet.worksheets() 
                      if sheet.title not in [info_sheet, "users"]]
        
        course_filename = [f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")][int(course_id) - 1]
        course_name = course_filename.replace(".yaml", "")
        course_sheets = []
        for sheet_name in all_sheets:
            if "_" in sheet_name:
                group_part, course_part = sheet_name.split("_", 1)
                if course_part == course_name:
                    course_sheets.append(group_part)
        
        return course_sheets
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch sheets: {str(e)}")


@app.get("/courses/{course_id}/groups/{group_id}/labs")
def get_course_labs(course_id: str, group_id: str):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Missing spreadsheet ID in config")


    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        course_name = filename.replace(".yaml", "")
        sheet_name = f"{group_id}_{course_name}"
        sheet = spreadsheet.worksheet(sheet_name)

        headers = sheet.row_values(1)[3:]
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Group not found in spreadsheet: {str(e)}")

    return [lab for lab in headers if lab.startswith("ЛР")]


@app.post("/courses/{course_id}/groups/{group_id}/register")
def register_student(course_id: str, group_id: str, student: StudentRegistration):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
        student_col = course_info.get("google", {}).get("student-name-column", 2)

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID not found in course config")


    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.worksheet(group_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Group not found in spreadsheet")

    full_name = f"{student.surname} {student.name} {student.patronymic}".strip()


    student_list = sheet.col_values(student_col)[2:]

    if full_name not in student_list:
        raise HTTPException(status_code=406, detail={"message": "Студент не найден"})

    row_idx = student_list.index(full_name) + 3


    header_row = sheet.row_values(1)
    try:
        github_col_idx = header_row.index("GitHub") + 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Столбец 'GitHub' не найден в таблице")


    try:
        github_response = requests.get(f"https://api.github.com/users/{student.github}")
        if github_response.status_code != 200:
            raise HTTPException(status_code=404, detail={"message": "Пользователь GitHub не найден"})
    except Exception:
        raise HTTPException(status_code=500, detail="Ошибка проверки GitHub пользователя")

    existing_github = sheet.cell(row_idx, github_col_idx).value

    if not existing_github:
        sheet.update_cell(row_idx, github_col_idx, student.github)
        return {"status": "registered", "message": "Аккаунт GitHub успешно задан"}

    if existing_github == student.github:
        return {
            "status": "already_registered",
            "message": "Этот аккаунт GitHub уже был указан ранее для этого же студента"
        }

    raise HTTPException(status_code=409, detail={
        "status": "conflict",
        "message": "Аккаунт GitHub уже был указан ранее. Для изменения аккаунта обратитесь к преподавателю"
    })


def normalize_lab_id(lab_id: str) -> str:
    """Возвращает нормализованную строку вида ЛР1, ЛР2 и т.д."""
    number = parse_lab_id(lab_id)
    return f"ЛР{number}"


class GradeRequest(BaseModel):
    github: str = Field(..., min_length=1)

class ChatRegistrationRequest(BaseModel):
    chat_id: int

@app.post("/courses/{course_id}/groups/{group_id}/labs/{lab_id}/grade")
def grade_lab(course_id: str, group_id: str, lab_id: str, request: GradeRequest):
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        org = course_info.get("github", {}).get("organization")
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
        student_col = course_info.get("google", {}).get("student-name-column", 2)
        lab_offset = course_info.get("google", {}).get("lab-column-offset", 1)

    labs = course_info.get("labs", {})
    normalized_lab_id = normalize_lab_id(lab_id)
    lab_config = labs.get(normalized_lab_id, {})
    repo_prefix = lab_config.get("github-prefix")

    if not all([org, spreadsheet_id, repo_prefix]):
        raise HTTPException(status_code=400, detail="Missing course configuration")

    username = request.github
    repo_name = f"{repo_prefix}-{username}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }


    workflows_url = f"https://api.github.com/repos/{org}/{repo_name}/contents/.github/workflows"
    if requests.get(workflows_url, headers=headers).status_code != 200:
        raise HTTPException(status_code=400, detail="⚠️ Папка .github/workflows не найдена. CI не настроен")

    commits_url = f"https://api.github.com/repos/{org}/{repo_name}/commits"
    commits_resp = requests.get(commits_url, headers=headers)
    if commits_resp.status_code != 200 or not commits_resp.json():
        raise HTTPException(status_code=404, detail="Нет коммитов в репозитории")

    latest_sha = commits_resp.json()[0]["sha"]


    check_url = f"https://api.github.com/repos/{org}/{repo_name}/commits/{latest_sha}/check-runs"
    check_resp = requests.get(check_url, headers=headers)
    if check_resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Проверки CI не найдены")

    check_runs = check_resp.json().get("check_runs", [])
    if not check_runs:
        return {"status": "pending", "message": "Нет активных CI-проверок ⏳"}

    summary = []
    passed_count = 0

    for check in check_runs:
        name = check.get("name", "Unnamed check")
        conclusion = check.get("conclusion")
        html_url = check.get("html_url")
        if conclusion == "success":
            emoji = "✅"
            passed_count += 1
        elif conclusion == "failure":
            emoji = "❌"
        else:
            emoji = "⏳"
        summary.append(f"{emoji} {name} — {html_url}")

    total_checks = len(check_runs)
    result_string = f"{passed_count}/{total_checks} тестов пройдено"

    final_result = "✓" if passed_count == total_checks else "✗"

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    try:
        course_name = filename.replace(".yaml", "")
        sheet_name = f"{group_id}_{course_name}"
        sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
    except Exception:
        raise HTTPException(status_code=404, detail="Группа не найдена в Google Таблице")

    header_row = sheet.row_values(1)
    
    id_values = sheet.col_values(1)[1:]
    
    try:
        github_col_idx = header_row.index("GitHub") + 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Столбец 'GitHub' не найден")
    
    github_values = sheet.col_values(github_col_idx)[1:]
    if username not in github_values:
        raise HTTPException(status_code=404, detail="GitHub логин не найден в таблице. Зарегистрируйтесь.")

    lab_number = parse_lab_id(lab_id)
    row_idx = github_values.index(username) + 2
    
    headers = sheet.row_values(1)
    lab_header = f"ЛР{lab_number}"
    
    try:
        lab_col = headers.index(lab_header) + 1
        print(f"[DEBUG] Lab {lab_id} (header '{lab_header}') for {username}: row {row_idx}, col {lab_col}")
    except ValueError:
        print(f"[DEBUG] Lab header '{lab_header}' not found in headers: {headers}")
        lab_col = github_col_idx + lab_offset + lab_number
        print(f"[DEBUG] Using fallback: row {row_idx}, col {lab_col}")
    
    sheet.update_cell(row_idx, lab_col, final_result)

    return {
        "status": "updated",
        "result": final_result,
        "message": f"{'✅ Все проверки пройдены' if final_result == '✓' else '❌ Обнаружены ошибки'}",
        "passed": result_string,
        "checks": summary
    }




@app.post("/courses/upload")
async def upload_course(file: UploadFile = File(...)):
    if not file.filename.endswith(".yaml") and not file.filename.endswith(".yml"):
        raise HTTPException(status_code=400, detail="Только YAML файлы разрешены")
    file_location = os.path.join(COURSES_DIR, file.filename)

    if os.path.exists(file_location):
        raise HTTPException(status_code=400, detail="Файл с таким именем уже существует")

    content = await file.read()
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail="Некорректный YAML файл")

    with open(file_location, "wb") as f:
        f.write(content)

    return {"detail": "Курс успешно загружен"}


class CodeLogin(BaseModel):
    chat_id: int
    code: str

class GitHubUpdate(BaseModel):
    chat_id: int
    github: str

class AdminCodeLogin(BaseModel):
    chat_id: int
    code: str

@app.post("/auth/code/login")
def code_login(body: CodeLogin):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    ws = client.open_by_key(SPREADSHEET_ID).worksheet(CODES_SHEET)

    header = [h.strip() for h in ws.row_values(1)]
    try:
        chat_col_idx = header.index("tg_chat_id") + 1
    except ValueError:
        raise HTTPException(500, "column tg_chat_id not found")

    records = ws.get_all_records()
    row_i, rec = next(
        ((i, r) for i, r in enumerate(records, start=2)
         if str(r["code"]).strip() == body.code),
        (None, None),
    )
    if rec is None:
        raise HTTPException(401, "invalid code")

    code_owner = str(rec.get("tg_chat_id") or "").strip()
    if code_owner and code_owner != str(body.chat_id):
        raise HTTPException(401, "code bound to another chat")

    is_new_chat_id = not code_owner
    
    if is_new_chat_id:
        ws.update_cell(row_i, chat_col_idx, str(body.chat_id))

    github_value = str(rec.get("github", "")).strip()
    
    return {
        "ok": True,
        "student_name": rec.get("student_name", "").strip(),
        "has_github": bool(github_value and github_value != ""),
        "is_new_chat_id": is_new_chat_id
    }

@app.post("/auth/github/update")
def update_github(body: GitHubUpdate):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    ws = client.open_by_key(SPREADSHEET_ID).worksheet(CODES_SHEET)

    header = [h.strip() for h in ws.row_values(1)]
    try:
        github_col_idx = header.index("github") + 1
    except ValueError:
        raise HTTPException(500, "column github not found")

    records = ws.get_all_records()
    row_i, rec = next(
        ((i, r) for i, r in enumerate(records, start=2)
         if str(r.get("tg_chat_id")) == str(body.chat_id)),
        (None, None),
    )
    if rec is None:
        raise HTTPException(404, "user not found")

    # Проверяем что GitHub username существует
    try:
        github_response = requests.get(f"https://api.github.com/users/{body.github}")
        if github_response.status_code != 200:
            raise HTTPException(400, "GitHub пользователь не найден")
    except requests.RequestException:
        raise HTTPException(500, "Ошибка проверки GitHub пользователя")

    ws.update_cell(row_i, github_col_idx, body.github)

    return {
        "ok": True,
        "message": "GitHub успешно сохранен"
    }

@app.post("/auth/admin/code/login")
def admin_code_login(body: AdminCodeLogin):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    ws = client.open_by_key(SPREADSHEET_ID).worksheet(ADMINS_SHEET)

    header = [h.strip() for h in ws.row_values(1)]
    try:
        chat_col_idx = header.index("tg_chat_id") + 1
    except ValueError:
        raise HTTPException(500, "column tg_chat_id not found in admins sheet")

    records = ws.get_all_records()
    row_i, rec = next(
        ((i, r) for i, r in enumerate(records, start=2)
         if str(r["code"]).strip() == body.code),
        (None, None),
    )
    if rec is None:
        raise HTTPException(401, "invalid admin code")

    code_owner = str(rec.get("tg_chat_id") or "").strip()
    if code_owner and code_owner != str(body.chat_id):
        raise HTTPException(401, "admin code bound to another chat")

    # Всегда обновляем chat_id (может быть повторный вход)
    if not code_owner:
        ws.update_cell(row_i, chat_col_idx, str(body.chat_id))

    return {
        "ok": True,
        "admin_name": rec.get("admin_name", "").strip(),
        "permissions": rec.get("permissions", "").strip()
    }

@app.get("/admin/courses")
def get_admin_courses(chat_id: int):
    """Получить список курсов для админа"""
    # Проверяем что пользователь админ
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    try:
        ws = client.open_by_key(SPREADSHEET_ID).worksheet(ADMINS_SHEET)
        
        rec = next(
            (r for r in ws.get_all_records()
             if str(r.get("tg_chat_id")) == str(chat_id)),
            None,
        )
        if rec is None:
            raise HTTPException(403, "access denied - not an admin")
    except Exception:
        raise HTTPException(403, "access denied")

    # Возвращаем список всех курсов
    courses = []
    for index, filename in enumerate(sorted(os.listdir(COURSES_DIR)), start=1):
        file_path = os.path.join(COURSES_DIR, filename)
        if filename.endswith(".yaml") and os.path.isfile(file_path):
            with open(file_path, "r", encoding="utf-8") as file:
                try:
                    data = yaml.safe_load(file)
                except yaml.YAMLError as e:
                    continue

                if not isinstance(data, dict) or "course" not in data:
                    continue

                course_info = data["course"]
                courses.append({
                    "id": str(index),
                    "filename": filename,
                    "name": course_info.get("name", "Unknown"),
                    "semester": course_info.get("semester", "Unknown"),
                })
    return courses

@app.get("/admin/courses/{course_id}/yaml")
def get_course_yaml(course_id: str, chat_id: int):
    """Получить YAML содержимое курса"""
    # Проверяем что пользователь админ
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    try:
        ws = client.open_by_key(SPREADSHEET_ID).worksheet(ADMINS_SHEET)
        
        rec = next(
            (r for r in ws.get_all_records()
             if str(r.get("tg_chat_id")) == str(chat_id)),
            None,
        )
        if rec is None:
            raise HTTPException(403, "access denied - not an admin")
    except Exception:
        raise HTTPException(403, "access denied")

    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, detail="Course file not found")

    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()

    return {"filename": filename, "content": content}

@app.delete("/admin/courses/{course_id}")
def delete_course_admin(course_id: str, chat_id: int):
    """Удалить курс (только для админов)"""
    # Проверяем что пользователь админ
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    try:
        ws = client.open_by_key(SPREADSHEET_ID).worksheet(ADMINS_SHEET)
        
        rec = next(
            (r for r in ws.get_all_records()
             if str(r.get("tg_chat_id")) == str(chat_id)),
            None,
        )
        if rec is None:
            raise HTTPException(403, "access denied - not an admin")
    except Exception:
        raise HTTPException(403, "access denied")

    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Курс не найден")

    file_path = os.path.join(COURSES_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"message": f"Курс {filename} успешно удален"}
    else:
        raise HTTPException(status_code=404, detail="Файл курса не найден")

@app.get("/admin/check-chat/{chat_id}")
def check_admin_chat(chat_id: int):
    """Проверить является ли пользователь админом по chat_id"""
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    try:
        ws = client.open_by_key(SPREADSHEET_ID).worksheet(ADMINS_SHEET)
        
        rec = next(
            (r for r in ws.get_all_records()
             if str(r.get("tg_chat_id")) == str(chat_id)),
            None,
        )
        if rec is None:
            raise HTTPException(403, "access denied - not an admin")
        
        return {"is_admin": True, "admin_name": rec.get("name", "администратор")}
    except Exception:
        raise HTTPException(403, "access denied")

@app.post("/auth/admin/logout")
def admin_logout(body: AdminCodeLogin):
    """Выйти из админской сессии"""
    # В данной реализации мы просто возвращаем успех
    # так как состояние хранится в памяти бота
    return {"message": "Выход выполнен"}

@app.get("/labs/by-chat/{chat_id}")
def labs_for_chat(chat_id: int):
    creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    ws     = client.open_by_key(SPREADSHEET_ID).worksheet(CODES_SHEET)

    rec = next(
        (r for r in ws.get_all_records()
         if str(r.get("tg_chat_id")) == str(chat_id)),
        None,
    )
    if rec is None:
        raise HTTPException(404, "student not found")

    course_ids_str = rec.get("course_id", "")
    allowed_course_ids = [cid.strip() for cid in course_ids_str.split(",") if cid.strip()]
    group = str(rec["group"])

    result = []
    
    for course_id in allowed_course_ids:
        try:
            with open(f"courses/{course_id}.yaml", encoding="utf-8") as f:
                course_yaml = yaml.safe_load(f)

            course_block = course_yaml.get("course", {})
            labs_dict    = course_block.get("labs", {})

            for key, cfg in labs_dict.items():
                if "groups" in cfg and group not in cfg["groups"]:
                    continue

                result.append(
                    {
                        "key":        key,
                        "title":      cfg.get("short-name", key),
                        "deadline":   cfg.get("deadline"),
                        "repo_prefix": cfg["github-prefix"],
                        "course_name": course_block.get("name", course_id),
                    }
                )
        except FileNotFoundError:
            continue

    return {"labs": result}

@app.get("/courses/by-chat/{chat_id}")
def courses_for_chat(chat_id: int):
    creds  = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    ws     = client.open_by_key(SPREADSHEET_ID).worksheet(CODES_SHEET)

    rec = next(
        (r for r in ws.get_all_records()
         if str(r.get("tg_chat_id")) == str(chat_id)),
        None,
    )
    if rec is None:
        raise HTTPException(404, "student not found")

    student_group = str(rec["group"])
    course_ids_str = rec.get("course_id", "")
    allowed_course_ids = [cid.strip() for cid in course_ids_str.split(",") if cid.strip()]
    
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    
    result = []
    for i, filename in enumerate(files):
        course_filename = filename.replace(".yaml", "")
        if allowed_course_ids and course_filename not in allowed_course_ids:
            continue
            
        file_path = os.path.join(COURSES_DIR, filename)
        with open(file_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
            course_info = data.get("course", {})
            
            spreadsheet_id = course_info.get("google", {}).get("spreadsheet")
            if spreadsheet_id:
                try:
                    course_client = gspread.authorize(creds)
                    spreadsheet = course_client.open_by_key(spreadsheet_id)
                except (PermissionError, Exception) as e:
                    print(f"Ошибка доступа к Google Sheets для курса {filename}: {e}")
                    continue
                
                worksheet_names = [ws.title for ws in spreadsheet.worksheets()]
                info_sheet = course_info.get("google", {}).get("info-sheet", "График")
                
                course_name = filename.replace(".yaml", "")
                
                available_groups = []
                for sheet_name in worksheet_names:
                    if sheet_name not in [info_sheet, "users"] and "_" in sheet_name:
                        group_part, course_part = sheet_name.split("_", 1)
                        if course_part == course_name:
                            available_groups.append(group_part)
                
                if student_group in available_groups:
                    result.append({
                        "id": str(i + 1),
                        "name": course_info.get("name", "Unnamed Course"),
                        "semester": course_info.get("semester", ""),
                        "logo": course_info.get("logo", "/assets/default.png"),
                        "email": course_info.get("email", "")
                    })
    
    return result

@app.post("/courses/{course_id}/groups/{group_id}/register-by-chat")
def register_student_by_chat(course_id: str, group_id: str, request: ChatRegistrationRequest):
    chat_id = request.chat_id
    
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
        client = gspread.authorize(creds)
        ws = client.open_by_key(SPREADSHEET_ID).worksheet(CODES_SHEET)

        rec = next(
            (r for r in ws.get_all_records()
             if str(r.get("tg_chat_id")) == str(chat_id)),
            None,
        )
        if rec is None:
            raise HTTPException(404, "Student not found")

        student_name = rec.get("student_name", "")
        github = rec.get("github", "")
        
        if not github:
            raise HTTPException(400, "GitHub username not found for student")
    except Exception as e:
        raise HTTPException(500, f"Registration error: {str(e)}")
    
    name_parts = student_name.split()
    if len(name_parts) >= 2:
        surname = name_parts[0]
        name = name_parts[1]
        patronymic = name_parts[2] if len(name_parts) >= 3 else ""
    else:
        surname = student_name
        name = ""
        patronymic = ""
    
    registration_data = {
        "surname": surname,
        "name": name,
        "patronymic": patronymic,
        "github": github
    }
    
    files = sorted([f for f in os.listdir(COURSES_DIR) if f.endswith(".yaml")])
    try:
        filename = files[int(course_id) - 1]
    except (IndexError, ValueError):
        raise HTTPException(status_code=404, detail="Course not found")

    file_path = os.path.join(COURSES_DIR, filename)
    with open(file_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
        course_info = data.get("course", {})
        spreadsheet_id = course_info.get("google", {}).get("spreadsheet")

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Spreadsheet ID not found")

    course_client = gspread.authorize(creds)
    course_spreadsheet = course_client.open_by_key(spreadsheet_id)
    
    course_name = filename.replace(".yaml", "")
    sheet_name = f"{group_id}_{course_name}"
    
    try:
        group_ws = course_spreadsheet.worksheet(sheet_name)
    except:
        raise HTTPException(status_code=404, detail=f"Group sheet {sheet_name} not found")

    all_records = group_ws.get_all_records()
    
    existing_student = None
    for i, record in enumerate(all_records):
        student_col_value = str(record.get("Студент", "")).strip()
        if student_col_value.lower() == student_name.lower():
            existing_student = (i + 3, record)
            break

    if existing_student:
        row_num, existing_record = existing_student
        existing_github = str(existing_record.get("GitHub", "")).strip()
        
        if existing_github and existing_github != github:
            return {"status": "conflict", "message": "Student registered with different GitHub"}
        elif not existing_github:
            group_ws.update_cell(row_num, 3, github)
        
        group_ws.update_cell(row_num, 1, str(chat_id))
        
        return {"status": "updated" if not existing_github else "already_registered", "github": github}
    else:
        next_row = len(all_records) + 2
        group_ws.update_cell(next_row, 1, str(chat_id))
        group_ws.update_cell(next_row, 2, student_name)
        group_ws.update_cell(next_row, 3, github)
        
        return {"status": "registered", "github": github}

@app.get("/student-group/{chat_id}")
def get_student_group(chat_id: int):
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE)
    client = gspread.authorize(creds)
    ws = client.open_by_key(SPREADSHEET_ID).worksheet(CODES_SHEET)

    rec = next(
        (r for r in ws.get_all_records()
         if str(r.get("tg_chat_id")) == str(chat_id)),
        None,
    )
    if rec is None:
        raise HTTPException(404, "Student not found")

    return {"group": rec.get("group"), "student_name": rec.get("student_name")}