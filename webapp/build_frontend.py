#!/usr/bin/env python3

import glob
import json


def get_asset_paths(is_dev: bool = False) -> dict[str, str | None]:
    """Get the correct asset paths for dev or production."""
    if is_dev:
        # In dev mode, Vite serves from the dev server
        return {
            "js": "http://localhost:5173/src/main.js",
            "vite_client": "http://localhost:5173/@vite/client",
            "css": None,  # CSS is injected by Vite in dev mode
        }
    else:
        # In production, find the latest built file
        js_files = glob.glob("dist/js/main-*.js")
        css_files = glob.glob("dist/assets/main-*.css")

        return {
            "js": f"/{js_files[0]}" if js_files else "/dist/js/main.js",
            "css": f"/{css_files[0]}" if css_files else None,
        }


if __name__ == "__main__":
    import sys

    is_dev = len(sys.argv) > 1 and sys.argv[1] == "--dev"
    assets = get_asset_paths(is_dev)
    print(json.dumps(assets))
