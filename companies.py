"""
Company / ticker directory.

Two layers, because neither alone is good enough:

1. BUNDLED CATALOG - a few hundred well-known companies across US, India
   and major global listings. Works instantly and offline, powers the
   "browse companies" panel, and covers the names most people actually
   type. It is a convenience shortlist, NOT the limit of what the app
   supports.

2. LIVE SYMBOL SEARCH - Yahoo Finance's own search endpoint, which covers
   its entire universe (~100k+ securities across global exchanges). This
   is what makes "any company" real: if it's listed and Yahoo has it, you
   can find it here even though it isn't in the bundled list.

Search merges both: catalog hits first (instant, curated), then live
results that weren't already covered.

Note on staleness: tickers do change (renames, mergers, re-listings). A
bundled entry can go out of date; live search is always authoritative, so
if a catalog entry ever misbehaves, searching the company name will
return the current symbol.
"""
from __future__ import annotations

from proc_isolate import run_with_timeout, SubprocessCallFailed

# region codes: US, IN, GLOBAL (ADRs / non-US listings), ETF
CATALOG = [
    # ---------------- US · Technology ----------------
    {"symbol": "AAPL",  "name": "Apple Inc.",                  "region": "US", "sector": "Technology"},
    {"symbol": "MSFT",  "name": "Microsoft Corporation",       "region": "US", "sector": "Technology"},
    {"symbol": "GOOGL", "name": "Alphabet Inc. (Class A)",     "region": "US", "sector": "Technology"},
    {"symbol": "GOOG",  "name": "Alphabet Inc. (Class C)",     "region": "US", "sector": "Technology"},
    {"symbol": "AMZN",  "name": "Amazon.com Inc.",             "region": "US", "sector": "Consumer"},
    {"symbol": "META",  "name": "Meta Platforms Inc.",         "region": "US", "sector": "Technology"},
    {"symbol": "NVDA",  "name": "NVIDIA Corporation",          "region": "US", "sector": "Semiconductors"},
    {"symbol": "AVGO",  "name": "Broadcom Inc.",               "region": "US", "sector": "Semiconductors"},
    {"symbol": "ORCL",  "name": "Oracle Corporation",          "region": "US", "sector": "Technology"},
    {"symbol": "CRM",   "name": "Salesforce Inc.",             "region": "US", "sector": "Technology"},
    {"symbol": "ADBE",  "name": "Adobe Inc.",                  "region": "US", "sector": "Technology"},
    {"symbol": "IBM",   "name": "International Business Machines", "region": "US", "sector": "Technology"},
    {"symbol": "CSCO",  "name": "Cisco Systems Inc.",          "region": "US", "sector": "Technology"},
    {"symbol": "INTC",  "name": "Intel Corporation",           "region": "US", "sector": "Semiconductors"},
    {"symbol": "AMD",   "name": "Advanced Micro Devices",      "region": "US", "sector": "Semiconductors"},
    {"symbol": "QCOM",  "name": "Qualcomm Inc.",               "region": "US", "sector": "Semiconductors"},
    {"symbol": "TXN",   "name": "Texas Instruments",           "region": "US", "sector": "Semiconductors"},
    {"symbol": "MU",    "name": "Micron Technology",           "region": "US", "sector": "Semiconductors"},
    {"symbol": "AMAT",  "name": "Applied Materials",           "region": "US", "sector": "Semiconductors"},
    {"symbol": "LRCX",  "name": "Lam Research",                "region": "US", "sector": "Semiconductors"},
    {"symbol": "KLAC",  "name": "KLA Corporation",             "region": "US", "sector": "Semiconductors"},
    {"symbol": "ADI",   "name": "Analog Devices",              "region": "US", "sector": "Semiconductors"},
    {"symbol": "NOW",   "name": "ServiceNow Inc.",             "region": "US", "sector": "Technology"},
    {"symbol": "INTU",  "name": "Intuit Inc.",                 "region": "US", "sector": "Technology"},
    {"symbol": "PANW",  "name": "Palo Alto Networks",          "region": "US", "sector": "Technology"},
    {"symbol": "CRWD",  "name": "CrowdStrike Holdings",        "region": "US", "sector": "Technology"},
    {"symbol": "SNOW",  "name": "Snowflake Inc.",              "region": "US", "sector": "Technology"},
    {"symbol": "PLTR",  "name": "Palantir Technologies",       "region": "US", "sector": "Technology"},
    {"symbol": "DDOG",  "name": "Datadog Inc.",                "region": "US", "sector": "Technology"},
    {"symbol": "NET",   "name": "Cloudflare Inc.",             "region": "US", "sector": "Technology"},
    {"symbol": "MDB",   "name": "MongoDB Inc.",                "region": "US", "sector": "Technology"},
    {"symbol": "TEAM",  "name": "Atlassian Corporation",       "region": "US", "sector": "Technology"},
    {"symbol": "WDAY",  "name": "Workday Inc.",                "region": "US", "sector": "Technology"},
    {"symbol": "DELL",  "name": "Dell Technologies",           "region": "US", "sector": "Technology"},
    {"symbol": "HPQ",   "name": "HP Inc.",                     "region": "US", "sector": "Technology"},
    {"symbol": "ACN",   "name": "Accenture plc",               "region": "US", "sector": "Technology"},

    # ---------------- US · Consumer & Retail ----------------
    {"symbol": "TSLA",  "name": "Tesla Inc.",                  "region": "US", "sector": "Automotive"},
    {"symbol": "NFLX",  "name": "Netflix Inc.",                "region": "US", "sector": "Media"},
    {"symbol": "DIS",   "name": "Walt Disney Company",         "region": "US", "sector": "Media"},
    {"symbol": "CMCSA", "name": "Comcast Corporation",         "region": "US", "sector": "Media"},
    {"symbol": "WMT",   "name": "Walmart Inc.",                "region": "US", "sector": "Retail"},
    {"symbol": "COST",  "name": "Costco Wholesale",            "region": "US", "sector": "Retail"},
    {"symbol": "TGT",   "name": "Target Corporation",          "region": "US", "sector": "Retail"},
    {"symbol": "HD",    "name": "Home Depot Inc.",             "region": "US", "sector": "Retail"},
    {"symbol": "LOW",   "name": "Lowe's Companies",            "region": "US", "sector": "Retail"},
    {"symbol": "DG",    "name": "Dollar General",              "region": "US", "sector": "Retail"},
    {"symbol": "KR",    "name": "Kroger Company",              "region": "US", "sector": "Retail"},
    {"symbol": "NKE",   "name": "Nike Inc.",                   "region": "US", "sector": "Consumer"},
    {"symbol": "SBUX",  "name": "Starbucks Corporation",       "region": "US", "sector": "Consumer"},
    {"symbol": "MCD",   "name": "McDonald's Corporation",      "region": "US", "sector": "Consumer"},
    {"symbol": "CMG",   "name": "Chipotle Mexican Grill",      "region": "US", "sector": "Consumer"},
    {"symbol": "YUM",   "name": "Yum! Brands",                 "region": "US", "sector": "Consumer"},
    {"symbol": "KO",    "name": "Coca-Cola Company",           "region": "US", "sector": "Consumer"},
    {"symbol": "PEP",   "name": "PepsiCo Inc.",                "region": "US", "sector": "Consumer"},
    {"symbol": "PG",    "name": "Procter & Gamble",            "region": "US", "sector": "Consumer"},
    {"symbol": "MDLZ",  "name": "Mondelez International",      "region": "US", "sector": "Consumer"},
    {"symbol": "CL",    "name": "Colgate-Palmolive",           "region": "US", "sector": "Consumer"},
    {"symbol": "PM",    "name": "Philip Morris International", "region": "US", "sector": "Consumer"},
    {"symbol": "ABNB",  "name": "Airbnb Inc.",                 "region": "US", "sector": "Travel"},
    {"symbol": "UBER",  "name": "Uber Technologies",           "region": "US", "sector": "Technology"},
    {"symbol": "LYFT",  "name": "Lyft Inc.",                   "region": "US", "sector": "Technology"},
    {"symbol": "DASH",  "name": "DoorDash Inc.",               "region": "US", "sector": "Technology"},
    {"symbol": "MAR",   "name": "Marriott International",      "region": "US", "sector": "Travel"},
    {"symbol": "HLT",   "name": "Hilton Worldwide",            "region": "US", "sector": "Travel"},
    {"symbol": "BKNG",  "name": "Booking Holdings",            "region": "US", "sector": "Travel"},
    {"symbol": "DAL",   "name": "Delta Air Lines",             "region": "US", "sector": "Airlines"},
    {"symbol": "UAL",   "name": "United Airlines Holdings",    "region": "US", "sector": "Airlines"},
    {"symbol": "LUV",   "name": "Southwest Airlines",          "region": "US", "sector": "Airlines"},
    {"symbol": "F",     "name": "Ford Motor Company",          "region": "US", "sector": "Automotive"},
    {"symbol": "GM",    "name": "General Motors",              "region": "US", "sector": "Automotive"},
    {"symbol": "RIVN",  "name": "Rivian Automotive",           "region": "US", "sector": "Automotive"},

    # ---------------- US · Financials ----------------
    {"symbol": "BRK-B", "name": "Berkshire Hathaway (Class B)", "region": "US", "sector": "Financials"},
    {"symbol": "JPM",   "name": "JPMorgan Chase & Co.",        "region": "US", "sector": "Financials"},
    {"symbol": "BAC",   "name": "Bank of America",             "region": "US", "sector": "Financials"},
    {"symbol": "WFC",   "name": "Wells Fargo & Company",       "region": "US", "sector": "Financials"},
    {"symbol": "C",     "name": "Citigroup Inc.",              "region": "US", "sector": "Financials"},
    {"symbol": "GS",    "name": "Goldman Sachs Group",         "region": "US", "sector": "Financials"},
    {"symbol": "MS",    "name": "Morgan Stanley",              "region": "US", "sector": "Financials"},
    {"symbol": "SCHW",  "name": "Charles Schwab Corporation",  "region": "US", "sector": "Financials"},
    {"symbol": "BLK",   "name": "BlackRock Inc.",              "region": "US", "sector": "Financials"},
    {"symbol": "AXP",   "name": "American Express",            "region": "US", "sector": "Financials"},
    {"symbol": "V",     "name": "Visa Inc.",                   "region": "US", "sector": "Financials"},
    {"symbol": "MA",    "name": "Mastercard Inc.",             "region": "US", "sector": "Financials"},
    {"symbol": "PYPL",  "name": "PayPal Holdings",             "region": "US", "sector": "Financials"},
    {"symbol": "COIN",  "name": "Coinbase Global",             "region": "US", "sector": "Financials"},
    {"symbol": "HOOD",  "name": "Robinhood Markets",           "region": "US", "sector": "Financials"},
    {"symbol": "SPGI",  "name": "S&P Global Inc.",             "region": "US", "sector": "Financials"},
    {"symbol": "MCO",   "name": "Moody's Corporation",         "region": "US", "sector": "Financials"},
    {"symbol": "CME",   "name": "CME Group",                   "region": "US", "sector": "Financials"},
    {"symbol": "ICE",   "name": "Intercontinental Exchange",   "region": "US", "sector": "Financials"},

    # ---------------- US · Healthcare ----------------
    {"symbol": "UNH",   "name": "UnitedHealth Group",          "region": "US", "sector": "Healthcare"},
    {"symbol": "JNJ",   "name": "Johnson & Johnson",           "region": "US", "sector": "Healthcare"},
    {"symbol": "LLY",   "name": "Eli Lilly and Company",       "region": "US", "sector": "Healthcare"},
    {"symbol": "ABBV",  "name": "AbbVie Inc.",                 "region": "US", "sector": "Healthcare"},
    {"symbol": "MRK",   "name": "Merck & Co.",                 "region": "US", "sector": "Healthcare"},
    {"symbol": "PFE",   "name": "Pfizer Inc.",                 "region": "US", "sector": "Healthcare"},
    {"symbol": "TMO",   "name": "Thermo Fisher Scientific",    "region": "US", "sector": "Healthcare"},
    {"symbol": "ABT",   "name": "Abbott Laboratories",         "region": "US", "sector": "Healthcare"},
    {"symbol": "DHR",   "name": "Danaher Corporation",         "region": "US", "sector": "Healthcare"},
    {"symbol": "AMGN",  "name": "Amgen Inc.",                  "region": "US", "sector": "Healthcare"},
    {"symbol": "BMY",   "name": "Bristol-Myers Squibb",        "region": "US", "sector": "Healthcare"},
    {"symbol": "GILD",  "name": "Gilead Sciences",             "region": "US", "sector": "Healthcare"},
    {"symbol": "VRTX",  "name": "Vertex Pharmaceuticals",      "region": "US", "sector": "Healthcare"},
    {"symbol": "REGN",  "name": "Regeneron Pharmaceuticals",   "region": "US", "sector": "Healthcare"},
    {"symbol": "BIIB",  "name": "Biogen Inc.",                 "region": "US", "sector": "Healthcare"},
    {"symbol": "MRNA",  "name": "Moderna Inc.",                "region": "US", "sector": "Healthcare"},
    {"symbol": "MDT",   "name": "Medtronic plc",               "region": "US", "sector": "Healthcare"},
    {"symbol": "CVS",   "name": "CVS Health Corporation",      "region": "US", "sector": "Healthcare"},
    {"symbol": "CI",    "name": "Cigna Group",                 "region": "US", "sector": "Healthcare"},
    {"symbol": "ISRG",  "name": "Intuitive Surgical",          "region": "US", "sector": "Healthcare"},

    # ---------------- US · Industrials & Energy ----------------
    {"symbol": "XOM",   "name": "Exxon Mobil Corporation",     "region": "US", "sector": "Energy"},
    {"symbol": "CVX",   "name": "Chevron Corporation",         "region": "US", "sector": "Energy"},
    {"symbol": "COP",   "name": "ConocoPhillips",              "region": "US", "sector": "Energy"},
    {"symbol": "SLB",   "name": "SLB (Schlumberger)",          "region": "US", "sector": "Energy"},
    {"symbol": "NEE",   "name": "NextEra Energy",              "region": "US", "sector": "Utilities"},
    {"symbol": "DUK",   "name": "Duke Energy",                 "region": "US", "sector": "Utilities"},
    {"symbol": "SO",    "name": "Southern Company",            "region": "US", "sector": "Utilities"},
    {"symbol": "BA",    "name": "Boeing Company",              "region": "US", "sector": "Industrials"},
    {"symbol": "CAT",   "name": "Caterpillar Inc.",            "region": "US", "sector": "Industrials"},
    {"symbol": "DE",    "name": "Deere & Company",             "region": "US", "sector": "Industrials"},
    {"symbol": "GE",    "name": "GE Aerospace",                "region": "US", "sector": "Industrials"},
    {"symbol": "HON",   "name": "Honeywell International",     "region": "US", "sector": "Industrials"},
    {"symbol": "MMM",   "name": "3M Company",                  "region": "US", "sector": "Industrials"},
    {"symbol": "LMT",   "name": "Lockheed Martin",             "region": "US", "sector": "Defense"},
    {"symbol": "RTX",   "name": "RTX Corporation",             "region": "US", "sector": "Defense"},
    {"symbol": "NOC",   "name": "Northrop Grumman",            "region": "US", "sector": "Defense"},
    {"symbol": "GD",    "name": "General Dynamics",            "region": "US", "sector": "Defense"},
    {"symbol": "UPS",   "name": "United Parcel Service",       "region": "US", "sector": "Logistics"},
    {"symbol": "FDX",   "name": "FedEx Corporation",           "region": "US", "sector": "Logistics"},
    {"symbol": "UNP",   "name": "Union Pacific",               "region": "US", "sector": "Logistics"},
    {"symbol": "T",     "name": "AT&T Inc.",                   "region": "US", "sector": "Telecom"},
    {"symbol": "VZ",    "name": "Verizon Communications",      "region": "US", "sector": "Telecom"},
    {"symbol": "TMUS",  "name": "T-Mobile US",                 "region": "US", "sector": "Telecom"},

    # ---------------- India · NSE ----------------
    {"symbol": "RELIANCE.NS",   "name": "Reliance Industries",        "region": "IN", "sector": "Energy"},
    {"symbol": "TCS.NS",        "name": "Tata Consultancy Services",  "region": "IN", "sector": "Technology"},
    {"symbol": "INFY.NS",       "name": "Infosys",                    "region": "IN", "sector": "Technology"},
    {"symbol": "HDFCBANK.NS",   "name": "HDFC Bank",                  "region": "IN", "sector": "Financials"},
    {"symbol": "ICICIBANK.NS",  "name": "ICICI Bank",                 "region": "IN", "sector": "Financials"},
    {"symbol": "SBIN.NS",       "name": "State Bank of India",        "region": "IN", "sector": "Financials"},
    {"symbol": "KOTAKBANK.NS",  "name": "Kotak Mahindra Bank",        "region": "IN", "sector": "Financials"},
    {"symbol": "AXISBANK.NS",   "name": "Axis Bank",                  "region": "IN", "sector": "Financials"},
    {"symbol": "INDUSINDBK.NS", "name": "IndusInd Bank",              "region": "IN", "sector": "Financials"},
    {"symbol": "BAJFINANCE.NS", "name": "Bajaj Finance",              "region": "IN", "sector": "Financials"},
    {"symbol": "BAJAJFINSV.NS", "name": "Bajaj Finserv",              "region": "IN", "sector": "Financials"},
    {"symbol": "SBILIFE.NS",    "name": "SBI Life Insurance",         "region": "IN", "sector": "Financials"},
    {"symbol": "HDFCLIFE.NS",   "name": "HDFC Life Insurance",        "region": "IN", "sector": "Financials"},
    {"symbol": "LICI.NS",       "name": "Life Insurance Corp of India", "region": "IN", "sector": "Financials"},
    {"symbol": "BHARTIARTL.NS", "name": "Bharti Airtel",              "region": "IN", "sector": "Telecom"},
    {"symbol": "HINDUNILVR.NS", "name": "Hindustan Unilever",         "region": "IN", "sector": "Consumer"},
    {"symbol": "ITC.NS",        "name": "ITC Limited",                "region": "IN", "sector": "Consumer"},
    {"symbol": "NESTLEIND.NS",  "name": "Nestle India",               "region": "IN", "sector": "Consumer"},
    {"symbol": "BRITANNIA.NS",  "name": "Britannia Industries",       "region": "IN", "sector": "Consumer"},
    {"symbol": "DABUR.NS",      "name": "Dabur India",                "region": "IN", "sector": "Consumer"},
    {"symbol": "GODREJCP.NS",   "name": "Godrej Consumer Products",   "region": "IN", "sector": "Consumer"},
    {"symbol": "TITAN.NS",      "name": "Titan Company",              "region": "IN", "sector": "Consumer"},
    {"symbol": "ASIANPAINT.NS", "name": "Asian Paints",               "region": "IN", "sector": "Materials"},
    {"symbol": "PIDILITIND.NS", "name": "Pidilite Industries",        "region": "IN", "sector": "Materials"},
    {"symbol": "ULTRACEMCO.NS", "name": "UltraTech Cement",           "region": "IN", "sector": "Materials"},
    {"symbol": "SHREECEM.NS",   "name": "Shree Cement",               "region": "IN", "sector": "Materials"},
    {"symbol": "GRASIM.NS",     "name": "Grasim Industries",          "region": "IN", "sector": "Materials"},
    {"symbol": "TATASTEEL.NS",  "name": "Tata Steel",                 "region": "IN", "sector": "Materials"},
    {"symbol": "JSWSTEEL.NS",   "name": "JSW Steel",                  "region": "IN", "sector": "Materials"},
    {"symbol": "HINDALCO.NS",   "name": "Hindalco Industries",        "region": "IN", "sector": "Materials"},
    {"symbol": "VEDL.NS",       "name": "Vedanta Limited",            "region": "IN", "sector": "Materials"},
    {"symbol": "MARUTI.NS",     "name": "Maruti Suzuki India",        "region": "IN", "sector": "Automotive"},
    {"symbol": "TATAMOTORS.NS", "name": "Tata Motors",                "region": "IN", "sector": "Automotive"},
    {"symbol": "M&M.NS",        "name": "Mahindra & Mahindra",        "region": "IN", "sector": "Automotive"},
    {"symbol": "BAJAJ-AUTO.NS", "name": "Bajaj Auto",                 "region": "IN", "sector": "Automotive"},
    {"symbol": "HEROMOTOCO.NS", "name": "Hero MotoCorp",              "region": "IN", "sector": "Automotive"},
    {"symbol": "EICHERMOT.NS",  "name": "Eicher Motors",              "region": "IN", "sector": "Automotive"},
    {"symbol": "SUNPHARMA.NS",  "name": "Sun Pharmaceutical",         "region": "IN", "sector": "Healthcare"},
    {"symbol": "DRREDDY.NS",    "name": "Dr. Reddy's Laboratories",   "region": "IN", "sector": "Healthcare"},
    {"symbol": "CIPLA.NS",      "name": "Cipla",                      "region": "IN", "sector": "Healthcare"},
    {"symbol": "DIVISLAB.NS",   "name": "Divi's Laboratories",        "region": "IN", "sector": "Healthcare"},
    {"symbol": "APOLLOHOSP.NS", "name": "Apollo Hospitals",           "region": "IN", "sector": "Healthcare"},
    {"symbol": "WIPRO.NS",      "name": "Wipro",                      "region": "IN", "sector": "Technology"},
    {"symbol": "HCLTECH.NS",    "name": "HCL Technologies",           "region": "IN", "sector": "Technology"},
    {"symbol": "TECHM.NS",      "name": "Tech Mahindra",              "region": "IN", "sector": "Technology"},
    {"symbol": "LTIM.NS",       "name": "LTIMindtree",                "region": "IN", "sector": "Technology"},
    {"symbol": "LT.NS",         "name": "Larsen & Toubro",            "region": "IN", "sector": "Industrials"},
    {"symbol": "SIEMENS.NS",    "name": "Siemens India",              "region": "IN", "sector": "Industrials"},
    {"symbol": "ABB.NS",        "name": "ABB India",                  "region": "IN", "sector": "Industrials"},
    {"symbol": "HAVELLS.NS",    "name": "Havells India",              "region": "IN", "sector": "Industrials"},
    {"symbol": "BEL.NS",        "name": "Bharat Electronics",         "region": "IN", "sector": "Defense"},
    {"symbol": "HAL.NS",        "name": "Hindustan Aeronautics",      "region": "IN", "sector": "Defense"},
    {"symbol": "NTPC.NS",       "name": "NTPC Limited",               "region": "IN", "sector": "Utilities"},
    {"symbol": "POWERGRID.NS",  "name": "Power Grid Corporation",     "region": "IN", "sector": "Utilities"},
    {"symbol": "ONGC.NS",       "name": "Oil & Natural Gas Corp",     "region": "IN", "sector": "Energy"},
    {"symbol": "COALINDIA.NS",  "name": "Coal India",                 "region": "IN", "sector": "Energy"},
    {"symbol": "BPCL.NS",       "name": "Bharat Petroleum",           "region": "IN", "sector": "Energy"},
    {"symbol": "IOC.NS",        "name": "Indian Oil Corporation",     "region": "IN", "sector": "Energy"},
    {"symbol": "GAIL.NS",       "name": "GAIL India",                 "region": "IN", "sector": "Energy"},
    {"symbol": "ADANIENT.NS",   "name": "Adani Enterprises",          "region": "IN", "sector": "Industrials"},
    {"symbol": "ADANIPORTS.NS", "name": "Adani Ports & SEZ",          "region": "IN", "sector": "Logistics"},
    {"symbol": "DLF.NS",        "name": "DLF Limited",                "region": "IN", "sector": "Real Estate"},
    {"symbol": "IRCTC.NS",      "name": "Indian Railway Catering (IRCTC)", "region": "IN", "sector": "Travel"},
    {"symbol": "IRFC.NS",       "name": "Indian Railway Finance Corp", "region": "IN", "sector": "Financials"},
    {"symbol": "PAYTM.NS",      "name": "One97 Communications (Paytm)", "region": "IN", "sector": "Technology"},
    {"symbol": "NYKAA.NS",      "name": "FSN E-Commerce (Nykaa)",     "region": "IN", "sector": "Retail"},

    # ---------------- Global / ADRs ----------------
    {"symbol": "TSM",   "name": "Taiwan Semiconductor (ADR)",  "region": "GLOBAL", "sector": "Semiconductors"},
    {"symbol": "ASML",  "name": "ASML Holding (ADR)",          "region": "GLOBAL", "sector": "Semiconductors"},
    {"symbol": "SAP",   "name": "SAP SE (ADR)",                "region": "GLOBAL", "sector": "Technology"},
    {"symbol": "SONY",  "name": "Sony Group (ADR)",            "region": "GLOBAL", "sector": "Technology"},
    {"symbol": "BABA",  "name": "Alibaba Group (ADR)",         "region": "GLOBAL", "sector": "Retail"},
    {"symbol": "PDD",   "name": "PDD Holdings (ADR)",          "region": "GLOBAL", "sector": "Retail"},
    {"symbol": "JD",    "name": "JD.com (ADR)",                "region": "GLOBAL", "sector": "Retail"},
    {"symbol": "NIO",   "name": "NIO Inc. (ADR)",              "region": "GLOBAL", "sector": "Automotive"},
    {"symbol": "TM",    "name": "Toyota Motor (ADR)",          "region": "GLOBAL", "sector": "Automotive"},
    {"symbol": "NVO",   "name": "Novo Nordisk (ADR)",          "region": "GLOBAL", "sector": "Healthcare"},
    {"symbol": "AZN",   "name": "AstraZeneca (ADR)",           "region": "GLOBAL", "sector": "Healthcare"},
    {"symbol": "UL",    "name": "Unilever (ADR)",              "region": "GLOBAL", "sector": "Consumer"},
    {"symbol": "HSBC",  "name": "HSBC Holdings (ADR)",         "region": "GLOBAL", "sector": "Financials"},
    {"symbol": "SHEL",  "name": "Shell plc (ADR)",             "region": "GLOBAL", "sector": "Energy"},
    {"symbol": "BP",    "name": "BP p.l.c. (ADR)",             "region": "GLOBAL", "sector": "Energy"},
    {"symbol": "TTE",   "name": "TotalEnergies (ADR)",         "region": "GLOBAL", "sector": "Energy"},
    {"symbol": "RIO",   "name": "Rio Tinto (ADR)",             "region": "GLOBAL", "sector": "Materials"},
    {"symbol": "BHP",   "name": "BHP Group (ADR)",             "region": "GLOBAL", "sector": "Materials"},
    {"symbol": "INFY",  "name": "Infosys (US ADR)",            "region": "GLOBAL", "sector": "Technology"},
    {"symbol": "WIT",   "name": "Wipro (US ADR)",              "region": "GLOBAL", "sector": "Technology"},
    {"symbol": "IBN",   "name": "ICICI Bank (US ADR)",         "region": "GLOBAL", "sector": "Financials"},
    {"symbol": "HDB",   "name": "HDFC Bank (US ADR)",          "region": "GLOBAL", "sector": "Financials"},

    # ---------------- Index ETFs ----------------
    {"symbol": "SPY",   "name": "SPDR S&P 500 ETF",            "region": "ETF", "sector": "Index ETF"},
    {"symbol": "QQQ",   "name": "Invesco QQQ (Nasdaq 100)",    "region": "ETF", "sector": "Index ETF"},
    {"symbol": "VOO",   "name": "Vanguard S&P 500 ETF",        "region": "ETF", "sector": "Index ETF"},
    {"symbol": "VTI",   "name": "Vanguard Total Stock Market", "region": "ETF", "sector": "Index ETF"},
    {"symbol": "DIA",   "name": "SPDR Dow Jones Industrial",   "region": "ETF", "sector": "Index ETF"},
    {"symbol": "IWM",   "name": "iShares Russell 2000",        "region": "ETF", "sector": "Index ETF"},
    {"symbol": "GLD",   "name": "SPDR Gold Shares",            "region": "ETF", "sector": "Commodity ETF"},
    {"symbol": "NIFTYBEES.NS", "name": "Nippon India Nifty 50 BeES", "region": "ETF", "sector": "Index ETF"},
]

REGION_LABELS = {
    "US": "United States",
    "IN": "India (NSE)",
    "GLOBAL": "Global / ADRs",
    "ETF": "Index & Commodity ETFs",
}

# Extra search keywords so common informal names find the right company.
ALIASES = {
    "GOOGL": ["google"], "GOOG": ["google"],
    "META": ["facebook", "instagram", "whatsapp"],
    "BRK-B": ["berkshire", "buffett"],
    "TCS.NS": ["tata consultancy"],
    "M&M.NS": ["mahindra"],
    "LICI.NS": ["lic"],
    "PAYTM.NS": ["paytm"],
    "NYKAA.NS": ["nykaa"],
    "IRCTC.NS": ["railway"],
    "BAJAJ-AUTO.NS": ["bajaj auto"],
    "GOOGL_": [],
}


def _score(entry: dict, q: str) -> int:
    """Higher = better match. 0 means no match."""
    sym = entry["symbol"].lower()
    name = entry["name"].lower()
    base = sym.split(".")[0]
    extra = " ".join(ALIASES.get(entry["symbol"], []))

    if sym == q or base == q:
        return 100
    if name == q:
        return 95
    if base.startswith(q):
        return 85
    if name.startswith(q):
        return 80
    if any(w.startswith(q) for w in name.split()):
        return 70
    if extra and any(w.startswith(q) for w in extra.split()):
        return 68
    if q in name or (extra and q in extra):
        return 55
    if q in sym:
        return 45
    return 0


def search_catalog(query: str, limit: int = 10) -> list:
    q = (query or "").strip().lower()
    if not q:
        return []
    scored = []
    for e in CATALOG:
        s = _score(e, q)
        if s:
            scored.append((s, e))
    scored.sort(key=lambda t: (-t[0], t[1]["name"]))
    return [
        {**e, "exchange": REGION_LABELS.get(e["region"], e["region"]), "source": "catalog"}
        for _, e in scored[:limit]
    ]


def _yahoo_search_worker(query: str, limit: int):
    """
    Live symbol lookup across Yahoo's full universe. Runs isolated because
    it makes a network call. Tries yfinance's own Search first (it handles
    Yahoo's cookie/crumb dance), then falls back to the plain endpoint.
    """
    results = []

    try:
        import yfinance as yf
        quotes = yf.Search(query, max_results=limit).quotes or []
        for q in quotes:
            sym = q.get("symbol")
            if not sym:
                continue
            results.append({
                "symbol": sym,
                "name": q.get("shortname") or q.get("longname") or sym,
                "exchange": q.get("exchDisp") or q.get("exchange") or "",
                "type": (q.get("quoteType") or "").upper(),
            })
    except Exception:
        pass

    if not results:
        import requests
        r = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": query, "quotesCount": limit, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        r.raise_for_status()
        for q in (r.json().get("quotes") or []):
            sym = q.get("symbol")
            if not sym:
                continue
            results.append({
                "symbol": sym,
                "name": q.get("shortname") or q.get("longname") or sym,
                "exchange": q.get("exchDisp") or q.get("exchange") or "",
                "type": (q.get("quoteType") or "").upper(),
            })

    if not results:
        raise ValueError("no live results")
    return results


def search(query: str, limit: int = 12) -> dict:
    """
    Merged search: curated catalog hits first, then live Yahoo results for
    anything the catalog doesn't cover.
    Returns {"results": [...], "live": bool}
    """
    q = (query or "").strip()
    if not q:
        return {"results": [], "live": False}

    catalog_hits = search_catalog(q, limit=limit)
    have = {e["symbol"].upper() for e in catalog_hits}
    live_ok = False

    if len(catalog_hits) < limit:
        try:
            live = run_with_timeout(_yahoo_search_worker, args=(q, limit), timeout=12)
            live_ok = True
            for e in live:
                if e["symbol"].upper() in have:
                    continue
                # Skip non-equity noise unless nothing else matched
                if e.get("type") not in ("EQUITY", "ETF", "INDEX", "", None) and catalog_hits:
                    continue
                have.add(e["symbol"].upper())
                catalog_hits.append({**e, "source": "live"})
                if len(catalog_hits) >= limit:
                    break
        except (SubprocessCallFailed, Exception):
            live_ok = False

    return {"results": catalog_hits[:limit], "live": live_ok}


def catalog_grouped() -> dict:
    """Full bundled catalog grouped by region then sector, for browsing."""
    out = {}
    for e in CATALOG:
        region = e["region"]
        out.setdefault(region, {}).setdefault(e["sector"], []).append(
            {"symbol": e["symbol"], "name": e["name"]}
        )
    return {
        "labels": REGION_LABELS,
        "groups": out,
        "total": len(CATALOG),
    }
