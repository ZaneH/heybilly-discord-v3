import os
import threading
import discord
from dotenv import load_dotenv
from src.rabbit.consumer import ActionConsumer

load_dotenv()

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")


class HeyBillyBot(discord.Bot):
    def __init__(self):
        super().__init__(command_prefix="!")
        self.queues = ["output.tts", "youtube.play", "volume.set"]
        self.consumers = [ActionConsumer(queue_name=q) for q in self.queues]
        self.consumer_threads = [threading.Thread(
            target=c.consume, daemon=True) for c in self.consumers]

    def start_consuming(self):
        try:
            self.actions_consumer.consume()
        except KeyboardInterrupt:
            print("Stopping actions consumer...")
            self.actions_consumer.stop()

    async def on_ready(self):
        print(f"Logged in as {self.user}.")
        for thread in self.consumer_threads:
            thread.start()

    def stop_consuming(self):
        for consumer in self.consumers:
            consumer.stop()


if __name__ == "__main__":
    bot = HeyBillyBot()

    @bot.slash_command(name="connect", description="Connect to your voice channel.")
    async def connect(ctx):
        await ctx.send("Connecting to your voice channel...", hidden=True)
        await ctx.author.voice.channel.connect()

    @bot.slash_command(name="disconnect", description="Disconnect from your voice channel.")
    async def disconnect(ctx):
        await ctx.send("Disconnecting from your voice channel...", hidden=True)
        await ctx.voice_client.disconnect()

    bot.run(DISCORD_BOT_TOKEN)
