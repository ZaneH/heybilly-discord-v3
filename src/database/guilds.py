import logging

from src.database.supabase import Client

logger = logging.getLogger(__name__)


class DBGuilds:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def create_guild_settings(self, owner_id: int, guild_id: int) -> bool:
        """
        Create the `guild_settings` table for the guild.
        :param owner_id: The owner's discord id.
        :param guild_id: The guild's discord id.
        :return: True if the guild settings were created successfully, False otherwise.
        """
        try:
            profile_res = self.supabase.table("profiles").select(
                "id").eq("discord_id", str(owner_id)).execute()

            data = profile_res.data
            if not data or len(data) == 0 or 'id' not in data[0] or not data[0]['id']:
                return False

            profile_id = data[0]["id"]
            try:
                self.supabase.table("guild_settings").insert({
                    "guild_id": str(guild_id),
                    "voice": None,
                    "profile_id": profile_id
                }).execute()

                return True
            except Exception as e:
                # If the guild settings already exist, return True.
                logger.debug(f"Error creating guild settings: {e}")
                return True
        except Exception as e:
            logger.debug(f"Error creating guild settings: {e}")
            return False
