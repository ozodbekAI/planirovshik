import aiohttp
import logging
from config import config


TGTRACK_GOAL_URL = f"https://bot-api.tgtrack.ru/v1/{config.TGRACK}/send_reach_goal"


class TgTrackService:

    @staticmethod
    async def send_goal(user_id: int, target: str):
        payload = {
            "user_id": str(user_id),
            "target": target
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(TGTRACK_GOAL_URL, json=payload) as resp:
                if resp.status != 200:
                    logging.error(
                        "TGTrack send_reach_goal error: %s",
                        await resp.text()
                    )
