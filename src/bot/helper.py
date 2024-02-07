import asyncio
from base64 import b64decode
import io
import logging
import discord
from src.music.ytdl_source import YTDLSource
from src.music.tts_queue import TTSQueue
from src.utils.tts_voice_map import TTS_VOICE_MAP
from supabase import Client

BOT_NAME = "HeyBilly 💤"
BOT_AWAKE_NAME = "HeyBilly 💬"
BOT_PROCESSING_NAME = "HeyBilly 💡"

logger = logging.getLogger(__name__)


class BotHelper:
    def __init__(self, bot):
        self.bot = bot
        self.supabase: Client = self.bot.supabase
        self.guild_id = None

        self.tts_queue = None
        self.current_music_source = None
        self.current_music_source_url = None
        self.current_sfx_source = None
        self.user_music_volume = 0.5

        self.voice = None

        self.vc = None

    def set_vc(self, voice_client):
        self.vc = voice_client
        if voice_client is None:
            self.tts_queue = None
            self.current_music_source = None
            self.current_sfx_source = None
            logger.debug(
                "Voice client set to None. Clearing tts queue and current music source.")
            return

        self.tts_queue = TTSQueue(voice_client, self)
        self.current_music_source = None

    def decrease_volume(self):
        if self.vc:
            self.vc.source.volume -= 0.2

    def increase_volume(self):
        if self.vc:
            self.vc.source.volume += 0.2

    def set_volume(self, value):
        value = max(0, min(10, value))
        value = value / 10
        self.user_music_volume = value

        if self.vc:
            self.vc.source.volume = value

    async def send_message(self, channel_id, content, embed=None, tts=False):
        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(content=content, embed=embed, tts=tts)
        else:
            logger.error(f"Channel with ID {channel_id} not found.")

    def music_stopped_callback(self, error):
        if error:
            logger.error(f'YTDL Player error: {error}')
        else:
            self.current_music_source = None

    async def play_youtube(self, video_url):
        if self.current_music_source and self.vc.is_playing():
            self.vc.stop()

        self.current_music_source = await YTDLSource.from_url(video_url, loop=self.bot.loop, stream=True)
        self.vc.play(self.current_music_source,
                     after=self.music_stopped_callback)
        self.current_music_source_url = video_url
        self.vc.source.volume = self.user_music_volume

    async def play_sfx(self, sfx_url, sfx_duration=5):
        old_source = self.vc.source if self.vc.is_playing() else None

        if self.vc.is_playing():
            self.vc.pause()

        async def stop_playback_after_timeout(duration):
            await asyncio.sleep(duration)
            if self.current_sfx_source:
                if self.vc.is_playing():
                    self.vc.stop()

        if sfx_duration > 0:
            timeout_task = asyncio.create_task(
                stop_playback_after_timeout(sfx_duration))

        # Load and play the SFX
        self.current_sfx_source = await YTDLSource.from_url(sfx_url, loop=self.bot.loop, stream=True)
        self.vc.play(self.current_sfx_source,
                     after=lambda e: sfx_stopped_callback(e, old_source, timeout_task))
        self.vc.source.volume = self.user_music_volume

        def sfx_stopped_callback(error, old_source, timeout_task=None):
            if error:
                logger.error(f'SFX Player error: {error}')
            else:
                if timeout_task:
                    timeout_task.cancel()

                self.current_sfx_source = None
                if old_source:
                    self.vc.play(
                        old_source, after=self.music_stopped_callback)
                    self.vc.source.volume = self.user_music_volume

    async def play_tts(self, tts_url):
        tts_source = await YTDLSource.from_url(tts_url, loop=self.bot.loop, stream=True)
        if self.tts_queue:
            await self.tts_queue.add_tts(tts_source)

    async def play_data(self, data):
        if self.tts_queue:
            b64decoded = b64decode(data)
            source = discord.FFmpegPCMAudio(io.BytesIO(b64decoded), pipe=True)
            await self.tts_queue.add_tts(source)

    def resume_music(self) -> bool:
        if self.current_music_source and self.vc.is_paused():
            self.vc.resume()
            return True
        return False

    def pause_music(self) -> bool:
        if self.current_music_source and self.vc.is_playing():
            self.vc.pause()
            return True
        return False

    def stop_music(self) -> bool:
        if self.current_music_source and self.vc.is_playing():
            self.vc.stop()
            self.current_music_source = None
            self.current_music_source_url = None
            return True
        return False

    def set_voice(self, new_voice_id: str):
        self.voice = new_voice_id
        res = self.supabase.table("guild_settings").update(
            {"voice": new_voice_id}).eq("guild_id", self.guild_id).execute()
        if hasattr(res, "error"):
            logger.error(f"Error setting voice: {res.error}")
        else:
            logger.debug(
                f"Voice in DB set to {new_voice_id} for guild {self.guild_id}.")

    async def _handle_post_node(self, node, discord_channel_id):
        await self.send_message(discord_channel_id, node["data"]["text"])

    async def _handle_tts_node(self, node):
        tts_url = node["data"].get("tts_url", None)
        tts_data = node["data"].get("tts_data", None)
        if tts_url:
            await self.play_tts(node["data"]["tts_url"])
        elif tts_data:
            await self.play_data(node["data"]["tts_data"])
        else:
            logger.error("No TTS data found in TTS node.")

    async def _handle_sfx_node(self, node):
        await self.play_sfx(node["data"]["video_url"])

    def _handle_volume_node(self, node):
        value = node["data"]["value"]
        if "+" in value:
            self.increase_volume()
        elif "-" in value:
            self.decrease_volume()
        else:
            try:
                value = int(value)
                self.set_volume(value)
            except ValueError:
                logger.error(f"Could not parse volume value: {value}")
                return

    async def _handle_music_control_node(self, node):
        action = node["data"]["action"]
        action = action.lower()

        if action == "start":
            await self.play_youtube(node["data"]["video_url"])
        elif action == "stop":
            self.stop_music()
        elif action == "pause":
            self.pause_music()
        elif action == "resume":
            self.resume_music()
        else:
            logger.error(f"Unknown music control action: {action}")

    async def _handle_request_status_update(self, update):
        if self.guild_id is None:
            return

        try:
            status = update["status"]
            if status == "awake":
                await self.bot.get_guild(self.guild_id).get_member(self.bot.user.id).edit(nick=BOT_AWAKE_NAME)
            elif status == "processing":
                await self.bot.get_guild(self.guild_id).get_member(self.bot.user.id).edit(nick=BOT_PROCESSING_NAME)
            elif status == "completed":
                await self.bot.get_guild(self.guild_id).get_member(self.bot.user.id).edit(nick=BOT_NAME)
        except Exception as e:
            logger.error(f"Error updating status: {e}")
            logger.error(f"Data: {update}")
