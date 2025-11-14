"""Simple CLI to harvest a subset of sources."""

import argparse
import json

from db import get_sources, init_db
from harvest import harvest_source


def main(limit: int):
    init_db()
    selected = get_sources(limit if limit > 0 else None)
    results = []
    for source in selected:
        result = harvest_source(source["url"], source.get("label"))
        results.append({
            "label": source.get("label"),
            "url": source["url"],
            "inserted": result["inserted"],
            "links_found": result["links_found"],
            "fetched": result["fetched"],
        })
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Harvest publication sources")
    parser.add_argument("--limit", type=int, default=3, help="Number of sources to harvest (<= len list)")
    args = parser.parse_args()
    main(args.limit)
