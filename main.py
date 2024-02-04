import asyncio
import json
import logging
import os

import discord
from dotenv import load_dotenv

from src.config.cliargs import CLIArgs
from src.utils.commandline import CommandLine

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

logger = logging.getLogger(__name__)


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

    from src.bot.heybilly_bot import HeyBillyBot
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
        if bot._is_ready is False:
            await ctx.respond("I am not ready yet. Try again later.", ephemeral=True)
            return

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
