import asyncio
import json
import logging
import os

import discord

from src.bot.helper import BotHelper
from src.bot.sinks.whisper_sink import WhisperSink
from src.queue.connect import RabbitConnection
from src.queue.consumer_manager import ConsumerManager
from src.queue.transcript.publisher import TranscriptPublisher
from src.utils.strings import find_wake_word_start

DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

logger = logging.getLogger(__name__)

WAKE_WORDS = ["ok billy", "yo billy", "okay billy", "hey billy"]


async def whisper_message(rabbit_conn, transcript_queue: asyncio.Queue, guild_id: int, bot: discord.Bot):
    transcript_publisher = TranscriptPublisher(rabbit_conn)
    await transcript_publisher.setup_connection()

    while True:
        try:
            response = await transcript_queue.get()

            if response is None:
                break  # Queue is closed
            else:
                user_id = response["user"]
                text = response["result"]

                wake_word_start = find_wake_word_start(WAKE_WORDS, text)
                if wake_word_start == -1:
                    logger.debug(f"No wake word found in: {text}")
                    continue  # No wake word found

                # Slice the line from the first wake word
                # it isn't perfect, but it's good enough
                processed_line = text[wake_word_start:]

                username = bot.get_guild(
                    guild_id).get_member(user_id).global_name
                logger.info(f"User {username} said: {processed_line}")
                await transcript_publisher.publish_transcript(json.dumps({
                    "guild_id": guild_id,
                    "username": username,
                    "text": processed_line,
                }))
        except Exception as e:
            logger.error(f"Error processing whisper message: {e}")


class HeyBillyBot(discord.Bot):
    def __init__(self, loop):
        super().__init__(command_prefix="!", loop=loop)
        self.helper = None
        self.action_queue = asyncio.Queue()
        self.guild_is_recording = {}
        self.guild_whisper_sinks = {}
        self.guild_whisper_message_tasks = {}
        self._is_ready = False

        self.created_queues = {
            "output.tts": None,
            "volume.set": None,
            "discord.post": None,
            "sfx.play": None,
            "music.control": None,
            "request.status": {
                "x-max-length": 10,
            }
        }

    async def process_actions(self):
        while True:
            try:
                action = await self.action_queue.get()
                node_type = action.get("node_type", None)
                logger.debug(f"Processing action: {action}")

                if node_type == "discord.post":
                    await self.helper._handle_post_node(action, DISCORD_CHANNEL_ID)
                elif node_type == "output.tts":
                    await self.helper._handle_tts_node(action)
                elif node_type == "volume.set":
                    self.helper._handle_volume_node(action)
                elif node_type == "sfx.play":
                    await self.helper._handle_sfx_node(action)
                elif node_type == "music.control":
                    await self.helper._handle_music_control_node(action)
                elif action.get("status", None):
                    await self.helper._handle_request_status_update(action)
                else:
                    logger.error(f"Unknown action: {action}")
            except Exception as e:
                logger.error(f"Error processing action: {e}")
                logger.error(f"Action: {action}")

    async def on_ready(self):
        logger.info(f"Logged in as {self.user}.")
        await self.start_consumers()
        self.helper = BotHelper(self)

        self.loop.create_task(self.process_actions())
        self._is_ready = True

    async def on_guild_join(self, guild: discord.Guild):
        try:
            logger.info(f"Joined guild {guild.name}.")
            await self.helper.send_welcome_message(guild)
        except Exception as e:
            logger.error(f"Error welcoming guild: {e}")

    async def start_consumers(self):
        self.rabbit_conn = await RabbitConnection.connect("localhost", self.loop)
        self.consumer_manager = ConsumerManager(self.rabbit_conn, self.loop)

        for queue_name, args in self.created_queues.items():
            logger.debug(f"Creating consumer for queue: {queue_name}")
            await self.consumer_manager.create_consumer(queue_name, self.action_queue, args)

    async def close_consumers(self):
        await self.consumer_manager.close()

    def _close_and_clean_sink_for_guild(self, guild_id: int):
        whisper_sink: WhisperSink | None = self.guild_whisper_sinks.get(
            guild_id, None)

        if whisper_sink:
            logger.debug(f"Stopping whisper sink, requested by {guild_id}.")
            whisper_sink.stop_voice_thread()
            del self.guild_whisper_sinks[guild_id]
            whisper_sink.close()

    def start_recording(self, ctx: discord.context.ApplicationContext):
        """
        Start recording audio from the voice channel. Create a whisper sink
        and start sending transcripts to the queue.
        """
        try:
            guild_voice_sink = self.guild_whisper_sinks.get(ctx.guild_id, None)
            if guild_voice_sink:
                logger.debug(
                    f"Sink is already active for guild {ctx.guild_id}.")
                return

            async def on_stop_record_callback(sink: WhisperSink, ctx):
                logger.debug(
                    f"{ctx.channel.guild.id} -> on_stop_record_callback")
                self._close_and_clean_sink_for_guild(ctx.guild_id)

            transcript_queue = asyncio.Queue()
            t = self.loop.create_task(whisper_message(
                self.rabbit_conn, transcript_queue, ctx.guild_id, self))
            self.guild_whisper_message_tasks[ctx.guild_id] = t

            whisper_sink = WhisperSink(
                transcript_queue,
                self.loop,
                data_length=50000,
                quiet_phrase_timeout=0.5,
                mid_sentence_multiplier=1.2,
                no_data_multiplier=0.15,
                max_phrase_timeout=15,
                min_phrase_length=7,
                max_speakers=10
            )

            self.helper.get_vc().start_recording(
                whisper_sink, on_stop_record_callback, ctx)
            whisper_sink.start_voice_thread()

            self.guild_is_recording[ctx.guild_id] = True
            self.guild_whisper_sinks[ctx.guild_id] = whisper_sink
        except Exception as e:
            logger.error(f"Error starting whisper sink: {e}")

    def stop_recording(self, ctx: discord.context.ApplicationContext):
        vc = ctx.guild.voice_client
        if vc:
            self.guild_is_recording[ctx.guild_id] = False
            vc.stop_recording()

        whisper_message_task = self.guild_whisper_message_tasks.get(
            ctx.guild_id, None)
        if whisper_message_task:
            logger.debug("Cancelling whisper message task.")
            whisper_message_task.cancel()
            del self.guild_whisper_message_tasks[ctx.guild_id]

        self._close_and_clean_sink_for_guild(ctx.guild_id)

    async def stop_and_cleanup(self):
        try:
            for sink in self.guild_whisper_sinks.values():
                sink.close()
                sink.stop_voice_thread()
                logger.debug(
                    f"Stopped whisper sink for guild {sink.vc.channel.guild.id} in cleanup.")
            self.guild_whisper_sinks.clear()
        except Exception as e:
            logger.error(f"Error stopping whisper sinks: {e}")
        finally:
            logger.info("Cleanup completed.")
