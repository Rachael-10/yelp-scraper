from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .text_utils import clean_text, extract_rating_from_aria

@dataclass
class Review:
    author: Optional[str]
    rating: Optional[float]
    text: Optional[str]

@dataclass
class Business:
    businessName: Optional[str]
    address: Optional[str]
    phoneNumber: Optional[str]
    rating: Optional[float]
    reviewText: Optional[str]
    url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def _extract_business_cards(soup: BeautifulSoup, base_url: str, max_results: int) -> List[Dict[str, Any]]:
    """
    Extract basic business info from a Yelp search results page.

    This function aims to be resilient by using generic selectors instead of fragile class names.
    """
    seen_urls: set[str] = set()
    results: List[Dict[str, Any]] = []

    # Strategy:
    # - Find links that look like /biz/<slug>
    # - Derive name from link text
    # - Look nearby for rating container (aria-label with "star rating")
    for link in soup.select("a[href^='/biz/']"):
        href = link.get("href")
        if not href:
            continue

        # Strip query params
        href = href.split("?", 1)[0]
        full_url = base_url.rstrip("/") + href

        if full_url in seen_urls:
            continue

        name = clean_text(link.get_text(" ", strip=True))
        if not name:
            continue

        # Try to find rating near the link
        rating_value: Optional[float] = None
        current = link
        for _ in range(4):  # limited hops to keep it cheap
            current = current.parent
            if current is None:
                break
            rating_node = current.find(attrs={"aria-label": re.compile(r"star rating", re.I)})
            if rating_node and rating_node.has_attr("aria-label"):
                rating_value = extract_rating_from_aria(rating_node["aria-label"])
                if rating_value is not None:
                    break

        result = {
            "businessName": name,
            "address": None,
            "phoneNumber": None,
            "rating": rating_value,
            "reviewText": None,
            "url": full_url,
        }
        seen_urls.add(full_url)
        results.append(result)

        if len(results) >= max_results:
            break

    return results

def parse_search_results(html: str, base_url: str = "https://www.yelp.com", max_results: int = 50) -> List[Dict[str, Any]]:
    """
    Parse a Yelp search results HTML page and return a list of business dictionaries.

    The output is aligned with the README's example structure.
    """
    soup = BeautifulSoup(html, "lxml")
    businesses = _extract_business_cards(soup, base_url=base_url, max_results=max_results)
    return businesses

def _extract_address(soup: BeautifulSoup) -> Optional[str]:
    # Try several strategies to find address text on a business page
    # 1. Look for schema.org postal address
    address_candidate = soup.find(attrs={"data-testid": re.compile("address", re.I)})
    if address_candidate:
        return clean_text(address_candidate.get_text(" ", strip=True))

    # 2. Look for elements with "address" in aria-label or title
    for elem in soup.find_all(True, attrs={"aria-label": re.compile("address", re.I)}):
        text = clean_text(elem.get_text(" ", strip=True))
        if text:
            return text

    # 3. Fallback: any `<address>` tag
    addr_tag = soup.find("address")
    if addr_tag:
        return clean_text(addr_tag.get_text(" ", strip=True))

    return None

def _extract_phone(soup: BeautifulSoup) -> Optional[str]:
    # Yelp often shows phone numbers in buttons or plain text.
    # We'll search for a pattern resembling a phone number.
    text = soup.get_text(" ", strip=True)
    patterns = [
        r"\(\d{3}\)\s*\d{3}-\d{4}",  # (555) 555-1234
        r"\d{3}-\d{3}-\d{4}",        # 555-555-1234
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None

def _extract_overall_rating(soup: BeautifulSoup) -> Optional[float]:
    # Look for a prominent element with aria-label containing "star rating"
    rating_node = soup.find(attrs={"aria-label": re.compile(r"star rating", re.I)})
    if rating_node and rating_node.has_attr("aria-label"):
        return extract_rating_from_aria(rating_node["aria-label"])
    return None

def _extract_top_review(soup: BeautifulSoup) -> Optional[Review]:
    """
    Extract a single prominent review (if present) from the business page.
    """
    # Heuristic: look for elements that might represent review containers
    # with a rating and some text.
    review_blocks = soup.find_all(attrs={"itemprop": re.compile("review", re.I)})
    if not review_blocks:
        # Fallback: search by data-testid marker commonly used by Yelp
        review_blocks = soup.find_all(attrs={"data-testid": re.compile("review", re.I)})

    for block in review_blocks:
        # Extract review text
        text = clean_text(block.get_text(" ", strip=True))
        if not text:
            continue

        # Extract rating within the block if available
        rating_val: Optional[float] = None
        rating_node = block.find(attrs={"aria-label": re.compile(r"star rating", re.I)})
        if rating_node and rating_node.has_attr("aria-label"):
            rating_val = extract_rating_from_aria(rating_node["aria-label"])

        # Extract author if available
        author = None
        author_node = block.find(attrs={"itemprop": re.compile("author", re.I)})
        if author_node:
            author = clean_text(author_node.get_text(" ", strip=True))

        return Review(author=author, rating=rating_val, text=text)

    return None

def parse_business_page(html: str, url: Optional[str] = None) -> Dict[str, Any]:
    """
    Parse a Yelp business detail page into a Business dictionary.
    """
    soup = BeautifulSoup(html, "lxml")

    # Business name
    name = None
    # 1. Look for schema.org name
    name_node = soup.find(attrs={"itemprop": re.compile("name", re.I)})
    if name_node:
        name = clean_text(name_node.get_text(" ", strip=True))
    if not name:
        # 2. Fallback: first <h1>
        h1 = soup.find("h1")
        if h1:
            name = clean_text(h1.get_text(" ", strip=True))

    address = _extract_address(soup)
    phone = _extract_phone(soup)
    rating = _extract_overall_rating(soup)
    top_review = _extract_top_review(soup)

    business = Business(
        businessName=name,
        address=address,
        phoneNumber=phone,
        rating=rating if rating is not None else (top_review.rating if top_review else None),
        reviewText=top_review.text if top_review else None,
        url=url,
    )

    return business.to_dict()