from aiogram.fsm.state import StatesGroup, State


class Auth(StatesGroup):
    waiting_code = State()

class CourseSelection(StatesGroup):
    waiting_course = State()

class LabSubmission(StatesGroup):
    waiting_lab_selection = State()