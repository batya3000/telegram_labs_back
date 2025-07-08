from aiogram.fsm.state import StatesGroup, State


class Auth(StatesGroup):
    waiting_code = State()

class CourseSelection(StatesGroup):
    waiting_course = State()
    waiting_group = State()
    waiting_lab = State()