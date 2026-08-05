"""
전북대학교 학생공지/교내공지 게시판을 크롤링해서
관심 키워드가 제목에 포함된 글만 골라 data/notices.json 에 저장한다.

실행: python tools/crawl_notices.py
"""
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.jbnu.ac.kr"
BOARDS = {
    "교내공지": f"{BASE_URL}/web/news/notice/sub01.do",
    "학생공지": f"{BASE_URL}/web/news/notice/sub02.do",
}
DETAIL_URL_TMPL = f"{BASE_URL}/web/Board/{{post_id}}/detailView.do"

KEYWORDS = ["모집", "프로젝트", "장학금", "선발", "AI", "빅데이터", "산업"]

# 오늘 포함 최근 N일 이내 글만 대상으로 함 (주말 등으로 실행이 하루 밀려도 놓치지 않도록 여유를 둠)
RECENT_DAYS = 3

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "notices.json"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_list_html(board_url: str, page_index: int = 1, retries: int = 3) -> str:
    last_error = None
    for attempt in range(retries):
        try:
            resp = requests.get(board_url, params={"pageIndex": page_index}, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            return resp.text
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(5)
    raise last_error


def parse_list(html: str, board_name: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tbody tr.tr-normal")
    items = []
    for row in rows:
        title_a = row.select_one("a.title")
        if not title_a:
            continue

        onclick = title_a.get("onclick", "")
        m = re.search(r"pf_DetailMove\('(\d+)'\)", onclick)
        if not m:
            continue
        post_id = m.group(1)

        # 아이콘 alt 텍스트("공지" 등)가 섞여 들어오지 않도록 텍스트 노드만 모음
        title = "".join(
            t for t in title_a.find_all(string=True, recursive=True)
        ).strip()

        date_li = row.select_one("ul.etc-list li")
        date_text = date_li.get_text(strip=True) if date_li else ""

        items.append(
            {
                "board": board_name,
                "title": title,
                "date": date_text,
                "link": DETAIL_URL_TMPL.format(post_id=post_id),
            }
        )
    return items


def is_recent(date_text: str) -> bool:
    try:
        d = datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        return False
    return (datetime.now().date() - d) <= timedelta(days=RECENT_DAYS)


def matches_keyword(title: str) -> bool:
    return any(keyword in title for keyword in KEYWORDS)


def crawl_board(board_name: str, board_url: str) -> list[dict]:
    collected = []
    page = 1
    while True:
        if page > 1:
            time.sleep(2)  # 연속 요청 시 서버가 봇으로 의심해 연결을 끊는 것을 방지
        try:
            html = fetch_list_html(board_url, page)
        except requests.exceptions.RequestException as e:
            # 한 페이지가 끝까지 실패해도 이미 수집한 내용은 버리지 않고 이번 실행은 여기서 마무리
            print(f"[경고] {board_name} {page}페이지 수집 실패, 이번 실행은 여기까지만 반영: {e}")
            break
        items = parse_list(html, board_name)
        if not items:
            break

        recent_items = [i for i in items if is_recent(i["date"])]
        collected.extend(recent_items)

        # 이 페이지의 글이 전부 최근 기준보다 오래됐으면 더 넘어갈 필요 없음
        if len(recent_items) < len(items):
            break
        page += 1
        if page > 10:  # 안전장치: 무한 루프 방지
            break
    return collected


def load_existing() -> list[dict]:
    if DATA_PATH.exists():
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def post_id_from_link(link: str) -> int:
    m = re.search(r"/Board/(\d+)/", link)
    return int(m.group(1)) if m else 0


def merge(existing: list[dict], new_items: list[dict]) -> list[dict]:
    seen_links = {item["link"] for item in existing}
    merged = list(existing)
    for item in new_items:
        if item["link"] not in seen_links:
            merged.append(item)
            seen_links.add(item["link"])
    # 같은 날짜 안에서는 게시글 번호가 클수록(=최근에 올라온 글) 위로 오도록 정렬
    merged.sort(key=lambda i: (i["date"], post_id_from_link(i["link"])), reverse=True)
    return merged


def main():
    all_recent = []
    for i, (board_name, board_url) in enumerate(BOARDS.items()):
        if i > 0:
            time.sleep(2)
        all_recent.extend(crawl_board(board_name, board_url))

    filtered = [item for item in all_recent if matches_keyword(item["title"])]

    existing = load_existing()
    merged = merge(existing, filtered)

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"이번 실행에서 새로 발견한 글: {len(filtered)}개")
    print(f"전체 누적 글: {len(merged)}개")


if __name__ == "__main__":
    main()
