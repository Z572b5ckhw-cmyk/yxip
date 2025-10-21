#!/usr/bin/env python3
"""
高可用反爬版 CloudFlare IP 采集器
运行前：pip install -U requests[socks] beautifulsoup4 fake-useragent undetected-chromedriver
"""

import os
import re
import time
import random
import logging
from typing import Set, List

import requests
from bs4 import BeautifulSoup
# 修复 fake_useragent 报错：禁用远程服务器，使用本地缓存
from fake_useragent import UserAgent
import undetected_chromedriver as uc

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
OUTPUT_FILE = "ip.txt"
RETRY_TIMES = 3
TIMEOUT = 8
RANDOM_JITTER = (1, 3)

# 目标站点（已移除失效的 cf.vvhan.com）
URLS = [
    'https://ip.164746.xyz', 
    'https://cf.090227.xyz', 
    'https://stock.hostmonit.com/CloudFlareYes',
    'https://ip.haogege.xyz/',
    'https://ct.090227.xyz',
    'https://cmcc.090227.xyz',    
    'https://api.uouin.com/cloudflare.html',
    'https://addressesapi.090227.xyz/CloudFlareYes',
    'https://addressesapi.090227.xyz/ip.164746.xyz',
    'https://ipdb.api.030101.xyz/?type=cfv4;proxy',
    'https://ipdb.api.030101.xyz/?type=bestcf&country=true',
    'https://ipdb.api.030101.xyz/?type=bestproxy&country=true',
    'https://www.wetest.vip/page/edgeone/address_v4.html',
    'https://www.wetest.vip/page/cloudfront/address_v4.html',
    'https://www.wetest.vip/page/cloudflare/address_v4.html'
]

PROXY_POOL_URL = "http://proxylist.geonode.com/api/proxy-list?limit=50&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps"

# ---------- 工具 ----------
class ProxyRotator:
    def __init__(self, proxy_api: str):
        self.api = proxy_api
        self.proxies: List[str] = []
        self._fetch_proxies()

    def _fetch_proxies(self):
        try:
            data = requests.get(self.api, timeout=10).json()
            self.proxies = [f"http://{p['ip']}:{p['port']}" for p in data.get("data", [])]
            random.shuffle(self.proxies)
            logging.info("代理池刷新，可用代理数：%d", len(self.proxies))
        except Exception as e:
            logging.warning("代理池获取失败: %s", e)

    def get(self) -> str:
        if not self.proxies:
            self._fetch_proxies()
        return self.proxies.pop() if self.proxies else ""

proxy_rotator = ProxyRotator(PROXY_POOL_URL)
# 修复 fake_useragent 503 错误：禁用远程服务器
ua = UserAgent(use_cache_server=False)

def _random_headers() -> dict:
    return {
        "User-Agent": ua.random,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.google.com/",
        "DNT": "1",
    }

def _sleep():
    time.sleep(random.uniform(*RANDOM_JITTER))

def _sort_ip(ip: str):
    return tuple(map(int, ip.split(".")))

# ---------- 请求 ----------
def requests_fallback(url: str) -> str:
    for attempt in range(1, RETRY_TIMES + 1):
        proxy = proxy_rotator.get()
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            logging.info("尝试[%d/%d] %s %s", attempt, RETRY_TIMES, url, proxy or "")
            resp = requests.get(
                url,
                headers=_random_headers(),
                proxies=proxies,
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 503, 520, 521, 522, 525):
                raise RuntimeError("CF Shield")
        except Exception as e:
            logging.warning("requests 失败: %s", e)
        _sleep()
    return _selenium_get(url)

def _selenium_get(url: str) -> str:
    logging.info("启用 Undetected Chrome: %s", url)
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.headless = True
    driver = uc.Chrome(options=options)
    try:
        driver.get(url)
        time.sleep(5)
        html = driver.page_source
        return html
    finally:
        driver.quit()

# ---------- 主流程 ----------
def crawl() -> Set[str]:
    ips = set()
    for u in URLS:
        try:
            html = requests_fallback(u.strip())
            found = IP_PATTERN.findall(html)
            ips.update(found)
            logging.info("从 %s 提取到 %d 个 IP", u, len(found))
        except Exception as e:
            logging.error("最终失败 %s : %s", u, e)
        _sleep()
    return ips

def save(ips: Set[str]):
    if not ips:
        logging.warning("未采集到任何 IP，保留旧的 ip.txt")
        return  # 没抓到新IP时，不修改旧文件
    sorted_ips = sorted(ips, key=_sort_ip)
    # 直接覆盖旧文件（而不是提前删除）
    with open(OUTPUT_FILE, "w", encoding="utf8") as f:
        f.write("\n".join(sorted_ips) + "\n")
    logging.info("已保存 %d 条 IP 到 %s（覆盖旧文件）", len(sorted_ips), OUTPUT_FILE)

if __name__ == "__main__":
    # ！！！关键修改：删除了提前删除 ip.txt 的代码！！！
    ip_set = crawl()  # 先抓取新IP
    save(ip_set)      # 抓到新IP才覆盖，没抓到就保留旧文件
