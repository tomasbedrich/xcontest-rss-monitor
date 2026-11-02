import asyncio
import datetime
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import List, Iterable, Set
from xml.etree import ElementTree

from aiohttp import ClientSession, ClientResponseError

_pilot_id_cache = {}


@dataclass()
class Pilot:
    username: str
    id: int = None

    async def load_id(self, session: ClientSession):
        if self.username in _pilot_id_cache:
            self.id = _pilot_id_cache[self.username]
            return

        detail = await (await session.get(self.url)).text()
        match = re.search(r'<meta name="pilot-id" content="(\d+)"', detail)
        if not match:
            raise ValueError("Cannot find the pilot ID by a username, it probably doesn't exist")

        self.id = int(match[1])
        _pilot_id_cache[self.username] = self.id

    @property
    def url(self):
        return "https://www.xcontest.org/world/en/pilots/detail:" + self.username

    def __eq__(self, other):
        if isinstance(other, Pilot):
            return self.username == other.username
        return NotImplemented

    def __hash__(self):
        return hash(self.username)


@dataclass(frozen=True)
class Flight(object):
    title: str
    link: str
    datetime: datetime.datetime

    @property
    def pilot(self):
        # link = "https://www.xcontest.org/world/en/flights/detail:Bull77/21.05.2020/14:56"
        username = self.link.split("/")[-3].split(":")[1]
        # title = "20.04.19 [28.46 km :: free_flight] Marcin Makuch"
        return Pilot(username=username)

    def __eq__(self, other):
        if isinstance(other, Flight):
            return self.link == other.link
        return NotImplemented


async def download_feed(session: ClientSession, pilot_ids: Iterable[int]) -> str:
    if not pilot_ids:
        raise ValueError("Empty 'pilot' filter is not allowed")
    url = "https://www.xcontest.org/rss/flights/?world/en&pilot=" + "|".join(map(str, pilot_ids))
    return await (await session.get(url)).text()


async def find_invalid_pilot_ids(
    session: ClientSession, pilot_ids: Iterable[int], max_requests: int = 50, delay: float = 2
) -> Set[int]:
    """
    Bisect the pilot IDs (already known to fail as a whole) to find those XContest rejects with HTTP 400.

    Requests are sequential with a delay in between. Returns an empty set if `max_requests` is exhausted,
    so a server-wide failure cannot cause a request storm or mark every pilot as invalid.
    """
    pilot_ids = list(pilot_ids)
    if len(pilot_ids) == 1:
        return set(pilot_ids)
    mid = len(pilot_ids) // 2
    to_check = [pilot_ids[:mid], pilot_ids[mid:]]
    invalid = set()
    for _ in range(max_requests):
        if not to_check:
            return invalid
        ids = to_check.pop()
        await asyncio.sleep(delay)
        try:
            await download_feed(session, ids)
            continue
        except ClientResponseError as e:
            if e.status != 400:
                raise
        if len(ids) == 1:
            invalid.add(ids[0])
        else:
            mid = len(ids) // 2
            to_check += [ids[:mid], ids[mid:]]
    return set()


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


async def _main():
    from config import config
    from pprint import pprint
    async with ClientSession(**config.get_namespace("HTTP_")) as session:
        feed = await download_feed(session, pilot_ids=[42210, 37933])
        flights = parse_feed(feed)
        pprint(flights)


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
