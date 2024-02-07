import os
import stripe
from src.database.supabase import supabase

stripe.api_key = os.getenv("STRIPE_API_KEY")


class StripeCustomer:
    @staticmethod
    def get_profile_id_for_guild_id(guild_id: int):
        response = supabase.table("guild_settings")\
            .select("profile_id")\
            .eq("guild_id", str(guild_id))\
            .execute()

        data = response.data

        if data and len(data) > 0 and 'profile_id' in data[0] and data[0]['profile_id']:
            return data[0]['profile_id']
        else:
            # Handle the case where the guild ID is not found or does not have an associated profile
            return None

    @staticmethod
    def get_customer_id_for_guild_id(guild_id: str):
        profile_id = StripeCustomer.get_profile_id_for_guild_id(guild_id)
        if not profile_id:
            return None

        response = supabase.table("stripe_customers")\
            .select("stripe_customer_id")\
            .eq("user_id", profile_id)\
            .execute()

        data = response.data

        if data and len(data) > 0 and 'stripe_customer_id' in data[0] and data[0]['stripe_customer_id']:
            return data[0]['stripe_customer_id']
        else:
            return None

    @staticmethod
    def has_active_plan(guild_id: str):
        customer_id = StripeCustomer.get_customer_id_for_guild_id(guild_id)
        if not customer_id:
            return False

        response = stripe.Subscription.list(
            customer=customer_id, status="active")

        return len(response.data) > 0
