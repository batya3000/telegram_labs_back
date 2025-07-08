from aiogram.fsm.state import StatesGroup, State


class Auth(StatesGroup):
    waiting_code = State()