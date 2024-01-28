import asyncio


class TTSQueue:
    def __init__(self, voice_client, bot):
        self.voice_client = voice_client
        self.bot = bot
        self.tts_sources = asyncio.Queue()
        self.is_playing_tts = False
        self.paused_music_source = None

    async def add_tts(self, tts_source):
        await self.tts_sources.put(tts_source)
        if not self.is_playing_tts:
            await self.play_next_tts()

    async def play_next_tts(self):
        if self.is_playing_tts:
            return

        self.is_playing_tts = True
        if self.voice_client.is_playing() and self.bot.helper.current_music_source:
            # Pause the music and store the current music source
            self.voice_client.pause()
            self.paused_music_source = self.bot.helper.current_music_source

        while not self.tts_sources.empty():
            tts_source = await self.tts_sources.get()

            self.voice_client.play(tts_source, after=self.after_callback)
            await self.wait_for_source_to_finish()

        if self.paused_music_source:
            # Resume the paused music source
            self.voice_client.play(self.paused_music_source, after=self.bot.helper.after_play_callback)
            self.paused_music_source = None

        self.is_playing_tts = False

    async def wait_for_source_to_finish(self):
        while self.voice_client.is_playing():
            await asyncio.sleep(0.1)

    def after_callback(self, error):
        if error:
            print(f'TTS Player error: {error}')
