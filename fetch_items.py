import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date

import httpx
from tqdm.asyncio import tqdm

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

@dataclass
class Config:
    searchText: str
    pageSize: int
    pageLimit: int | None # Must be greater than 0

CONFIG = Config(searchText="*", pageSize=100, pageLimit=None)

async def fetch_bibs(sem: asyncio.Semaphore, dateFrom: int, dateTo: int, pageNum: int = 0, get_pages: bool = False) -> tuple:
    async with sem:
        # if not get_pages:
        #     logger.info(f"Fetching page {pageNum}")

        url: str = "https://na2.iiivega.com/api/search-result/search/format-groups"

        headers: dict = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "anonymous-user-id": "86d9e401-ea99-4bc3-a5aa-08a9a00a9e0e",
            "api-version": "2",
            "content-type": "application/json",
            "iii-customer-domain": "slouc.na2.iiivega.com",
            "iii-host-domain": "slouc.na2.iiivega.com",
            "priority": "u=1, i",
            "sec-ch-ua": "Chromium;v=146, Not-A.Brand;v=24, Google Chrome;v=146",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "Windows",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "Referer": "https://slouc.na2.iiivega.com/"
        }

        payload: dict = {
            "searchText": CONFIG.searchText,
            "sorting": "title",
            "sortOrder": "asc",
            "searchType": "everything",
            "universalLimiterIds": [
                "at_library"
            ],
            "materialTypeIds": [
                "1"
            ],
            "locationIds": [
                "59"
            ],
            "pageNum": pageNum,
            "pageSize": CONFIG.pageSize,
            "resourceType": "FormatGroup",
            "dateFrom": dateFrom,
            "dateTo": dateTo,
        }

    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(url=url, headers=headers, json=payload)

    response.raise_for_status()
    records: dict = response.json()

    if get_pages:
        total_pages: int = records.get('totalPages')
        return total_pages

    parsed: dict = []
    ids: set = set()

    for r in records.get('data'):
        parsed.append(
            (
                r.get("id"),
                r.get('title'),
                r.get('publicationDate'),
                r.get('coverUrl', {}).get('medium'),
                r.get('materialTabs', [])[0].get('editions', [])[0].get('id')
            )
        )
        ids.add(r.get("id"))
    return parsed, ids

def get_lang(lang_abr: str) -> str:
    # take lang code and return full language.
    langs = {
        'ben': 'Bengali',
        'bos': 'Bosnian',
        'eka': 'Ekajuk',
        'eng': 'English',
        'enm': 'Middle English',
        'hrv': 'Croatian',
        'kor': 'Korean',
        'mul': 'Multiple languages',
        'spa': 'Spanish',
        'srp': 'Serbian',
        'tur': 'Turkish',
        'und': 'Undefined',
        '|||': 'Undefined'
    }

    lang_abr_std = lang_abr.lower().strip()
    full_lang = langs.get(lang_abr_std)

    if full_lang:
        return full_lang
    else:
        return "Undefined"

async def fetch_edition(id: str, sem: asyncio.Semaphore) -> tuple:
    async with sem:
        url: str = f"https://na2.iiivega.com/api/search-result/editions/{id}"
        headers: dict = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "anonymous-user-id": "8f979f0f-2cda-46d7-9da5-4c3dddec18b0",
            "api-version": "1",
            "iii-customer-domain": "slouc.na2.iiivega.com",
            "iii-host-domain": "slouc.na2.iiivega.com",
            "priority": "u=1, i",
            "sec-ch-ua": "Chromium;v=146, Not-A.Brand;v=24, Google Chrome;v=146",
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": "\"Windows\"",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "Referer": "https://slouc.na2.iiivega.com/"
        }

        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.get(url=url, headers=headers)

        response.raise_for_status()

        data: dict = response.json()
        e: dict = data.get("edition", {})

        # create subjects string
        subjects: list = []
        for k, v in e.items():
            if re.match("subj", k):
                for subject in v:
                    subjects.append(subject)
        try:
            author: str = ", ".join(e.get("author", []))
        except Exception:
            author: str = e.get("author")

        edition_info: tuple = (
            id,
            author,
            ", ".join(e.get("itemLanguage", [])),
            ", ".join(subjects),
            ", ".join(e.get("noteSummary", []))
        )

        return edition_info

async def fetch_all_bibs() -> tuple:
    sem = asyncio.Semaphore(5)
    current_year = date.today().year
    years = list(range(2000, current_year + 1))

    all_bibs = []
    all_ids = set()

    # get from years 1 to 1999 first
    all_bibs, all_ids = await bibs_loop(sem, 1, 1999, all_bibs, all_ids)
    for year in years:
        all_bibs, all_ids = await bibs_loop(sem, year, year, all_bibs, all_ids)
    
    return all_bibs, all_ids

async def bibs_loop(sem: asyncio.Semaphore, dateFrom: int, dateTo: int, all_bibs: list, all_ids: set) -> tuple:
    total_pages: int = await fetch_bibs(sem = sem, dateFrom=dateFrom, dateTo=dateTo, get_pages=True)

    coroutines: list = [fetch_bibs(sem=sem, dateFrom=dateFrom, dateTo=dateTo,  pageNum=i) for i in range(0, total_pages + 1)]
    results: list = await tqdm.gather(*coroutines, desc="fetching bibs...")

    bib_list, id_list =zip(*results)
    
    for item in bib_list:
        all_bibs += item
    
    for item in id_list:
        all_ids = all_ids | item

    return all_bibs, all_ids

async def fetch_all_editions(edition_ids: list):
    sem = asyncio.Semaphore(5)
    coroutines = [fetch_edition(id, sem) for id in edition_ids]
    editions = await tqdm.gather(*coroutines, desc="fetching editions...")
    return editions
    
if __name__ == "__main__":
    # all_bibs, all_ids = fetch_all_bibs()
    # edition = fetch_edition("5dea2497-dff9-11ed-8960-5526fbe53189")
    all_bibs, all_ids = asyncio.run(fetch_all_bibs())
    print(len(all_ids))
    # result = asyncio.run(fetch_all_editions({"5dea2497-dff9-11ed-8960-5526fbe53189"}))
