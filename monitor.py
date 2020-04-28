#!/usr/bin/env python3

import asyncio
import datetime
import logging
import sys
from collections import MutableSet
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import List
from xml.etree import ElementTree

from aiohttp import ClientError, ClientSession, ClientTimeout
from llconfig import Config
from llconfig.converters import bool_like

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

config = Config()
config.init("FEED_URL", str)
config.init("HTTP_TIMEOUT", lambda val: ClientTimeout(total=int(val)), ClientTimeout(total=10))  # seconds
config.init("HTTP_RAISE_FOR_STATUS", bool_like, True)

config.init("WEBHOOK_URL", str, None)
config.init("WEBHOOK_TEXT_TEMPLATE", str, "<{flight.link}|{flight.title}>")

config.init("TELEGRAM_BOT_TOKEN", str, None)
config.init("TELEGRAM_URL", str, "https://api.telegram.org/bot{token}/sendMessage")
config.init("TELEGRAM_CHAT_ID", int, None)
config.init("TELEGRAM_TEXT_TEMPLATE", str, "{flight.title}\n{flight.link}")

config.init("SLEEP", int, 600)  # seconds
config.init("BACKOFF_SLEEP", int, 1200)  # seconds


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


class History(MutableSet):
    """
    Stateful object to determine which flights have already been posted.
    """

    def discard(self, flight):
        del self._flights[flight]

    def __len__(self):
        return len(self._flights)

    def __iter__(self):
        return iter(self._flights.keys())

    def __init__(self):
        # key = flight, value = "is touched in current round"
        self._flights = {}

    def __contains__(self, flight):
        if flight in self._flights:
            self._flights[flight] = True
        return flight in self._flights

    def add(self, flight):
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
    await session.post(webhook_url, json={"text": text})


async def post_telegram(session: ClientSession, telegram_url: str, chat_id: int, text: str):
    await session.post(telegram_url, data={"chat_id": chat_id, "text": text})


async def do_output(session, flight):
    tasks = []
    if config["WEBHOOK_URL"]:
        tasks.append(post_webhook(
            session,
            config["WEBHOOK_URL"],
            config["WEBHOOK_TEXT_TEMPLATE"].format(flight=flight)
        ))
    if config["TELEGRAM_BOT_TOKEN"] and config["TELEGRAM_CHAT_ID"]:
        tasks.append(post_telegram(
            session,
            config["TELEGRAM_URL"].format(token=config["TELEGRAM_BOT_TOKEN"]),
            config["TELEGRAM_CHAT_ID"],
            config["TELEGRAM_TEXT_TEMPLATE"].format(flight=flight)
        ))
    await asyncio.gather(*tasks)


async def main():
    if not config["FEED_URL"]:
        logging.error("Missing FEED_URL, exiting.")
        sys.exit(1)

    if not config["WEBHOOK_URL"]:
        logging.warning("Missing WEBHOOK_URL, webhook output turned off.")

    if not config["TELEGRAM_BOT_TOKEN"] or not config["TELEGRAM_CHAT_ID"]:
        logging.warning("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID, Telegram output turned off.")

    already_posted = History()
    startup = True

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

            already_posted.next_round()

            flights = parse_feed(feed)
            logging.info(f"Parsed: {len(flights)} flights")

            if startup:
                startup = False
                # first round - assume that everything we parse is already posted
                for flight in flights:
                    already_posted.add(flight)
                logging.info(f"Sleeping for {config['SLEEP']} seconds")
                await asyncio.sleep(config["SLEEP"])
                continue

            for flight in flights:
                if flight in already_posted:
                    # this check "touches" the history (= informs the object, that the flight is still active and should not be purged)
                    continue
                try:
                    await do_output(session, flight)
                    already_posted.add(flight)
                    logging.info(f"Posted: {flight}")
                except (ClientError, asyncio.TimeoutError):
                    logging.exception("Post failed")
                    logging.info(f"Sleeping for {config['BACKOFF_SLEEP']} seconds")
                    await asyncio.sleep(config["BACKOFF_SLEEP"])
                    continue

            logging.info(f"Sleeping for {config['SLEEP']} seconds")
            await asyncio.sleep(config["SLEEP"])


if __name__ == "__main__":
    asyncio.run(main())
