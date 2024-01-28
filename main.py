import asyncio
import os
import queue

import discord
from dotenv import load_dotenv

from src.bot.helper import BotHelper
from src.queue.action_consumer import ActionConsumer

load_dotenv()

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID"))


class HeyBillyBot(discord.Bot):
    def __init__(self, loop):
        super().__init__(command_prefix="!", loop=loop)
        self.helper = BotHelper(self)
        self.action_queue = asyncio.Queue()

        self.consumers = [
            ActionConsumer(loop, "output.tts", self.action_queue),
            ActionConsumer(loop, "volume.set", self.action_queue),
            ActionConsumer(loop, "youtube.play", self.action_queue),
            ActionConsumer(loop, "discord.post", self.action_queue),
        ]

    async def start_consumers(self):
        consumer_tasks = [consumer.start_consuming() for consumer in self.consumers]
        await asyncio.gather(*consumer_tasks)

    async def process_actions(self):
        while True:
            action = await self.action_queue.get()
            print("Processing:", action)

    async def on_ready(self):
        print(f"Logged in as {self.user}.")
        await self.start_consumers()
        self.loop.create_task(self.process_actions())

    async def close_connections(self):
        await asyncio.gather(*(consumer.close_connection() for consumer in self.consumers))


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    bot = HeyBillyBot(loop)

    @bot.slash_command(name="connect", description="Connect to your voice channel.")
    async def connect(ctx: discord.context.ApplicationContext):
        author_vc = ctx.author.voice
        if not author_vc:
            await ctx.respond("You are not in a voice channel.", ephemeral=True)
            return

        await ctx.respond("Connecting to your VC.", ephemeral=True)
        bot.vc = await author_vc.channel.connect()
        bot.vc.play(await bot.helper.create_ytdl_source("https://www.youtube.com/watch?v=wvPPDMjuh6Q"))

    @bot.slash_command(name="disconnect", description="Disconnect from your voice channel.")
    async def disconnect(ctx: discord.context.ApplicationContext):
        bot_vc = ctx.voice_client
        if not bot_vc:
            await ctx.respond("I am not in your voice channel.", ephemeral=True)
            return

        await ctx.respond("Disconnecting from VC.", ephemeral=True)
        await bot_vc.disconnect()

    try:
        loop.run_until_complete(bot.start(DISCORD_BOT_TOKEN))
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        # Close all connections
        loop.run_until_complete(bot.close_connections())

        tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))

        # Close the loop
        loop.run_until_complete(bot.close())
        loop.close()