import sys
from pathlib import Path
from uuid import uuid4

from loguru import logger
from telebot import TeleBot


class TelegramHandler:
    def __init__(self, token: str, chat_id: int):
        self.bot = TeleBot(token=token)
        self.chat_id = chat_id
        self.session = str(uuid4()).replace('-', '')
        self.bot.send_message(
            chat_id=self.chat_id,
            text=f'Starting session with ID #{self.session}'
        )

    def emit(self, log_message: str) -> None:
        log_entry = f'#{self.session}\n{log_message}'

        self.bot.send_message(
            chat_id=self.chat_id,
            text=log_entry,
            disable_web_page_preview=True
        )


fmt = '<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>'

logger.remove()

logger.add(
    sink=sys.stderr,
    format=fmt,
    colorize=True
)

logger.add(
    Path(__file__).parents[1] / 'logs' / 'scroll_canvas.log',
    rotation='1 day',
    format=fmt
)
