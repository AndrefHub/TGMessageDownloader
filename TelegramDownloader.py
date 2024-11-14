import os
import asyncio
import time
import shutil
from datetime import datetime
from telethon import TelegramClient, events
import logging

import tgutils

logger = logging.getLogger(__name__)


class InternalMessageStatus:
    CREATED = 1
    DOWNLOADING_MEDIA = 2
    READY = 3

    def stringify(status):
        return [0, "CREATED", "DOWNLOADING", "READY"][status]


class InternalMessage:
    required_fields = ["id", "date"]
    optional_fields = ["group_id", "text", "media"]

    def __init__(self, **kwargs):
        for field in InternalMessage.required_fields:
            if field in kwargs:
                setattr(self, field, kwargs[field])
            else:
                raise TypeError(f"Missing required argument: '{field}'")

        for field in InternalMessage.optional_fields:
            if field in kwargs:
                setattr(self, field, kwargs[field])
            else:
                setattr(self, field, None)

        self.update_status(InternalMessageStatus.CREATED)

    def update_status(self, status):
        self.update_time()
        self.status = status
        logger.debug(
            f"Updated status to message {self.id} to {InternalMessageStatus.stringify(self.status)}"
        )

    def update_time(self):
        self.last_update = time.time()

    def __str__(self):
        return f"""InternalMessage(
    id = {self.id},
    date = {self.date},
    group_id = {self.group_id},
    text = {self.text},
    media = {self.media},
    status = {InternalMessageStatus.stringify(self.status)}
)"""


class MessageDownloader:
    def __init__(self, **kwargs):
        self.__set_default_values()
        self._set_fields(**kwargs)
        self.fetching_done = asyncio.Event()

    async def __aenter__(self):
        # Set up resources, e.g., open a connection
        self.connection = await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        # Tear down resources, e.g., close connection
        await self.close_connection()

    required_fields = ["api_id", "api_hash"]
    optional_fields = [
        "url",
        "delete_url",
        "bot_token",
        "phone",
        "image_path",
        "video_path",
        "hashtags",
        "start_date",
        "dry",
    ]

    def __set_required_fields(self, **kwargs):
        for field in MessageDownloader.required_fields:
            if field in kwargs:
                setattr(self, field, kwargs[field])
                logger.debug(f"{self}: Set required field '{field}' to {kwargs[field]}")
            elif not getattr(self, field, None):
                raise TypeError(f"Missing required argument: '{field}'")

    def __set_optional_fields(self, **kwargs):
        for field in MessageDownloader.optional_fields:
            if field in kwargs:
                setattr(self, field, kwargs[field])
                logger.debug(f"{self}: Set optional field '{field}' to {kwargs[field]}")
            elif not getattr(self, field, None):
                setattr(self, field, None)

    def _set_fields(self, **kwargs):
        self.__set_required_fields(**kwargs)
        self.__set_optional_fields(**kwargs)

    def __set_default_values(self):
        self.parsed_messages = []
        self.single_messages = {}
        self.group_messages = {}
        self.ignored_group_ids = []

        self.latest_group_id = None

        self.url = "example.com/api/post"
        self.image_path = "media/images"
        self.video_path = "media/videos"
        self.hashtags = [
            "#срочно",
            "#происшествия",
            "#дтп",
            "#лайфстайл",
            "#спорт",
            "#город",
            "#политика",
            "#развлечения",
            "#18+",
            "#топновости",
        ]

    # Проверка типа медиа (изображение или видео)
    def get_media_type(self, message):
        if message.photo:
            return "image"
        elif message.video or (
            message.document and "video" in message.document.mime_type
        ):
            return "video"
        return None

    def get_media_path_from_type(self, media_type):
        if media_type == "image":
            return self.image_path
        if media_type == "video":
            return self.video_path
        return None

    def __generate_preview_from_video(self, filename):
        name, ext = os.path.splitext(filename)
        preview_filename = f"{name}.jpg"
        tgutils.extract_frame(
            f"{self.video_path}/{filename}", f"{self.image_path}/{preview_filename}"
        )
        return preview_filename

    async def __process_media_to_download(self, message):
        media_temp_path = await message.download_media()
        if not media_temp_path:
            logger.warn(f"Failed to download media for message {message.id}")
            return ""
        media_filename = tgutils.change_filename_preserve_ext(message.id, media_temp_path)
        # Определяем, является ли файл изображением или видео
        media_type = self.get_media_type(message)
        if media_type:
            media_destination = os.path.join(
                self.get_media_path_from_type(media_type), media_filename
            )
            try:
                await asyncio.to_thread(shutil.move, media_temp_path, media_destination)
                logger.info(f"Downloaded media to {media_destination}")

            except Exception as e:
                logger.warn(f"Failed to move media: {e}")
            finally:
                if os.path.exists(media_temp_path):
                    os.remove(media_temp_path)
        return media_filename

    async def _process_media(self, message):
        downloaded_media = tgutils.is_media_downloaded(
            message.id, self.video_path, self.image_path
        )

        if downloaded_media:
            filename = downloaded_media[0].name
            logger.info(f"Skipped downloading {filename}")
        else:
            filename = await self.__process_media_to_download(message)

        media = {
            "filename": filename,
            "spoiler": message.media.spoiler,
        }
        if self.get_media_type(message) == "video":
            media["preview"] = self.__generate_preview_from_video(filename)

        return media

    async def _process_message(self, message):
        group_id = message.grouped_id

        # If message doesn't have text and not in a group
        if not (message.text or group_id):
            return

        # If message has text and no hashtags -> SKIP
        if not tgutils.check_message_text_for_hashtags(message.text, self.hashtags):
            if group_id:
                self.ignored_group_ids.append(group_id)
            logger.info(
                f"No valid hashtags found for message {message.id}. Group ID {group_id} ignored."
            )
            return

        await asyncio.sleep(1)

        if group_id and group_id in self.ignored_group_ids:
            logger.info(f"GroupID {group_id} is likely an ad post.")
            return

        message_date = message.date
        iso_date = message_date.isoformat()

        internal_message = InternalMessage(
            id=message.id,
            group_id=group_id,
            date=iso_date,
            text=message.text,
        )

        if internal_message.group_id:
            if internal_message.group_id in self.group_messages.keys():
                self.group_messages[internal_message.group_id].append(internal_message)
            else:
                self.group_messages[internal_message.group_id] = [internal_message]
        else:
            self.single_messages[internal_message.id] = internal_message

        if message.media:
            internal_message.update_status(InternalMessageStatus.DOWNLOADING_MEDIA)
            internal_message.media = await self._process_media(message)
        internal_message.update_status(InternalMessageStatus.READY)

    # async def _process_message_get_history(self, message):
    #     group_id = message.grouped_id
    #     latest_group_id = self.latest_group_id

    #     if group_id:

    """
    Returns an Iterable with messages ordered from oldest to newest
    """

    async def _get_messages(self, client, channel):
        messages = []

        start_date = datetime.fromisoformat(self.start_date)
        end_date = datetime.now()

        async for message in client.iter_messages(
            channel,
            offset_date=end_date,
            min_id=1,
            limit=None,
        ):
            if message.date.replace(tzinfo=None) < start_date:
                break
            messages.append(message)

        return reversed(messages)

    async def fetch_messages(self, client, channel):
        try:
            messages = await self._get_messages(client, channel)
            logger.info(
                f"Messages up to {self.start_date} are downloaded and ready for processing."
            )

            tasks = []
            for message in messages:
                task = asyncio.create_task(self._process_message(message))
                tasks.append(task)
                # # HACK: создание небольшой задержки для обработки сообщений по порядку
                await asyncio.sleep(0.1)

            if tasks:
                await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"Error fetching messages: {e}")

        finally:
            self.fetching_done.set()

    async def blm_new_message_handler(self, event):
        logger.debug(event)
        if event.message:
            await self._process_message(event.message)

    async def blm_delete_message_handler(self, event):
        logger.info(event)
        # add check for correct channel
        for deleted_id in event.deleted_ids:
            await tgutils.delete_news(self.delete_url, deleted_id)
        
    async def __send_one_message(self, converted_message: dict):
        self.parsed_messages.append(converted_message)
        if not self.dry:
            await tgutils.send_to_api(self.url, converted_message)

    def convert_message_to_json_generator(self, transform: callable):
        return lambda message: tgutils.cleanup_text_in_json(transform(message), self.hashtags)

    async def __send_prepared_messages(
        self, messages: dict, condition: callable, transform: callable
    ):
        keys_to_remove = [key for key in messages if condition(messages[key])]

        for key in keys_to_remove:
            message = messages[key]
            transformed_message = transform(message)
            await self.__send_one_message(transformed_message)
            logger.debug(f"Removing message {key}")
            del messages[key]

    async def __send_messages_cycle(self):
        DELAY_IN_SECONDS = 3

        await self.__send_prepared_messages(
            self.single_messages,
            lambda message: message.status == InternalMessageStatus.READY,
            self.convert_message_to_json_generator(tgutils.convert_message_to_data),
        )

        await self.__send_prepared_messages(
            self.group_messages,
            lambda group: all(
                message.status == InternalMessageStatus.READY
                and message.last_update < time.time() - DELAY_IN_SECONDS
                for message in group
            ),
            self.convert_message_to_json_generator(tgutils.convert_group_to_data),
        )

    async def send_messages(self):
        while not self.fetching_done.is_set():
            await asyncio.sleep(5)
            await self.__send_messages_cycle()

        # ew
        for _ in range(3):
            if not (self.single_messages or self.group_messages):
                break
            await self.__send_messages_cycle()
            await asyncio.sleep(3)

        # EWWWWWWWWWWWW
        await self.__send_prepared_messages(
            self.group_messages,
            lambda group: all(
                message.status == InternalMessageStatus.READY for message in group
            ),
            tgutils.convert_group_to_data,
        )

    def is_all_fields_present(self, *args):
        return all(getattr(self, field, None) for field in args)

    async def get_history(self, channel):
        # required_fields = ['api_id', 'api_hash', 'phone']
        tgutils.create_output_directories(self.image_path, self.video_path)

        client = await TelegramClient(
            f"load_session_{self.api_id}",
            self.api_id,
            self.api_hash,
        ).start(self.phone)

        logger.info("`get_history()` session started and user authorized.")
        tasks = [
            asyncio.create_task(self.fetch_messages(client, channel)),
            asyncio.create_task(self.send_messages()),
        ]
        await asyncio.gather(*tasks)
        await client.disconnect()
        tgutils.write_messages_to_file(self.parsed_messages, f"{channel}.json")

    async def get_new_messages(self, channel):
        tgutils.create_output_directories(self.image_path, self.video_path)

        client = await TelegramClient(
            f"blm_session_{self.api_id}",
            self.api_id,
            self.api_hash,
        ).start(bot_token=self.bot_token)

        # await client(JoinChannelRequest(channel))

        client.add_event_handler(
            self.blm_new_message_handler, events.NewMessage(chats=channel)
        )
        client.add_event_handler(
            self.blm_delete_message_handler, events.MessageDeleted()
        )
        logger.info("`get_new_messages()` session started and user authorized.")
        task = asyncio.create_task(self.send_messages())
        await client.run_until_disconnected()
