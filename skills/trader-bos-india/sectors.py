"""Sector of each Nifty 50 / Next 50 stock, and which macro moves usually help or hurt each sector.

Used to rank sectors by today's move and to sort BOS signals so stocks in the
strongest themes come first. Stocks not listed fall into "Other". The macro
map is the usual direction of exposure, not a forecast.
"""

SECTOR = {
    # banks
    "AXISBANK": "Banks", "HDFCBANK": "Banks", "ICICIBANK": "Banks", "KOTAKBANK": "Banks", "SBIN": "Banks",
    "BANKBARODA": "Banks", "CANBK": "Banks", "PNB": "Banks", "UNIONBANK": "Banks",
    # lenders and financials
    "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC", "SHRIRAMFIN": "NBFC", "CHOLAFIN": "NBFC", "JIOFIN": "NBFC",
    "TATACAP": "NBFC", "BAJAJHLDNG": "NBFC", "PFC": "NBFC", "IRFC": "NBFC",
    "MUTHOOTFIN": "Gold finance",
    "HDFCLIFE": "Insurance & AMC", "SBILIFE": "Insurance & AMC", "HDFCAMC": "Insurance & AMC", "BSE": "Insurance & AMC",
    # IT
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "TECHM": "IT", "WIPRO": "IT", "LTM": "IT",
    # healthcare
    "SUNPHARMA": "Pharma & health", "CIPLA": "Pharma & health", "DRREDDY": "Pharma & health",
    "DIVISLAB": "Pharma & health", "TORNTPHARM": "Pharma & health", "ZYDUSLIFE": "Pharma & health",
    "APOLLOHOSP": "Pharma & health", "MAXHEALTH": "Pharma & health",
    # autos
    "MARUTI": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto", "EICHERMOT": "Auto", "TVSMOTOR": "Auto",
    "HYUNDAI": "Auto", "TMPV": "Auto", "TMCV": "Auto", "BOSCHLTD": "Auto", "MOTHERSON": "Auto",
    # consumer
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG", "TATACONSUM": "FMCG",
    "GODREJCP": "FMCG", "VBL": "FMCG",
    "TITAN": "Jewellery & retail", "TRENT": "Jewellery & retail", "DMART": "Jewellery & retail",
    "ETERNAL": "Jewellery & retail",
    "ASIANPAINT": "Paints & chemicals", "PIDILITIND": "Paints & chemicals",
    # commodities
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals", "VEDL": "Metals", "HINDZINC": "Metals",
    "JINDALSTEL": "Metals", "VAML": "Metals", "COALINDIA": "Metals",
    "ULTRACEMCO": "Cement", "AMBUJACEM": "Cement", "GRASIM": "Cement",
    # energy
    "BPCL": "Oil marketing", "IOC": "Oil marketing",
    "ONGC": "Oil & gas", "RELIANCE": "Oil & gas", "GAIL": "Oil & gas",
    "NTPC": "Power", "POWERGRID": "Power", "TATAPOWER": "Power", "ADANIPOWER": "Power", "ADANIGREEN": "Power",
    "ADANIENSOL": "Power",
    # industrials
    "LT": "Capital goods", "ABB": "Capital goods", "SIEMENS": "Capital goods", "CGPOWER": "Capital goods",
    "CUMMINSIND": "Capital goods", "POWERINDIA": "Capital goods", "POLYCAB": "Capital goods", "ENRIN": "Capital goods",
    "HAL": "Defence", "BEL": "Defence", "MAZDOCK": "Defence", "SOLARINDS": "Defence",
    # others
    "INDIGO": "Aviation", "ADANIPORTS": "Ports & logistics", "ADANIENT": "Conglomerate",
    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "DLF": "Realty",
}

# gauge name (as in trader-geo-india) -> (sectors helped when it rises, sectors hurt when it rises)
MACRO = {
    "Brent crude": (["Oil & gas"], ["Oil marketing", "Paints & chemicals", "Aviation", "Auto"]),
    "Gold": (["Gold finance"], ["Jewellery & retail"]),
    "USD/INR": (["IT", "Pharma & health"], ["Oil marketing", "Aviation"]),
    "Dollar index": ([], ["Metals", "Banks", "NBFC"]),
    "US 10y yield": ([], ["Banks", "NBFC", "Realty", "Insurance & AMC"]),
    "Nasdaq": (["IT"], []),
    "Hang Seng": (["Metals"], []),
}


def sector(sym):
    return SECTOR.get(sym, "Other")


def macro_tilt(gauges):
    """{sector: [reasons]} for flagged gauge moves: '+Brent crude down 9.5%' means a tailwind."""
    tilt = {}
    for g in gauges:
        if not g.get("flag") or g["name"] not in MACRO:
            continue
        helped, hurt = MACRO[g["name"]]
        up = g["change"] > 0
        move = "%s %s %.1f%s" % (g["name"], "up" if up else "down", abs(g["change"]), g["unit"])
        for s in helped:
            tilt.setdefault(s, []).append(("+" if up else "-") + move)
        for s in hurt:
            tilt.setdefault(s, []).append(("-" if up else "+") + move)
    return tilt


# scanner sector -> NSDL fortnightly FPI report sector (NSE industry classification); stock overrides first
NSDL_SECTOR = {
    "Banks": "Financial Services", "NBFC": "Financial Services", "Gold finance": "Financial Services",
    "Insurance & AMC": "Financial Services", "IT": "Information Technology", "Pharma & health": "Healthcare",
    "Auto": "Automobile and Auto Components", "FMCG": "Fast Moving Consumer Goods",
    "Jewellery & retail": "Consumer Services", "Paints & chemicals": "Consumer Durables",
    "Metals": "Metals & Mining", "Cement": "Construction Materials", "Oil marketing": "Oil, Gas & Consumable Fuels",
    "Oil & gas": "Oil, Gas & Consumable Fuels", "Power": "Power", "Capital goods": "Capital Goods",
    "Defence": "Capital Goods", "Aviation": "Services", "Ports & logistics": "Services",
    "Conglomerate": "Metals & Mining", "Telecom": "Telecommunication", "Realty": "Realty",
}
NSDL_STOCK = {"TITAN": "Consumer Durables", "PIDILITIND": "Chemicals", "COALINDIA": "Oil, Gas & Consumable Fuels",
              "LT": "Construction", "VBL": "Fast Moving Consumer Goods", "POLYCAB": "Capital Goods",
              "GRASIM": "Construction Materials", "DMART": "Consumer Services", "ETERNAL": "Consumer Services"}


def nsdl_sector(sym):
    return NSDL_STOCK.get(sym) or NSDL_SECTOR.get(sector(sym))
