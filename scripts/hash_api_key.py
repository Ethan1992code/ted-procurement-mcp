from __future__ import annotations

import argparse
import hashlib


def main() -> None:
    parser = argparse.ArgumentParser(description="Hash a raw MCP API key with SHA-256 for storage.")
    parser.add_argument("raw_key")
    args = parser.parse_args()
    print(hashlib.sha256(args.raw_key.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    main()
