import datetime
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import List, Iterable
from xml.etree import ElementTree

from aiohttp import ClientSession

_pilot_id_cache = {}


@dataclass()
class Pilot:
    username: str
    id: int = None

    async def load_id(self, session: ClientSession):
        if self.username in _pilot_id_cache:
            self.id = _pilot_id_cache[self.username]
            return

        url = "https://www.xcontest.org/world/cs/piloti/detail:" + self.username
        detail = await (await session.get(url)).text()
        match = re.search(r'XContest\.run\("pilot", .*item : (\d+)', detail, re.DOTALL)
        if not match:
            raise ValueError("Cannot find the pilot ID by a username, it probably doesn't exist")

        self.id = int(match[1])
        _pilot_id_cache[self.username] = self.id

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
        # link = ''https://www.xcontest.org/cesko/prelety/detail:Bull77/19.05.2020/14:32''
        username = self.link.split("/")[5].split(":")[1]
        # title = '20.04.19 [28.46 km :: free_flight] Marcin Makuch'
        return Pilot(username=username)

    def __eq__(self, other):
        if isinstance(other, Flight):
            return self.link == other.link
        return NotImplemented


async def download_feed(session: ClientSession, pilot_ids: Iterable[int]) -> str:
    if not pilot_ids:
        raise ValueError("Empty 'pilot' filter is not allowed")
    url = "https://www.xcontest.org/rss/flights/?cpp&pilot=" + "|".join(map(str, pilot_ids))
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
