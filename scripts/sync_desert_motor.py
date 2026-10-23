"""Sync public Desert Motor listings to a GitHub Pages JSON snapshot.
No login bypass; if extraction fails, keep existing data unchanged.
"""
import json, re, time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

HOST = "https://desert-motor.com"
FILE = Path("desert-motor-catalog.json")
CATEGORIES = [
 "Armor, Bumpers & Underbody Protection",
 "Coolant system & Air condition",
 "Engine & Performance Parts",
 "Grease, Oil & Oil Filters",
 "Lighting, Electrical & Accessories",
 "Recover, Camping & Off-road Gear",
 "Suspension & Lift Kits",
 "Wheels & Brakes"
]
def category(value):
 t = str(value or "").lower().replace("\xa0", " ")
 for name in CATEGORIES:
  if name.lower() in t:
   return name
 for s,idx in (("suspension",6),("lift kit",6),("wheel",7),("brake",7),("bumper",0),("armor",0),("lighting",4),("electrical",4),("engine",2),("performance",2),("recover",5),("camping",5),("coolant",1),("air condition",1),("grease",3),("filter",3)):
  if s in t: return CATEGORIES[idx]
 return None
def add(obj, products):
 if not isinstance(obj,dict):return
 name=str(obj.get("name") or obj.get("title") or "").strip()
 if not 5<=len(name)<=260:return
 cat=obj.get("category") or obj.get("category_name") or ""
 if isinstance(cat,dict):cat=cat.get("name","")
 cat=category(cat)
 url=str(obj.get("url") or obj.get("link") or "")
 if not url:
  pid=obj.get("id") or obj.get("product_id")
  if pid and re.fullmatch(r"[0-9]{3,9}",str(pid)):url=HOST+"/products/"+str(pid)
 if url.startswith("/products/"):url=HOST+url
 if not cat or not url.startswith(HOST+"/products/"):return
 price=obj.get("price") or 0
 if isinstance(price,dict):price=price.get("amount") or price.get("value") or 0
 try:price=float(re.sub(r"[^0-9.]","",str(price)))
 except ValueError:price=0
 products[url]=dict(name=name,category=cat,price=price,url=url,
  sku=str(obj.get("sku") or ""),fitment=str(obj.get("fitment") or ""))
def scan(x,products,depth=0):
 if depth>7:return
 if isinstance(x,list):
  for v in x[:1000]:scan(v,products,depth+1)
 if isinstance(x,dict):
  add(x,products)
  for key,val in x.items():
   if depth<3 or key.lower() in ("items","data","products","results","product","edges","node","records"):
    scan(val,products,depth+1)
def main():
 products={}
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
  ctx=browser.new_context(locale="en-US")
  ctx.route("**/*",lambda route: route.abort() if route.request.resource_type in ("image","media","font") else route.continue_())
  page=ctx.new_page()
  def collect(response):
   try:
    if response.status==200 and "desert-motor.com" in response.url and "json" in response.headers.get("content-type",""):
     scan(response.json(),products)
   except Exception:pass
  page.on("response",collect)
  missed=0
  import requests
  for diagurl in [HOST+"/products?page=1&page_size=24&sort=newest&with_facets=1", HOST+"/",HOST+"/robots.txt"]:
   try:
    rr=requests.get(diagurl,timeout=12,headers={"User-Agent":"Mozilla/5.0 (compatible; ProductCatalogBot/1.0)"})
    print("RAW REQUEST",diagurl,rr.status_code,len(rr.content),"end",rr.url,"text",rr.text[:900],"scripts",re.findall(r'<script[^>]+src="([^"]+)"',rr.text)[:6],flush=True)
   except Exception as ex:print("REQUEST ERROR",str(ex)[:160],flush=True)
  page.on("pageerror",lambda ex:print("PAGE ERR",str(ex)[:280],flush=True))
  page.on("console",lambda m:print("CONSOLE",m.type,m.text[:240],flush=True) if m.type=="error" else None)
  page.on("requestfailed",lambda rq:print("REQ FAILED",rq.url[:180],rq.failure,flush=True))
  for number in range(1,83):
   try:
    page.goto(f"{HOST}/products?page={number}&page_size=24&sort=newest&with_facets=1",wait_until="domcontentloaded",timeout=35000)
    page.wait_for_timeout(7000 if number==1 else 900)
    if number==1:
     print("DEBUG page title:",page.title(),flush=True)
     print("DEBUG body:",page.locator("body").inner_text(timeout=3000)[:1400],flush=True)\n     print("DEBUG HTML:",page.content()[:1800],flush=True)
     print("DEBUG links:",page.evaluate('''() => [...document.querySelectorAll("a[href]")].map(x=>x.href).slice(0,35)'''),flush=True)
     print("DEBUG network urls:",[x.url for x in page.context.pages][:3],flush=True)
    candidates=page.evaluate("""() => Array.from(document.querySelectorAll('a[href*="/products/"]')).map(a => {
       const e=a.closest("article,li,[data-product-id]")||a.parentElement?.parentElement;
       return {url:a.href,name:(a.innerText||e?.querySelector("h2,h3,h4")?.innerText||"").trim(),description:(e?.innerText||"").slice(0,800)};
    })""")
    added=0
    for item in candidates:
     if not item["name"]:continue
     m=re.search(r"(?:QAR|QR)\s*([\d,.]+)",item["description"],re.I)
     before=len(products)
     add(dict(name=item["name"],category=item["description"],price=m.group(1) if m else 0,url=item["url"]),products)
     added+=len(products)-before
    print("page",number,"found",len(products),flush=True)
    missed=missed+1 if not candidates and not added else 0
    if missed>=4:break
   except Exception as ex:
    print("page error",number,str(ex)[:140],flush=True)
    missed+=1
    if missed>=4:break
   time.sleep(0.4)
  browser.close()
 if not products:
  print("No reliable product URLs discovered; keeping previous catalog")
  return
 try:
  old=json.loads(FILE.read_text())
  for item in old.get("products",[]):add(item,products)
 except (FileNotFoundError,ValueError):pass
 data={"updated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),"source":HOST+"/products","currency":"QAR","note":"Snapshot only; stock, price and vehicle compatibility require vendor confirmation.","products":list(products.values())}
 FILE.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n")
 print("saved",len(products),"products")
if __name__=="__main__":main()
