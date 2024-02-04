import asyncio
import json
import logging
import os

import discord
from dotenv import load_dotenv

from src.bot.helper import BotHelper
from src.bot.sinks.whisper_sink import WhisperSink
from src.config.cliargs import CLIArgs
from src.queue.connect import RabbitConnection
from src.queue.consumer_manager import ConsumerManager
from src.queue.transcript.publisher import TranscriptPublisher
from src.utils.commandline import CommandLine

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))

logger = logging.getLogger(__name__)


async def whisper_message(rabbit_conn, transcript_queue: asyncio.Queue, guild_id: int, bot: discord.Bot):
    transcript_publisher = TranscriptPublisher(rabbit_conn)
    await transcript_publisher.setup_connection()
    while True:
        try:
            response = await transcript_queue.get()

            if response is None:
                break
            else:
                user_id = response["user"]
                text = response["result"]

                username = bot.get_guild(
                    guild_id).get_member(user_id).global_name
                logger.info(f"User {username} said: {text}")
                await transcript_publisher.publish_transcript(json.dumps({
                    "user_id": user_id,
                    "username": username,
                    "text": text,
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
        self.rabbit_conn = None

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

    async def start_consumers(self):
        self.rabbit_conn = await RabbitConnection.connect("localhost", loop)
        self.consumer_manager = ConsumerManager(self.rabbit_conn, loop)

        for queue_name, args in self.created_queues.items():
            await self.consumer_manager.create_consumer(queue_name, self.action_queue, args)

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
            t = loop.create_task(whisper_message(
                self.rabbit_conn, transcript_queue, ctx.guild_id, self))
            self.guild_whisper_message_tasks[ctx.guild_id] = t

            whisper_sink = WhisperSink(
                transcript_queue,
                loop,
                data_length=50000,
                quiet_phrase_timeout=1.25,
                mid_sentence_multiplier=1.75,
                no_data_multiplier=0.75,
                max_phrase_timeout=20,
                min_phrase_length=3,
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


def configure_logging():
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('aiormq').setLevel(logging.ERROR)
    logging.getLogger('aio_pika').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logging.getLogger('faster_whisper').setLevel(logging.WARNING)

    if CLIArgs.verbose:
        logging.basicConfig(level=logging.DEBUG,
                            format='%(name)s: %(message)s')

    else:
        logging.basicConfig(level=logging.INFO,
                            format='%(name)s: %(message)s')


if __name__ == "__main__":
    args = CommandLine.read_command_line()
    CLIArgs.update_from_args(args)

    configure_logging()

    loop = asyncio.get_event_loop()
    bot = HeyBillyBot(loop)

    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus("opus")
        except OSError:
            discord.opus.load_opus("/opt/homebrew/lib/libopus.dylib")
        except Exception as e:
            logger.error(f"Error loading opus library: {e}")
            raise e

    @bot.event
    async def on_voice_state_update(member, before, after):
        if member.id == bot.user.id:
            if after.channel is None:
                bot.helper.guild_id = None
                bot.helper.set_vc(None)

                bot._close_and_clean_sink_for_guild(before.channel.guild.id)

    @bot.slash_command(name="connect", description="Connect to your voice channel.")
    async def connect(ctx: discord.context.ApplicationContext):
        author_vc = ctx.author.voice
        if not author_vc:
            await ctx.respond("You are not in a voice channel.", ephemeral=True)
            return

        await ctx.trigger_typing()
        try:
            vc = await author_vc.channel.connect()
            bot.helper.guild_id = ctx.guild_id
            bot.helper.set_vc(vc)
            await ctx.respond(f"Connected to {author_vc.channel.name}.", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"{e}", ephemeral=True)

        bot.start_recording(ctx)

    @bot.slash_command(name="disconnect", description="Disconnect from your voice channel.")
    async def disconnect(ctx: discord.context.ApplicationContext):
        bot_vc = bot.helper.get_vc(ctx)
        if not bot_vc:
            await ctx.respond("I am not in your voice channel.", ephemeral=True)
            return

        await ctx.trigger_typing()
        if bot.guild_is_recording.get(ctx.guild_id, False):
            bot.stop_recording(ctx)

        await bot_vc.disconnect()
        bot.helper.guild_id = None
        bot.helper.set_vc(None)
        await ctx.respond("Disconnected from VC.", ephemeral=True)

    @bot.slash_command(name="resume", description="Resume music playback.")
    async def resume(ctx: discord.context.ApplicationContext):
        if bot.helper.resume_music():
            await ctx.respond("Resuming music.", ephemeral=True)
        else:
            await ctx.respond("No music to resume.", ephemeral=True)

    @bot.slash_command(name="pause", description="Pause music playback.")
    async def pause(ctx: discord.context.ApplicationContext):
        if bot.helper.pause_music():
            await ctx.respond("Pausing music.", ephemeral=True)
        else:
            await ctx.respond("No music is playing.", ephemeral=True)

    @bot.slash_command(name="stop", description="Stop music playback.")
    async def stop(ctx: discord.context.ApplicationContext):
        if bot.helper.stop_music():
            await ctx.respond("Stopping music.", ephemeral=True)
        else:
            await ctx.respond("No music is playing.", ephemeral=True)

    @bot.slash_command(name="volume", description="Set the volume.")
    async def volume(ctx: discord.context.ApplicationContext, value: int):
        bot.helper.set_volume(value)
        await ctx.respond(f"Volume set to {value}.", ephemeral=True)

    try:
        loop.run_until_complete(bot.start(DISCORD_BOT_TOKEN))
    except KeyboardInterrupt:
        logger.info("^C received, shutting down...")
        asyncio.run(bot.stop_and_cleanup())
    finally:
        # Close all connections
        loop.run_until_complete(bot.close_consumers())

        tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))

        # Close the loop
        loop.run_until_complete(bot.close())
        loop.close()
