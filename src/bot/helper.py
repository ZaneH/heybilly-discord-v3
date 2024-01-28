from src.music.ytdl_source import YTDLSource


class BotHelper:
    def __init__(self, bot):
        self.bot = bot

    async def send_message(self, channel_id, content, embed=None, tts=False):
        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(content=content, embed=embed, tts=tts)
        else:
            print(f"Channel with ID {channel_id} not found.")

    async def create_ytdl_source(self, video_url, add_yt_prefix=False):
        if add_yt_prefix:
            video_url = f"https://www.youtube.com/watch?v={video_url}"

        return await YTDLSource.from_url(video_url, loop=self.bot.loop, stream=True)

    async def play_audio(self, video_id):
        voice_channel = self.bot.vc
        ytdl_source = await self.create_ytdl_source(video_id, True)
        voice_channel.play(ytdl_source)