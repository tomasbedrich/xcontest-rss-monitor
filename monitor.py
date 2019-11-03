#!/usr/bin/env python3

import asyncio
from dataclasses import dataclass
import datetime
from email.utils import parsedate_to_datetime
import logging
from typing import List
from xml.etree import ElementTree
from llconfig import Config

from aiohttp import ClientError, ClientSession, ClientTimeout
from llconfig.converters import bool_like

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

config = Config()
config.init("FEED_URL", str, "https://www.xcontest.org/rss/flights/?world/en")
config.init("HTTP_TIMEOUT", lambda val: ClientTimeout(total=int(val)), ClientTimeout(total=10))  # seconds
config.init("HTTP_RAISE_FOR_STATUS", bool_like, True)
config.init("WEBHOOK_URL", str, None)
config.init("WEBHOOK_TEXT_TEMPLATE", str, "<{flight.link}|{flight.title}>")
config.init("PILOT_USERNAMES", lambda val: val.split(","), {})
config.init("SLEEP", int, 10)  # seconds
config.init("BACKOFF_SLEEP", int, 30)  # seconds

if not config["WEBHOOK_URL"]:
    logging.warning("Missing WEBHOOK_URL, requests will only be printed to console")


@dataclass(unsafe_hash=True)
class Flight(object):
    title: str
    link: str
    datetime: datetime.datetime

    @property
    def pilot_username(self):
        # link = 'https://www.xcontest.org/world/en/flights/detail:Filipo/21.04.2019/07:57'
        return self.link.split("/")[6].split(":")[1]

    @property
    def pilot_name(self):
        # title = '20.04.19 [28.46 km :: free_flight] Marcin Makuch'
        return self.title.split("]")[-1].strip()


class History(object):
    """
    Stateful object to determine which flights have already been posted.
    """

    def __init__(self):
        # key = flight, value = "is touched in current round"
        self._flights = {}

    def should_skip(self, flight):
        if flight in self._flights:
            self._flights[flight] = True
        return flight in self._flights

    def track(self, flight):
        # just touch
        self._flights[flight] = True

    def next_round(self):
        # 1) remove flights, which has not been touched in previous round
        # 2) reset touches for others
        for flight in tuple(self._flights.keys()):
            if not self._flights[flight]:
                del self._flights[flight]
            else:
                self._flights[flight] = False


async def download_feed(session: ClientSession, url: str) -> str:
    return await (await session.get(url)).text()


def parse_feed(feed: str) -> List[Flight]:
    root = ElementTree.fromstring(feed)
    res = []
    for item in root.iterfind("channel/item"):
        flight = Flight(
            title=item.find("title").text,
            link=item.find("link").text.strip(),
            datetime=parsedate_to_datetime(item.find("pubDate").text)
        )
        res.append(flight)
    return res


async def post_webhook(session: ClientSession, webhook_url: str, text: str):
    if webhook_url:
        await session.post(webhook_url, json={"text": text})
    else:
        logging.info(f"POST: {text}")  # debug only


async def main():
    history = History()
    async with ClientSession(**config.get_namespace("HTTP_")) as session:
        while True:
            try:
                feed = await download_feed(session, config["FEED_URL"])
                logging.info("Downloaded feed")
            except (ClientError, asyncio.TimeoutError):
                logging.exception("Feed download failed")
                logging.info(f"Sleeping for {config['BACKOFF_SLEEP']} seconds")
                await asyncio.sleep(config["BACKOFF_SLEEP"])
                continue

            history.next_round()

            flights = parse_feed(feed)
            logging.info(f"Parsed: {len(flights)} flights")

            flights = [f for f in flights if f.pilot_username in config["PILOT_USERNAMES"]]
            logging.info(f"Filter by pilot: {len(flights)} flights")

            flights = [f for f in flights if not history.should_skip(f)]
            logging.info(f"Filter already posted: {len(flights)} flights")

            for flight in flights:
                try:
                    await post_webhook(
                        session,
                        config["WEBHOOK_URL"],
                        config["WEBHOOK_TEXT_TEMPLATE"].format(flight=flight)
                    )
                    history.track(flight)
                    logging.info(f"Posted to webhook: {flight}")
                except (ClientError, asyncio.TimeoutError):
                    logging.exception("Webhook post failed")
                    logging.info(f"Sleeping for {config['BACKOFF_SLEEP']} seconds")
                    await asyncio.sleep(config["BACKOFF_SLEEP"])
                    continue

            logging.info(f"Sleeping for {config['SLEEP']} seconds")
            await asyncio.sleep(config["SLEEP"])


if __name__ == "__main__":
    asyncio.run(main())
