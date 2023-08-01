import asyncio
import datetime
import html
import json
import logging
from asyncio import Task
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Optional, MutableMapping

import sentry_sdk
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher.filters import CommandStart, CommandHelp
from aiogram.utils import executor
from aiogram.utils.markdown import escape_md
from aiogram.utils.exceptions import BotBlocked
from aiohttp import ClientError, ClientSession
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from config import config
from xcontest import download_feed, parse_feed, Pilot

logging.basicConfig(level=config["LOGGING_LEVEL"], format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

log = logging.getLogger(__name__)

sentry_sdk.init(**config.get_namespace("SENTRY_"), integrations=[AioHttpIntegration()])

bot = Bot(token=config["TELEGRAM_BOT_TOKEN"])
dp = Dispatcher(bot)


@dataclass()
class PilotData:
    chat_ids: set = field(default_factory=set)
    """Non-empty set of chat IDs where the pilot wants his flights to be posted."""

    # must contain a timezone spec - UTC to match feed pubDate
    latest_flight: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    """Latest flight datetime is used to determine whether to post a flight discovered in a feed."""


state: MutableMapping[Pilot, PilotData] = dict()

watch_task: Optional[Task] = None

state_backup_task: Optional[Task] = None

session: Optional[ClientSession] = None


def create_task_log_exception(awaitable):
    async def _log_exception(awaitable):
        try:
            return await awaitable
        except Exception as e:
            log.exception(e)
    return asyncio.create_task(_log_exception(awaitable))


async def on_startup(dispatcher: Dispatcher):
    global session, state_backup_task, watch_task
    log.info("Opening an HTTP session")
    session = ClientSession(**config.get_namespace("HTTP_"))  # TODO set User-Agent
    load_state()
    if state and not watch_task:
        log.info("Starting a watch task")
        watch_task = create_task_log_exception(watch())


async def on_shutdown(dispatcher: Dispatcher):
    log.info("Closing an HTTP session")
    if session:
        await session.close()
    save_state()


def load_state():
    global state
    log.info("Loading a state")

    try:
        with config["STATE"].open("r") as f:
            data = json.load(f)
    except FileNotFoundError:
        log.warning("A previous state not found, creating an empty state")
        with config["STATE"].open("w") as f:
            json.dump([], f)
        return

    for item in data:
        pilot = Pilot(username=item["username"], id=item["id"])
        chat_ids = set(item["chat_ids"])
        latest_flight = datetime.datetime.fromisoformat(item["latest_flight"])
        state[pilot] = PilotData(chat_ids, latest_flight)


def save_state():
    log.info("Saving a state")

    res = []
    for pilot, data in state.items():
        res.append({
            "username": pilot.username,
            "id": pilot.id,
            "chat_ids": list(data.chat_ids),
            "latest_flight": data.latest_flight.isoformat()
        })

    with config["STATE"].open("w") as f:
        json.dump(res, f)


def get_state_item_by_pilot_id(id: int):
    for pilot, data in state.items():
        if pilot.id == id:
            return pilot, data
    raise ValueError(f"Pilot with id {id} not found in the state")


async def _get_pilot(message: types.Message):
    """Parse a Pilot object with username and ID from a Telegram message."""
    log.debug(f"Parsing a pilot username from {message=}")
    parts = message.text.strip().split(" ")
    if len(parts) != 2:
        raise ValueError("An username cannot be parsed from a message")
    username = parts[1].strip()

    pilot = Pilot(username=username)
    await pilot.load_id(session)
    log.debug(f"Fetched ID for {pilot}")
    return pilot


@dp.message_handler(commands=["register"])
async def register(message: types.Message):
    global watch_task

    chat_id = message.chat.id
    try:
        pilot = await _get_pilot(message)
    except ValueError as e:
        return await message.answer(f"{str(e)}. Please see /help")
    log.info(f"Registering {chat_id=} for {pilot}")

    if pilot in state and chat_id in state[pilot].chat_ids:
        return await message.answer("Already registered for this chat")

    if pilot not in state:
        state[pilot] = PilotData()
    state[pilot].chat_ids.add(chat_id)
    save_state()

    await message.answer("Okay, registered")
    if not watch_task:
        log.info("Starting a watch task")
        watch_task = create_task_log_exception(watch())


@dp.message_handler(commands=["unregister"])
async def unregister(message: types.Message):

    chat_id = message.chat.id
    try:
        pilot = await _get_pilot(message)
    except ValueError as e:
        return await message.answer(f"{str(e)}. Please see /help")
    log.info(f"Unregistering {chat_id=} for {pilot}")

    if pilot not in state or chat_id not in state[pilot].chat_ids:
        return await message.answer("Already unregistered for this chat")

    _unregister(pilot, chat_id)
    message.answer("Okay, unregistered")


def _unregister(pilot: Pilot, chat_id: int):
    global watch_task

    state[pilot].chat_ids.remove(chat_id)
    if not state[pilot].chat_ids:
        # need to cleanup keys with empty values
        del state[pilot]
    save_state()

    if not state and watch_task:
        log.info("Stopping a watch task")
        # noinspection PyUnresolvedReferences
        watch_task.cancel()
        watch_task = None


@dp.message_handler(commands=["list"])
async def list_(message: types.Message):
    chat_id = message.chat.id
    log.info(f"Listing all pilots for {chat_id=}")

    pilots = set()
    for pilot, data in state.items():
        if chat_id in data.chat_ids:
            pilots.add(pilot)

    if not pilots:
        return await message.answer("No pilots registered")

    sorted_pilots = sorted(pilots, key=lambda p: p.username)
    pilots_markdown = "\n".join(rf"\- [{escape_md(p.username)}]({p.url})" for p in sorted_pilots)
    await message.answer(
        "Pilots registered for this chat:\n" + pilots_markdown,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True
    )


@dp.message_handler(CommandStart())
@dp.message_handler(CommandHelp())
async def help(message: types.Message):
    await message.answer(dedent(r"""
    Watch XContest flights of specified pilots and post them into this chat\.
    `/register <XCONTEST-USERNAME>` \- start watching a pilot
    `/unregister <XCONTEST-USERNAME>` \- stop watching a pilot
    `/list` \- list currently watched pilots
    """), parse_mode="MarkdownV2")


def touch_liveness_probe():
    config["LIVENESS"].touch()


async def watch():
    while True:
        touch_liveness_probe()

        pilot_ids = {pilot.id for pilot in state.keys()}
        if not pilot_ids:
            log.info(f"No pilot_ids to fetch, sleeping for {config['SLEEP']} seconds")
            await asyncio.sleep(config["SLEEP"])
            continue

        try:
            log.info(f"Downloading a feed for {pilot_ids=}")
            feed = await download_feed(session, pilot_ids)
        except (ClientError, asyncio.TimeoutError):
            log.exception("The feed download failed")
            log.info(f"Sleeping for {config['BACKOFF_SLEEP']} seconds")
            await asyncio.sleep(config["BACKOFF_SLEEP"])
            continue

        flights = parse_feed(feed)
        flights_sorted = sorted(flights, key=lambda f: f.datetime)
        log.info(f"Parsed {len(flights)} flights")

        to_unregister = []

        for flight in flights_sorted:
            try:
                pilot_data = state[flight.pilot]
            except KeyError:
                # probably pilot changed his/her username (but fortunately ID remains the same)
                new_username = flight.pilot.username
                new_pilot = Pilot(username=new_username)
                await new_pilot.load_id(session)
                log.debug(f"Fetched ID for {new_pilot}")
                old_pilot, pilot_data = get_state_item_by_pilot_id(new_pilot.id)
                state[new_pilot] = pilot_data
                del state[old_pilot]
                log.debug(f"Pilot renamed from {old_pilot} to {new_pilot}, state updated")

            if flight.datetime <= pilot_data.latest_flight:
                log.debug(f"Skipping {flight} because it is older or equal to latest flight datetime: {pilot_data.latest_flight}")
                continue
            try:
                for chat_id in pilot_data.chat_ids:
                    log.debug(f"About to post {flight} to {chat_id=}")
                    try:
                        flight_title = html.escape(flight.title)
                        await bot.send_message(chat_id, f'<a href="{flight.link}">{flight_title}</a> [<a href="{flight.pilot.url}">{flight.pilot.username}</a>]', parse_mode="HTML")
                    except BotBlocked:
                        to_unregister.append((flight.pilot, chat_id))
                        continue
                pilot_data.latest_flight = flight.datetime
                log.info(f"Posted {flight} to chat_ids={pilot_data.chat_ids}")
            except (ClientError, asyncio.TimeoutError):
                log.exception("Posting failed")
                log.info(f"Sleeping for {config['BACKOFF_SLEEP']} seconds")
                await asyncio.sleep(config["BACKOFF_SLEEP"])
                continue

        for pilot, chat_id in to_unregister:
            log.debug(f"Bot blocked by user {chat_id=}, executing unregister command")
            _unregister(pilot, chat_id)

        save_state()
        log.info(f"Sleeping for {config['SLEEP']} seconds")
        await asyncio.sleep(config["SLEEP"])


if __name__ == "__main__":
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)
