import asyncio
from src.music.ytdl_source import YTDLSource
from src.music.tts_queue import TTSQueue


class BotHelper:
    def __init__(self, bot):
        self.bot = bot
        self.tts_queue = None
        self.current_music_source = None
        self.current_sfx_source = None

    def set_vc(self, voice_client):
        if voice_client is None:
            self.bot.vc = None
            self.bot.source_queue = None
            return

        self.bot.vc = voice_client
        self.tts_queue = TTSQueue(voice_client, self.bot)
        self.current_music_source = None

    def decrease_volume(self):
        if self.bot.vc:
            self.bot.vc.source.volume -= 0.2

    def increase_volume(self):
        if self.bot.vc:
            self.bot.vc.source.volume += 0.2

    def set_volume(self, value):
        value = value / 10
        if self.bot.vc:
            self.bot.vc.source.volume = value

    async def send_message(self, channel_id, content, embed=None, tts=False):
        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(content=content, embed=embed, tts=tts)
        else:
            print(f"Channel with ID {channel_id} not found.")

    def music_stopped_callback(self, error):
        if error:
            print(f'YTDL Player error: {error}')
        else:
            self.current_music_source = None

    async def play_youtube(self, video_url):
        if self.current_music_source:
            self.bot.vc.stop()

        self.current_music_source = await YTDLSource.from_url(video_url, loop=self.bot.loop, stream=True)
        self.bot.vc.play(self.current_music_source,
                         after=self.music_stopped_callback)

    async def play_sfx(self, sfx_url, sfx_duration=5):
        old_source = self.bot.vc.source if self.bot.vc.is_playing() else None

        if self.bot.vc.is_playing():
            self.bot.vc.pause()

        if sfx_duration > 0:
            timeout_task = asyncio.create_task(
                stop_playback_after_timeout(sfx_duration))

        # Load and play the SFX
        self.current_sfx_source = await YTDLSource.from_url(sfx_url, loop=self.bot.loop, stream=True)
        self.bot.vc.play(self.current_sfx_source,
                         after=lambda e: sfx_stopped_callback(e, old_source, timeout_task))

        def sfx_stopped_callback(error, old_source, timeout_task=None):
            if error:
                print(f'SFX Player error: {error}')
            else:
                if timeout_task:
                    timeout_task.cancel()

                self.current_sfx_source = None
                if old_source:
                    self.bot.vc.play(
                        old_source, after=self.music_stopped_callback)

        async def stop_playback_after_timeout(duration):
            await asyncio.sleep(duration)
            if self.current_sfx_source:
                if self.bot.vc.is_playing():
                    self.bot.vc.stop()

    async def play_tts(self, tts_url):
        tts_source = await YTDLSource.from_url(tts_url, loop=self.bot.loop, stream=True)
        if self.tts_queue:
            await self.tts_queue.add_tts(tts_source)

    async def _handle_play_node(self, node):
        await self.play_youtube(node["data"]["video_url"])

    async def _handle_post_node(self, node, discord_channel_id):
        await self.send_message(discord_channel_id, node["data"]["text"])

    async def _handle_tts_node(self, node):
        await self.play_tts(node["data"]["tts_url"])

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
                print(f"Could not parse volume value: {value}")
                return

    async def _handle_music_control_node(self, node):
        action = node["data"]["action"]
        action = action.lower()

        if action == "stop":
            if self.bot.vc.is_playing():
                self.bot.vc.stop()
        elif action == "pause":
            if self.bot.vc.is_playing():
                self.bot.vc.pause()
        elif action == "play":
            if self.bot.vc.is_paused():
                self.bot.vc.resume()
        else:
            print(f"Unknown music control action: {action}")
