# coding=utf-8

import datetime
import logging
from typing import List, Optional

from peewee import Model, TextField, DateTimeField, CharField, SqliteDatabase, DoesNotExist, fn
from playhouse.migrate import SqliteMigrator, migrate

from ehforwarderbot import utils, EFBChannel

database = SqliteDatabase(None)


class BaseModel(Model):
    class Meta:
        database = database


class ChatAssoc(BaseModel):
    master_uid = TextField()
    slave_uid = TextField()


class MsgLog(BaseModel):
    master_msg_id = TextField(unique=True, primary_key=True)
    master_msg_id_alt = TextField(null=True)
    slave_message_id = TextField()
    text = TextField()
    slave_origin_uid = TextField()
    slave_origin_display_name = TextField(null=True)
    slave_member_uid = TextField(null=True)
    slave_member_display_name = TextField(null=True)
    media_type = TextField(null=True)
    mime = TextField(null=True)
    file_id = TextField(null=True)
    msg_type = TextField()
    sent_to = TextField()
    time = DateTimeField(default=datetime.datetime.now, null=True)


class SlaveChatInfo(BaseModel):
    slave_channel_id = TextField()
    slave_channel_emoji = CharField()
    slave_chat_uid = TextField()
    slave_chat_name = TextField()
    slave_chat_alias = TextField(null=True)
    slave_chat_type = CharField()


class DatabaseManager:
    logger = logging.getLogger(__name__)

    def __init__(self, channel: EFBChannel):
        base_path = utils.get_data_path(channel.channel_id)

        database.init(str(base_path / 'tgdata.db'))
        database.connect()

        if not ChatAssoc.table_exists():
            self._create()
        elif "file_id" not in {i.name for i in database.get_columns("MsgLog")}:
            self._migrate(0)

    def _create(self):
        """
        Initializing tables.
        """
        database.execute_sql("PRAGMA journal_mode = OFF")
        database.create_tables([ChatAssoc, MsgLog, SlaveChatInfo])

    def _migrate(self, i):
        """
        Run migrations.

        Args:
            i: Migration ID

        Returns:
            False: when migration ID is not found
        """
        migrator = SqliteMigrator(database)
        if i >= 0:
            # Migration 0: Add media file ID and editable message ID
            # 2019JAN08
            migrate(
                migrator.add_column("msglog", "file_id", MsgLog.file_id),
                migrator.add_column("msglog", "media_type", MsgLog.media_type),
                migrator.add_column("msglog", "mime", MsgLog.mime),
                migrator.add_column("msglog", "master_msg_id_alt", MsgLog.master_msg_id_alt)
            )
        # if i == 0:
        #     # Migration 0: Added Time column in MsgLog table.
        #     # 2016JUN15
        #     migrate(migrator.add_column("msglog", "time", DateTimeField(default=datetime.datetime.now, null=True)))
        # elif i == 1:
        #     # Migration 1:
        #     # Add table: SlaveChatInfo
        #     # 2017FEB25
        #     SlaveChatInfo.create_table()
        #     migrate(migrator.add_column("msglog", "slave_message_id", CharField(default="__none__")))
        #
        # else:
        return False

    def add_chat_assoc(self, master_uid, slave_uid, multiple_slave=False):
        """
        Add chat associations (chat links).
        One Master channel with many Slave channel.

        Args:
            master_uid (str): Master channel UID ("%(chat_id)s")
            slave_uid (str): Slave channel UID ("%(channel_id)s.%(chat_id)s")
            multiple_slave: Allow linking to multiple slave channels.
        """
        if not multiple_slave:
            self.remove_chat_assoc(master_uid=master_uid)
        self.remove_chat_assoc(slave_uid=slave_uid)
        return ChatAssoc.create(master_uid=master_uid, slave_uid=slave_uid)

    def remove_chat_assoc(self, master_uid=None, slave_uid=None):
        """
        Remove chat associations (chat links).
        Only one parameter is to be provided.

        Args:
            master_uid (str): Master channel UID ("%(chat_id)s")
            slave_uid (str): Slave channel UID ("%(channel_id)s.%(chat_id)s")
        """
        try:
            if bool(master_uid) == bool(slave_uid):
                raise ValueError("Only one parameter is to be provided.")
            elif master_uid:
                return ChatAssoc.delete().where(ChatAssoc.master_uid == master_uid).execute()
            elif slave_uid:
                return ChatAssoc.delete().where(ChatAssoc.slave_uid == slave_uid).execute()
        except DoesNotExist:
            return 0

    def get_chat_assoc(self, master_uid: str = None, slave_uid: str = None) -> List[str]:
        """
        Get chat association (chat link) information.
        Only one parameter is to be provided.

        Args:
            master_uid (str): Master channel UID ("%(chat_id)s")
            slave_uid (str): Slave channel UID ("%(channel_id)s.%(chat_id)s")

        Returns:
            list: The counterpart ID.
        """
        try:
            if bool(master_uid) == bool(slave_uid):
                raise ValueError("Only one parameter is to be provided.")
            elif master_uid:
                slaves = ChatAssoc.select().where(ChatAssoc.master_uid == master_uid)
                if len(slaves) > 0:
                    return [i.slave_uid for i in slaves]
                else:
                    return []
            elif slave_uid:
                masters = ChatAssoc.select().where(ChatAssoc.slave_uid == slave_uid)
                if len(masters) > 0:
                    return [i.master_uid for i in masters]
                else:
                    return []
            else:
                return []
        except DoesNotExist:
            return []

    def get_last_msg_from_chat(self, chat_id):
        """Get last message from the selected chat from Telegram

        Args:
            chat_id (int|str): Telegram chat ID

        Returns:
            MsgLog: The last message from the chat
        """
        try:
            return MsgLog.select().where(MsgLog.master_msg_id.startswith("%s." % chat_id)).order_by(
                MsgLog.time.desc()).first()
        except DoesNotExist:
            return None

    def add_msg_log(self, **kwargs):
        """
        Add an entry to message log.

        Display name is defined as `alias or name`.

        Args:
            master_msg_id (str): Telegram message ID ("%(chat_id)s.%(msg_id)s")
            text (str): String representation of the message
            slave_origin_uid (str): Slave chat ID ("%(channel_id)s.%(chat_id)s")
            msg_type (str): String of the message type.
            sent_to (str): "master" or "slave"
            slave_origin_display_name (str): Display name of slave chat.
            slave_member_uid (str|None):
                User ID of the slave chat member (sender of the message, for group chat only).
                ("%(channel_id)s.%(chat_id)s"), None if not available.
            slave_member_display_name (str|None):
                Display name of the member, None if not available.
            update (bool): Update a previous record. Default: False.
            slave_message_id (str): the corresponding message uid from slave channel.

        Returns:
            MsgLog: The added/updated entry.
        """
        master_msg_id = kwargs.get('master_msg_id')
        text = kwargs.get('text')
        slave_origin_uid = kwargs.get('slave_origin_uid')
        msg_type = kwargs.get('msg_type')
        sent_to = kwargs.get('sent_to')
        slave_origin_display_name = kwargs.get('slave_origin_display_name', None)
        slave_member_uid = kwargs.get('slave_member_uid', None)
        slave_member_display_name = kwargs.get('slave_member_display_name', None)
        slave_message_id = kwargs.get('slave_message_id')
        master_msg_id_alt = kwargs.get('master_msg_id_alt', None)
        media_type = kwargs.get('media_type', None)
        file_id = kwargs.get('file_id', None)
        mime = kwargs.get('mime', None)
        update = kwargs.get('update', False)
        if not slave_message_id:
            self.logger.debug("slave_message_id is None. DONOT add to msg log [%s]", kwargs)
            return
        if update:
            msg_log = MsgLog.get(MsgLog.master_msg_id == master_msg_id)
            msg_log.text = text or msg_log.text
            msg_log.msg_type = msg_type or msg_log.msg_type
            msg_log.sent_to = sent_to or msg_log.sent_to
            msg_log.slave_origin_uid = slave_origin_uid or msg_log.slave_origin_uid
            msg_log.slave_origin_display_name = slave_origin_display_name or msg_log.slave_origin_display_name
            msg_log.slave_member_uid = slave_member_uid or msg_log.slave_member_uid
            msg_log.slave_member_display_name = slave_member_display_name or msg_log.slave_member_display_name
            msg_log.slave_message_id = slave_message_id or msg_log.slave_message_id
            msg_log.master_msg_id_alt = master_msg_id_alt
            msg_log.media_type = media_type or msg_log.media_type
            msg_log.file_id = file_id or msg_log.file_id
            msg_log.mime = mime or msg_log.mime
            msg_log.save()
            return msg_log
        else:
            return MsgLog.create(master_msg_id=master_msg_id,
                                      slave_message_id=slave_message_id,
                                      text=text,
                                      slave_origin_uid=slave_origin_uid,
                                      msg_type=msg_type,
                                      sent_to=sent_to,
                                      slave_origin_display_name=slave_origin_display_name,
                                      slave_member_uid=slave_member_uid,
                                      slave_member_display_name=slave_member_display_name,
                                      master_msg_id_alt=master_msg_id_alt,
                                      media_type=media_type,
                                      file_id=file_id,
                                      mime=mime
                                      )

    def get_msg_log(self,
                    master_msg_id: Optional[str] = None,
                    slave_msg_id: Optional[str] = None,
                    slave_origin_uid: Optional[str] = None) -> Optional['MsgLog']:
        """Get message log by message ID.

        Args:
            master_msg_id: Telegram message ID in string
            slave_msg_id: Slave message identifier in string
            slave_origin_uid: Slave chat identifier in string

        Returns:
            MsgLog|None: The queried entry, None if not exist.
        """
        if (master_msg_id and (slave_msg_id or slave_origin_uid)) \
                or not (master_msg_id or (slave_msg_id or slave_origin_uid)):
            raise ValueError('master_msg_id and slave_msg_id is mutual exclusive')
        if not master_msg_id and not (slave_msg_id and slave_origin_uid):
            raise ValueError('slave_msg_id and slave_origin_uid must exists together.')
        try:
            if master_msg_id:
                return MsgLog.select().where(MsgLog.master_msg_id == master_msg_id) \
                    .order_by(MsgLog.time.desc()).first()
            else:
                return MsgLog.select().where((MsgLog.slave_message_id == slave_msg_id) &
                                                  (MsgLog.slave_origin_uid == slave_origin_uid)
                                                  ).order_by(MsgLog.time.desc()).first()
        except DoesNotExist:
            return None

    def delete_msg_log(self,
                       master_msg_id: Optional[str] = None,
                       slave_msg_id: Optional[str] = None,
                       slave_origin_uid: Optional[str] = None):
        """Remove a message log by message ID.

        Args:
            master_msg_id: Telegram message ID in string
            slave_msg_id: Slave message identifier in string
            slave_origin_uid: Slave chat identifier in string
        """
        if (master_msg_id and (slave_msg_id or slave_origin_uid)) \
                or not (master_msg_id or (slave_msg_id or slave_origin_uid)):
            raise ValueError('master_msg_id and slave_msg_id is mutual exclusive')
        if not master_msg_id and not (slave_msg_id and slave_origin_uid):
            raise ValueError('slave_msg_id and slave_origin_uid must exists together.')
        try:
            if master_msg_id:
                MsgLog.delete().where(MsgLog.master_msg_id == master_msg_id).execute()
            else:
                MsgLog.delete().where((MsgLog.slave_message_id == slave_msg_id) &
                                           (MsgLog.slave_origin_uid == slave_origin_uid)
                                           ).execute()
        except DoesNotExist:
            return

    def get_slave_chat_info(self, slave_channel_id=None, slave_chat_uid=None) -> Optional['SlaveChatInfo']:
        """
        Get cached slave chat info from database.

        Returns:
            SlaveChatInfo|None: The matching slave chat info, None if not exist.
        """
        if slave_channel_id is None or slave_chat_uid is None:
            raise ValueError("Both slave_channel_id and slave_chat_id should be provided.")
        try:
            return SlaveChatInfo.select()\
                .where((SlaveChatInfo.slave_channel_id == slave_channel_id) &
                       (SlaveChatInfo.slave_chat_uid == slave_chat_uid)).first()
        except DoesNotExist:
            return None

    def set_slave_chat_info(self,
                            slave_channel_id=None,
                            slave_channel_name=None,
                            slave_channel_emoji=None,
                            slave_chat_uid=None,
                            slave_chat_name=None,
                            slave_chat_alias="",
                            slave_chat_type=None):
        """
        Insert or update slave chat info entry

        Args:
            slave_channel_id (str): Slave channel ID
            slave_channel_name (str): Slave channel name
            slave_channel_emoji (str): Slave channel emoji
            slave_chat_uid (str): Slave chat UID
            slave_chat_name (str): Slave chat name
            slave_chat_alias (str): Slave chat alias, "" (empty string) if not available
            slave_chat_type (channel.ChatType): Slave chat type

        Returns:
            SlaveChatInfo: The inserted or updated row
        """
        if self.get_slave_chat_info(slave_channel_id=slave_channel_id, slave_chat_uid=slave_chat_uid):
            chat_info = SlaveChatInfo.get(SlaveChatInfo.slave_channel_id == slave_channel_id,
                                               SlaveChatInfo.slave_chat_uid == slave_chat_uid)
            chat_info.slave_channel_name = slave_channel_name
            chat_info.slave_channel_emoji = slave_channel_emoji
            chat_info.slave_chat_name = slave_chat_name
            chat_info.slave_chat_alias = slave_chat_alias
            chat_info.slave_chat_type = slave_chat_type.value
            chat_info.save()
            return chat_info
        else:
            return SlaveChatInfo.create(slave_channel_id=slave_channel_id,
                                             slave_channel_name=slave_channel_name,
                                             slave_channel_emoji=slave_channel_emoji,
                                             slave_chat_uid=slave_chat_uid,
                                             slave_chat_name=slave_chat_name,
                                             slave_chat_alias=slave_chat_alias,
                                             slave_chat_type=slave_chat_type.value)

    def delete_slave_chat_info(self, slave_channel_id, slave_chat_uid):
        return SlaveChatInfo.delete()\
            .where((SlaveChatInfo.slave_channel_id == slave_channel_id) &
                   (SlaveChatInfo.slave_chat_uid == slave_chat_uid)).execute()

    @staticmethod
    def get_recent_slave_chats(master_chat_id, limit=5):
        query = MsgLog\
            .select(MsgLog.slave_origin_uid, fn.MAX(MsgLog.time)) \
            .where(MsgLog.master_msg_id.startswith("{}.".format(master_chat_id))) \
            .group_by(MsgLog.slave_origin_uid) \
            .order_by(fn.MAX(MsgLog.time).desc()) \
            .limit(limit)

        return [i.slave_origin_uid for i in query]
