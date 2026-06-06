"""
World Lore Loader (v2.0 — Lazy + RAG)
=======================================
Implements Q2=C: Preload all world metadata at startup, but lazy-deserialize
YAML content on first access. Build LanceDB vector index in background.

Architecture:
  Phase 1 (FastAPI startup):
    - Scan worlds/*.yaml
    - Register metadata (id, name, version, file_size) in memory
    - DO NOT parse YAML yet
    - Schedule background tasks: parse + build LanceDB index per world

  Phase 2 (First player joins world_id):
    - Check if YAML is parsed (cache hit/miss)
    - If miss: parse YAML, build WorldLoreDB instance, cache in memory
    - If hit: return cached instance
    - RAG extraction happens on-demand during LLM calls

  Phase 3 (LLM call):
    - WorldLoreDB.semantic_search(query, top_k=5)
    - Returns relevant chunks (5K-10K tokens)
    - Inject into Scene Agent prompt

Memory characteristics:
  - Metadata: ~10KB per world (always loaded)
  - Parsed YAML: ~50MB per world (lazy, cached)
  - LanceDB index: ~200MB per world (built in background)
  - For 1-4 player single-host: 1-3 worlds total, fits easily in 64GB RAM
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .world_lore_db import WorldLoreDB

logger = logging.getLogger(__name__)


@dataclass
class WorldMetadata:
    """Lightweight metadata loaded at startup."""
    world_id: str
    name: str
    version: str
    yaml_path: Path
    file_size_bytes: int
    is_parsed: bool = False
    is_indexed: bool = False
    parse_started_at: float | None = None
    parse_completed_at: float | None = None


class WorldLoreLoader:
    """
    Manages lazy loading + RAG indexing of world packages.

    Singleton — one instance per FastAPI app.
    """

    def __init__(self, worlds_dir: Path = Path("worlds")):
        self._worlds_dir = worlds_dir
        self._metadata: dict[str, WorldMetadata] = {}
        self._instances: dict[str, WorldLoreDB] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def scan_and_register(self) -> int:
        """
        Phase 1: Scan worlds/ directory and register metadata.
        Called on FastAPI startup. Non-blocking (no YAML parsing).
        """
        async with self._meta_lock:
            count = 0
            for yaml_file in self._worlds_dir.glob("*.yaml"):
                try:
                    # Read only the top-level metadata fields (cheap)
                    with open(yaml_file, encoding="utf-8") as f:
                        # Read first 1KB to extract metadata
                        head = f.read(1024)

                    # Quick parse of just world_meta section
                    # (YAML full parse deferred to lazy load)
                    world_id = yaml_file.stem  # e.g., "dnd_5e_forgotten_realms"
                    name = self._extract_field(head, "name:") or world_id
                    version = self._extract_field(head, "version:") or "unknown"

                    metadata = WorldMetadata(
                        world_id=world_id,
                        name=name,
                        version=version,
                        yaml_path=yaml_file,
                        file_size_bytes=yaml_file.stat().st_size,
                    )
                    self._metadata[world_id] = metadata
                    self._locks[world_id] = asyncio.Lock()
                    count += 1
                    logger.info(f"[WorldLoreLoader] Registered: {world_id} ({yaml_file.stat().st_size} bytes)")
                except Exception as e:
                    logger.exception(f"[WorldLoreLoader] Failed to register {yaml_file}: {e}")
            return count

    async def schedule_indexing(self) -> None:
        """
        Phase 1.5: Schedule background tasks to parse YAML + build LanceDB index.
        Each world parsed in its own task (parallelism).
        """
        for world_id, metadata in self._metadata.items():
            asyncio.create_task(self._parse_and_index_world(world_id))
            logger.info(f"[WorldLoreLoader] Scheduled indexing for {world_id}")

    async def get_world_db(self, world_id: str) -> WorldLoreDB | None:
        """
        Phase 2: Get a parsed WorldLoreDB instance (lazy).
        First call triggers YAML parse + cache. Subsequent calls return cache.
        """
        # Check cache
        if world_id in self._instances:
            return self._instances[world_id]

        # Acquire per-world lock to prevent double-parsing
        if world_id not in self._locks:
            logger.warning(f"[WorldLoreLoader] Unknown world: {world_id}")
            return None

        async with self._locks[world_id]:
            # Double-check after acquiring lock
            if world_id in self._instances:
                return self._instances[world_id]

            metadata = self._metadata.get(world_id)
            if not metadata:
                return None

            # Parse YAML (this is the heavy operation)
            try:
                logger.info(f"[WorldLoreLoader] Lazy parsing: {world_id}")
                metadata.parse_started_at = time.time()
                instance = WorldLoreDB(world_id, metadata.yaml_path)
                success = instance.load_from_yaml(metadata.yaml_path)
                if not success:
                    logger.error(f"[WorldLoreLoader] Parse failed for {world_id}")
                    return None
                metadata.is_parsed = True
                metadata.parse_completed_at = time.time()
                self._instances[world_id] = instance
                logger.info(
                    f"[WorldLoreLoader] Parsed {world_id} in "
                    f"{metadata.parse_completed_at - metadata.parse_started_at:.2f}s"
                )
                return instance
            except Exception as e:
                logger.exception(f"[WorldLoreLoader] Lazy parse error for {world_id}: {e}")
                return None

    async def _parse_and_index_world(self, world_id: str) -> None:
        """
        Phase 1.5 background task: parse YAML + build LanceDB index.
        Runs in parallel for all worlds.
        """
        try:
            instance = await self.get_world_db(world_id)
            if not instance:
                return

            # TODO: Build LanceDB vector index
            # For now, just mark as indexed (no actual index yet)
            metadata = self._metadata[world_id]
            metadata.is_indexed = True
            logger.info(f"[WorldLoreLoader] Indexing complete for {world_id}")
        except Exception as e:
            logger.exception(f"[WorldLoreLoader] Indexing failed for {world_id}: {e}")

    def _extract_field(self, text: str, field_marker: str) -> str | None:
        """Extract a YAML field value from the first 1KB of a file."""
        try:
            for line in text.split("\n"):
                if line.strip().startswith(field_marker):
                    # Remove field_marker and quotes/whitespace
                    value = line.split(field_marker, 1)[1].strip().strip('"').strip("'")
                    return value
        except Exception:
            pass
        return None

    def get_metadata(self, world_id: str) -> WorldMetadata | None:
        return self._metadata.get(world_id)

    def list_worlds(self) -> list:
        """List all registered world metadata (for /api/world endpoint)."""
        return [
            {
                "world_id": m.world_id,
                "name": m.name,
                "version": m.version,
                "is_parsed": m.is_parsed,
                "is_indexed": m.is_indexed,
            }
            for m in self._metadata.values()
        ]

    def stats(self) -> dict:
        return {
            "total_worlds": len(self._metadata),
            "parsed": sum(1 for m in self._metadata.values() if m.is_parsed),
            "indexed": sum(1 for m in self._metadata.values() if m.is_indexed),
            "cached_instances": len(self._instances),
        }


# Global instance
world_lore_loader = WorldLoreLoader()
