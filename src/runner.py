import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests

# Ensure the `src` folder (where this file lives) is on sys.path so we can import sibling packages
CURRENT_FILE = Path(__file__).resolve()
SRC_DIR = CURRENT_FILE.parent
PROJECT_ROOT = SRC_DIR.parent

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from extractors.yelp_parser import parse_search_results, parse_business_page  # type: ignore
from outputs.exporters import export_to_json  # type: ignore  # noqa: E402

logger = logging.getLogger("yelp_scraper")

def load_settings() -> Dict[str, Any]:
    """
    Load scraper settings from the example settings file.

    In a real deployment, users can copy this file to `settings.json` and adjust values.
    For this demo implementation, we just use `settings.example.json` directly.
    """
    config_path = SRC_DIR / "config" / "settings.example.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.debug("Loading settings from %s", config_path)
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)

def load_inputs(inputs_path: Path) -> List[str]:
    """
    Load search queries or Yelp URLs from a text file.

    Blank lines and lines starting with '#' are ignored.
    """
    if not inputs_path.exists():
        raise FileNotFoundError(f"Input file not found: {inputs_path}")

    queries: List[str] = []
    with inputs_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            queries.append(line)

    logger.info("Loaded %d input entries from %s", len(queries), inputs_path)
    return queries

def build_search_url(base_url: str, search_path: str, query: str, location: str | None = None) -> str:
    from urllib.parse import urlencode, urljoin

    params: Dict[str, str] = {"find_desc": query}
    if location:
        params["find_loc"] = location

    query_string = urlencode(params)
    return urljoin(base_url, search_path) + f"?{query_string}"

def fetch_html(url: str, headers: Dict[str, str], timeout: int) -> str | None:
    """
    Fetch HTML content from a URL with basic error handling.
    """
    try:
        logger.debug("Fetching URL: %s", url)
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

def enrich_businesses_with_details(
    base_url: str,
    businesses: List[Dict[str, Any]],
    headers: Dict[str, str],
    timeout: int,
    max_detail_requests: int,
) -> List[Dict[str, Any]]:
    """
    For each business that has a `url`, fetch the business page and merge detailed data.
    To avoid hammering Yelp, we limit the number of detail requests per run.
    """
    enriched: List[Dict[str, Any]] = []
    detail_count = 0

    for biz in businesses:
        url = biz.get("url")
        if not url or detail_count >= max_detail_requests:
            enriched.append(biz)
            continue

        html = fetch_html(url, headers=headers, timeout=timeout)
        if not html:
            enriched.append(biz)
            continue

        details = parse_business_page(html, url=url)
        merged = {**biz, **details}
        enriched.append(merged)
        detail_count += 1

    logger.info("Fetched detailed pages for %d businesses", detail_count)
    return enriched

def run_scraper(
    inputs_path: Path,
    output_path: Path,
    location: str | None = None,
    max_results: int | None = None,
) -> None:
    """
    Main orchestration logic for the scraper:
    - Load config
    - Load inputs
    - For each input:
        * If it's a URL -> fetch & parse as a business page
        * Otherwise treat it as a search query
    - Export results as JSON
    """
    settings = load_settings()

    base_url: str = settings.get("base_url", "https://www.yelp.com")
    search_path: str = settings.get("search_path", "/search")
    timeout_seconds: int = int(settings.get("timeout_seconds", 10))
    max_results_per_query: int = int(settings.get("max_results_per_query", 50))
    max_detail_requests_per_query: int = int(settings.get("max_detail_requests_per_query", 10))

    headers = {
        "User-Agent": settings.get(
            "user_agent",
            "Mozilla/5.0 (compatible; YelpScraper/1.0; +https://bitbash.dev)",
        )
    }

    queries = load_inputs(inputs_path)
    all_results: List[Dict[str, Any]] = []

    for raw in queries:
        raw = raw.strip()
        if not raw:
            continue

        logger.info("Processing input: %s", raw)

        if raw.startswith("http://") or raw.startswith("https://"):
            # Treat as a direct Yelp business URL
            html = fetch_html(raw, headers=headers, timeout=timeout_seconds)
            if not html:
                continue
            biz = parse_business_page(html, url=raw)
            all_results.append(biz)
        else:
            # Treat as a search query
            search_url = build_search_url(base_url, search_path, raw, location=location)
            html = fetch_html(search_url, headers=headers, timeout=timeout_seconds)
            if not html:
                continue

            businesses = parse_search_results(
                html,
                base_url=base_url,
                max_results=max_results_per_query,
            )
            businesses = enrich_businesses_with_details(
                base_url=base_url,
                businesses=businesses,
                headers=headers,
                timeout=timeout_seconds,
                max_detail_requests=max_detail_requests_per_query,
            )
            all_results.extend(businesses)

    if max_results is not None:
        all_results = all_results[:max_results]

    # Ensure the output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    export_to_json(all_results, output_path)
    logger.info("Scraping completed. Saved %d records to %s", len(all_results), output_path)

def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Yelp Scraper - extract business details and reviews into JSON."
    )
    default_input = PROJECT_ROOT / "data" / "inputs.sample.txt"
    default_output = PROJECT_ROOT / "data" / "yelp_results.json"

    parser.add_argument(
        "-i",
        "--inputs",
        type=Path,
        default=default_input,
        help=f"Path to input file with search terms or Yelp URLs (default: {default_input})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_output,
        help=f"Path for JSON output file (default: {default_output})",
    )
    parser.add_argument(
        "-l",
        "--location",
        type=str,
        default=None,
        help="Optional location to bias search (e.g., 'San Francisco, CA').",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Optional global cap on total number of businesses to return.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging.",
    )
    return parser.parse_args(argv)

def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
    )

def main(argv: List[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging(args.verbose)

    try:
        run_scraper(
            inputs_path=args.inputs,
            output_path=args.output,
            location=args.location,
            max_results=args.max_results,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error while running scraper: %s", exc)
        sys.exit(1)

if __name__ == "__main__":
    main()