import aiohttp
import logging
from aiogram.types import Message
from config import config


class TgTrackService:

    @staticmethod
    async def send_goal(user_id: int, target: str):
        url = f"https://bot-api.tgtrack.ru/v1/{config.TGTRACK}/send_reach_goal"

        payload = {
            "user_id": str(user_id),
            "target": target
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logging.error(
                        "TGTrack send_reach_goal error: %s",
                        await resp.text()
                    )

    @staticmethod
    async def send_start_to_tgtrack(message: Message):
        url = f"https://bot-api.tgtrack.ru/v1/{config.TGTRACK}/user_did_start_bot"

        start_value = ""
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                start_value = parts[1]

        payload = {
            "user_id": str(message.from_user.id),
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "username": message.from_user.username,
            "start_value": start_value
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logging.error(
                        "TGTrack user_did_start_bot error: %s",
                        await resp.text()
                    )
