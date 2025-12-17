from aiohttp import ClientSession
from urllib.parse import quote
import asyncio
import json

url = 'https://gw.yad2.co.il'
PROPERTY_MAPPING = None
PROXY_URL = None # for avoid rate limit use proxy (roaute proxy rednantinal israel isp)

with open("property.json", "r", encoding="UTF-8", errors="ignore") as f:
    PROPERTY_MAPPING = json.loads(f.read())

async def get_city_id(client, city):
    response = await client.get(f"{url}/address-autocomplete/realestate/v2?text={quote(city)}")
    data = await response.json()
    return [info_city.get("cityId") for info_city in data.get("cities", []) if info_city.get("cityId")]


async def get_contact_info(client, ads_id):
    response = await client.get(f'{url}/realestate-item/{ads_id}/customer')
    data = await response.json()
    print(data)
    return data

async def fetch_feed(client: object, page: int = 1, city: str = "4000", property: str = "apartment"):
    property = PROPERTY_MAPPING.get(property, 1)
    response = await client.get(f"{url}/realestate-feed/rent/feed?multiCity={city}&property={property}&sort=1&page={page}")
    data = await response.json()
    results = data.get("data", {}).get("private")
   
    for index, item in enumerate(results, 0):
        results[index]['contact_info'] = await get_contact_info(client, item.get("token"))
    
    print(results)
    return results

async def main():
    property = "apartment"
    city = "תל אביב"
    dump = []
    tasks = []
    async with ClientSession() as client:
        city = await get_city_id(client, city)
        city = ",".join(city)
        for page in range(1, 11):
            tasks.append(asyncio.create_task(fetch_feed(client, page, city, property)))

        
        results = await asyncio.gather(*tasks)
        for result in results:
            dump.append(result)


    with open("dump.json", "w", encoding="UTF-8", errors="ignore") as f:
        json.dump(dump, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    from sys import platform
    if platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

