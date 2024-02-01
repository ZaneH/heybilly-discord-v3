import asyncio
import os

import discord
from dotenv import load_dotenv

from src.bot.helper import BotHelper
from src.queue.consumer_manager import ConsumerManager

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID"))


class HeyBillyBot(discord.Bot):
    def __init__(self, loop):
        super().__init__(command_prefix="!", loop=loop)
        self.helper = BotHelper(self)
        self.action_queue = asyncio.Queue()

        self.consumer_manager = ConsumerManager(loop)
        self.queue_names = [
            "output.tts",
            "volume.set",
            "discord.post",
            "sfx.play",
            "music.control",
            "request.status"
        ]

    async def start_consumers(self):
        await self.consumer_manager.start()

        for queue_name in self.queue_names:
            await self.consumer_manager.create_consumer(queue_name, self.action_queue)

    async def process_actions(self):
        while True:
            try:
                action = await self.action_queue.get()
                node_type = action.get("node_type", None)
                print(f"Processing action: {action}")

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
                    print(f"Unknown action: {action}")
            except Exception as e:
                print(f"Error processing action: {e}")
                print(f"Action: {action}")

    async def on_ready(self):
        print(f"Logged in as {self.user}.")
        await self.start_consumers()

        self.loop.create_task(self.process_actions())

    async def close_connections(self):
        await self.consumer_manager.close()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    bot = HeyBillyBot(loop)

    if not discord.opus.is_loaded():
        try:
            discord.opus.load_opus("opus")
        except OSError:
            discord.opus.load_opus("/opt/homebrew/lib/libopus.dylib")
        except Exception as e:
            print(f"Error loading opus library: {e}")
            raise e

    @bot.slash_command(name="connect", description="Connect to your voice channel.")
    async def connect(ctx: discord.context.ApplicationContext):
        author_vc = ctx.author.voice
        if not author_vc:
            await ctx.respond("You are not in a voice channel.", ephemeral=True)
            return

        await ctx.respond("Connecting to your VC.", ephemeral=True)
        vc = await author_vc.channel.connect()
        bot.helper.guild_id = ctx.guild_id
        bot.helper.set_vc(vc)

    @bot.slash_command(name="disconnect", description="Disconnect from your voice channel.")
    async def disconnect(ctx: discord.context.ApplicationContext):
        bot_vc = ctx.voice_client
        if not bot_vc:
            await ctx.respond("I am not in your voice channel.", ephemeral=True)
            return

        await ctx.respond("Disconnecting from VC.", ephemeral=True)
        await bot_vc.disconnect()
        bot.helper.guild_id = None
        bot.helper.set_vc(None)

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
