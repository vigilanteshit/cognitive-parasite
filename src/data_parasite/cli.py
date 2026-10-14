"""Local entry point. Internet hosting is intentionally not an implicit default."""

import argparse
import asyncio
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Cognitive Parasite research workbench")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local API and built frontend")
    serve.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    reindex = commands.add_parser(
        "reindex", help="Re-embed a stopped SQLite store into a new directory"
    )
    reindex.add_argument("--source", type=Path, required=True)
    reindex.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    elif args.command == "reindex":
        from .config import Settings
        from .providers import ModelRouter
        from .reindex import reindex_sqlite

        async def migrate():
            router = ModelRouter(Settings())
            try:
                count = await reindex_sqlite(args.source, args.target, router)
                print(
                    f"Reindexed {count} memories into {args.target}. Verify before switching data directories."
                )
            finally:
                await router.close()

        asyncio.run(migrate())


if __name__ == "__main__":
    main()
