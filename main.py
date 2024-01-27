import os
import queue
import threading

import discord
from dotenv import load_dotenv

from src.queue.consumer import ActionConsumer

load_dotenv()

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID")


class HeyBillyBot(discord.Bot):
    def __init__(self):
        super().__init__(command_prefix="!")
        self.action_queue = queue.Queue()  # Queue for incoming actions

        # Create consumer for each action queue
        self.queues = ["output.tts", "youtube.play",
                       "volume.set", "discord.post"]
        self.consumers = [ActionConsumer(self, queue_name=q)
                          for q in self.queues]
        self.consumer_threads = [threading.Thread(
            target=c.consume, daemon=True) for c in self.consumers]

    async def process_actions(self):
        while True:
            action_json = await self.loop.run_in_executor(None, self.action_queue.get)
            if action_json['node_type'] == 'output.tts':
                print(f"Received TTS output: {action_json['data']['tts_url']}")
            elif action_json['node_type'] == 'youtube.play':
                print(
                    f"Received YouTube play: {action_json['data']['video_id']}")
            elif action_json['node_type'] == 'volume.set':
                print(f"Received volume set: {action_json['data']['value']}")
            elif action_json['node_type'] == 'discord.post':
                print(
                    f"Received Discord post: {action_json['data']['text']}")

    async def on_ready(self):
        print(f"Logged in as {self.user}.")
        for thread in self.consumer_threads:
            thread.start()

        self.loop.create_task(self.process_actions())


if __name__ == "__main__":
    bot = HeyBillyBot()

    @bot.slash_command(name="connect", description="Connect to your voice channel.")
    async def connect(ctx: discord.context.ApplicationContext):
        author_vc = ctx.author.voice
        if not author_vc:
            await ctx.respond("You are not in a voice channel.", ephemeral=True)
            return

        await ctx.respond("Connecting to your VC.", ephemeral=True)
        await author_vc.channel.connect()

    @bot.slash_command(name="disconnect", description="Disconnect from your voice channel.")
    async def disconnect(ctx: discord.context.ApplicationContext):
        bot_vc = ctx.voice_client
        if not bot_vc:
            await ctx.respond("I am not in a voice channel.", ephemeral=True)
            return

        await ctx.respond("Disconnecting from VC.", ephemeral=True)
        await bot_vc.disconnect()

    bot.run(DISCORD_BOT_TOKEN)
