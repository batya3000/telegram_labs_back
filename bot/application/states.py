from aiogram.fsm.state import StatesGroup, State


class Auth(StatesGroup):
    waiting_code = State()
    waiting_github = State()

class CourseSelection(StatesGroup):
    waiting_course = State()

class LabSubmission(StatesGroup):
    waiting_lab_selection = State()

class AdminAuth(StatesGroup):
    waiting_admin_code = State()

class AdminPanel(StatesGroup):
    viewing_courses = State()
    viewing_course_yaml = State()
    confirming_delete = State()