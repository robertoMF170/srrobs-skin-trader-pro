import requests

from collectors.steam import SteamCollector

c = SteamCollector()
p = c._priceoverview("AK-47 | Redline (Field-Tested)")
print("steam:", p)
