# coding=utf-8

from typing import List
import logging
import telegram
from telegram import Update
from telegram.ext.handler import Handler


class WhitelistHandler(Handler):
    """
    Handler class to block users not on white-list.

    Args:
        whitelist (List[int]): A list consist of whitelisted user IDs
            in int.
        pass_update_queue (optional[bool]): If the handler should be passed the
            update queue as a keyword argument called ``update_queue``. It can
            be used to insert updates. Default is ``False``
    """

    def __init__(self, whitelist: List[int], update: telegram.ext.Updater, pass_update_queue: bool=False):
        def void_function(bot, update):
            pass

        self.logger: logging.Logger = logging.getLogger(__name__)
        self.update = update
        self.whitelist = list(map(lambda i: int(i), whitelist))
        super(WhitelistHandler, self).__init__(void_function, pass_update_queue)

    def check_update(self, update):
        if not isinstance(update, Update):
            return False
        if not update.effective_user:
            return True
        if int(update.effective_user.id) in self.whitelist:
            return False

        user = self.update.bot.getChatMember(update.message.chat.id, update.effective_user.id, 5)
        # self.logger.log(99, "Received message from User: %s", user)

        return user.status != 'administrator'

    def handle_update(self, update, dispatcher):
        pass
