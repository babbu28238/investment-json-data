import json, re
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATA = Path("data")
DATA.mkdir(exist_ok=True)
OUT = DATA / "stock_universe_a424.json"
HEADERS = {"User-Agent":"Mozilla/5.0","Referer":"https://finance.naver.com/"}

def pykrx_rows():
    rows = []
    try:
        from pykrx import stock
        for market in ["KOSPI","KOSDAQ"]:
            for code in stock.get_market_ticker_list(market=market):
                name = stock.get_market_ticker_name(code)
                if code and name:
                    rows.append({"code":code,"name":name,"market":market,"sector":""})
    except Exception as e:
        print("pykrx failed:", e)
    return rows

def naver_rows():
    rows = []
    for sosok, market in [("0","KOSPI"),("1","KOSDAQ")]:
        for page in range(1,80):
            url=f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            try:
                html=requests.get(url,headers=HEADERS,timeout=12).text
                soup=BeautifulSoup(html,"html.parser")
                found=0
                for a in soup.select("a.tltle"):
                    href=a.get("href","")
                    m=re.search(r"code=(\d{6})",href)
                    name=a.get_text(strip=True)
                    if m and name:
                        rows.append({"code":m.group(1),"name":name,"market":market,"sector":""})
                        found+=1
                if found==0 and page>3:
                    break
            except Exception as e:
                print("naver failed:", market, page, e)
                if page>3:
                    break
    return rows

rows = pykrx_rows()
source = "pykrx"
if len(rows) < 1000:
    rows = naver_rows()
    source = "naver_market_sum"
rows.append({"code":"141080","name":"리가켐바이오","market":"KOSDAQ","sector":"바이오"})
seen=set(); out=[]
for r in rows:
    code=str(r["code"]).zfill(6)
    if code not in seen:
        seen.add(code)
        out.append({"code":code,"name":r["name"],"market":r.get("market",""),"sector":r.get("sector","")})
result={"updatedAt":datetime.now().isoformat(timespec="seconds"),"source":source,"count":len(out),"stocks":sorted(out,key=lambda x:(x["market"],x["name"]))}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"source":source,"count":len(out)},ensure_ascii=False,indent=2))
