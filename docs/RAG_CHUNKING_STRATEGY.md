# LanceDB RAG Chunking Strategy

> 將 50 萬 token 世界觀切成可檢索嘅 chunks，注入 Scene Agent prompt。

---

## 🎯 設計目標

| 指標 | 目標 |
|------|------|
| Chunk size | 300-500 tokens |
| Overlap | 50-100 tokens |
| Retrieval | top-5-10 chunks per query |
| Total context per LLM call | 3,000-5,000 tokens |
| Recall@5 | > 80%（5 個 chunk 入面有 4 個相關）|
| Latency | < 100ms (LanceDB 本地) |

---

## 🧩 Chunking 策略

### 1. Entity-Based Chunking（首選）

每個 World Lore 實體切成一個 chunk：

```python
# Pseudo-code
def chunk_world_lore(world: dict) -> List[Chunk]:
    chunks = []

    for npc in world['npcs']:
        chunks.append(Chunk(
            content=format_npc(npc),  # 1500 tokens
            metadata={
                'entity_type': 'npc',
                'entity_id': npc['id'],
                'name': npc['name'],
                'location': npc['location'],
                'tags': npc['narrative_tags'],
            }
        ))

    for location in world['locations']:
        chunks.append(Chunk(
            content=format_location(location),  # 2500 tokens
            metadata={
                'entity_type': 'location',
                'entity_id': location['id'],
                'name': location['name'],
                'atmosphere': location['atmosphere'],
                'tags': location['environment_tags'],
            }
        ))

    for item in world['items']:
        chunks.append(Chunk(
            content=format_item(item),  # 400 tokens
            metadata={
                'entity_type': 'item',
                'entity_id': item['id'],
                'name': item['name'],
                'type': item['type'],
                'rarity': item['rarity'],
            }
        ))

    return chunks
```

**優點：**
- 每個 chunk 係**完整實體**（LLM 易消化）
- Metadata 精準（可以 filter by entity_type, location, tags）
- 易於除錯（可以攞特定 entity 嘅 chunk）

**缺點：**
- 單個 chunk 太大（NPC 1500 tokens > 預期 500）
- 召回時可能浪費 context

### 2. Hybrid Chunking（推薦）

大實體（NPC, Location）內部 sub-chunk：

```python
def chunk_npc(npc: dict) -> List[Chunk]:
    """每個 NPC 切成 2-4 個 sub-chunks。"""
    chunks = []

    # Sub-chunk 1: 基本資料 + 外貌
    chunks.append(Chunk(
        content=format_basic_info(npc),  # 300 tokens
        metadata={
            'entity_type': 'npc',
            'entity_id': npc['id'],
            'chunk_type': 'basic',
        }
    ))

    # Sub-chunk 2: 背景 + 隱藏 lore
    chunks.append(Chunk(
        content=format_background(npc),  # 600 tokens
        metadata={
            'entity_type': 'npc',
            'entity_id': npc['id'],
            'chunk_type': 'background',
        }
    ))

    # Sub-chunk 3: 關係 + 對話
    chunks.append(Chunk(
        content=format_relationships(npc),  # 400 tokens
        metadata={
            'entity_type': 'npc',
            'entity_id': npc['id'],
            'chunk_type': 'social',
        }
    ))

    return chunks
```

**優點：**
- 召回更精準（只攞相關 sub-chunk）
- 節省 context（唔需要 NPC 全文）

**缺點：**
- 複雜啲
- LLM 有時需要跨 sub-chunk 嘅 context

### 3. Section-Based Chunking（備選）

按 YAML 嘅 section 切：

```python
# 每個 top-level YAML key = 1 個 section
sections = [
    'eternal.physical_rules',  # 5 萬 tokens
    'eternal.magic_rules',  # 3 萬 tokens
    'world_parameters',  # 5 萬 tokens
    'npcs',  # 15 萬 tokens（再 sub-chunk）
    'locations',  # 10 萬 tokens
    'items',  # 8 萬 tokens
    'quests',  # 5 萬 tokens
]
```

每個 section 太大，要再切。

---

## 🔍 Retrieval 策略

### Query Construction

Scene Agent 嘅 query 由以下構成：

```python
def build_query(scene_context: dict) -> str:
    parts = []

    # 1. 場景 ID
    parts.append(f"Scene: {scene_context['location_id']}")

    # 2. 場景描述
    parts.append(scene_context['description'])

    # 3. 附近 NPC
    for npc_id in scene_context.get('nearby_npcs', []):
        parts.append(f"NPC: {npc_id}")

    # 4. 玩家動作 / 態度
    if scene_context.get('player_action'):
        parts.append(f"Action: {scene_context['player_action']}")
    if scene_context.get('attitude'):
        parts.append(f"Attitude: {scene_context['attitude']}")

    return " | ".join(parts)
```

### LanceDB Search

```python
# Pseudo-code
def retrieve_relevant_chunks(query: str, top_k: int = 5) -> List[Chunk]:
    # Generate query embedding (Nomic Embed)
    query_embedding = embedding_model.encode(query)

    # Vector search
    results = lance_db.table.search(query_embedding).limit(top_k).to_list()

    # Optional: Filter by metadata
    # e.g., only retrieve NPCs at current location
    filtered = [r for r in results if r['metadata'].get('location') == current_location]

    return results[:top_k]
```

### Top-K Selection

| Query Type | Top-K | Rationale |
|-----------|-------|-----------|
| **Scene generation** | 5-7 | 場景 + 附近 NPC + 物品 + lore |
| **NPC dialogue** | 3-4 | NPC 完整 + 關係 + 對話主題 |
| **Quest trigger** | 4-5 | Quest + 觸發 NPC + 場景 |
| **Combat** | 2-3 | 敵人 + 武器 + 場景危險點 |

---

## 📐 具體實作（待補）

```python
# backend/rag/world_lore_chunker.py
import lancedb
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer

class WorldLoreChunker:
    def __init__(self, world_lore_db: WorldLoreDB):
        self.world = world_lore_db
        self.embedder = SentenceTransformer('nomic-embed-text-v1.5')
        self.db = lancedb.connect('./lancedb_data')
        self.table = None

    def chunk_all(self) -> int:
        """Chunk all world lore entities and create LanceDB table."""
        chunks = []

        # Chunk NPCs (hybrid)
        for npc in self.world.npcs.values():
            chunks.extend(self._chunk_npc(npc))

        # Chunk locations (full)
        for loc in self.world.locations.values():
            chunks.append(self._chunk_location(loc))

        # Chunk items (full)
        for item in self.world.items.values():
            chunks.append(self._chunk_item(item))

        # Generate embeddings
        texts = [c['content'] for c in chunks]
        embeddings = self.embedder.encode(texts, show_progress_bar=True)

        for chunk, emb in zip(chunks, embeddings):
            chunk['vector'] = emb.tolist()

        # Create LanceDB table
        self.table = self.db.create_table('world_lore', chunks, mode='overwrite')
        return len(chunks)

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve top-k most relevant chunks."""
        query_emb = self.embedder.encode([query])[0]
        results = (
            self.table.search(query_emb)
            .limit(top_k)
            .to_list()
        )
        return results
```

---

## 🧠 注入 Scene Agent Prompt 嘅格式

```python
def build_scene_agent_prompt(world_chunks: List[Chunk]) -> str:
    """Build the World Lore section of the Scene Agent system prompt."""

    # Group by entity type
    by_type = {}
    for chunk in world_chunks:
        t = chunk['metadata']['entity_type']
        by_type.setdefault(t, []).append(chunk)

    sections = []

    # 永恆規則（always included, no retrieval）
    sections.append("[Eternal Rules]\n[All physics/magic/social rules]")

    # Retrieved chunks
    if 'location' in by_type:
        sections.append("### Retrieved Locations")
        for chunk in by_type['location']:
            sections.append(f"--- {chunk['metadata']['name']} ---")
            sections.append(chunk['content'])

    if 'npc' in by_type:
        sections.append("### Retrieved NPCs")
        for chunk in by_type['npc']:
            sections.append(f"--- {chunk['metadata']['name']} ---")
            sections.append(chunk['content'])

    if 'item' in by_type:
        sections.append("### Retrieved Items")
        for chunk in by_type['item']:
            sections.append(f"--- {chunk['metadata']['name']} ---")
            sections.append(chunk['content'])

    return "\n\n".join(sections)
```

**Total tokens (example for typical scene):**
- Eternal rules: 500 tokens
- Current location: 1500 tokens
- 2 nearby NPCs: 800 tokens
- 2 items: 400 tokens
- **Total: ~3,200 tokens** (well within 5,000 budget)

---

## 🔄 增量更新策略

Quest trigger 後會生成新 NPC / 場景 / 物品：

```python
def add_new_entity(entity: dict):
    """Add a new entity (created by God Agent) to LanceDB."""
    chunks = chunk_entity(entity)
    embeddings = embedder.encode([c['content'] for c in chunks])
    for c, e in zip(chunks, embeddings):
        c['vector'] = e.tolist()
    table.add(chunks)
```

**Background task**，唔影響主遊戲流程。

---

## 📊 性能指標

| 指標 | 目標 | 實測 |
|------|------|------|
| Chunk size avg | 400 tokens | TBD |
| Retrieval latency | < 100ms | TBD |
| Recall@5 | > 80% | TBD |
| False positive rate | < 20% | TBD |
| Context per LLM call | < 5,000 tokens | TBD |
| Total LanceDB size | < 1 GB | TBD |

---

## 🚀 實作路線

### Phase 1: MVP（1 週）
- [ ] Simple entity-based chunking
- [ ] LanceDB + Nomic Embed 整合
- [ ] Top-5 retrieval
- [ ] Prompt injection template

### Phase 2: Optimisation（1 週）
- [ ] Hybrid chunking (sub-chunks)
- [ ] Metadata filtering (by location/type)
- [ ] Recall metrics
- [ ] A/B test retrieval strategies

### Phase 3: Advanced（2 週）
- [ ] Re-ranking (cross-encoder)
- [ ] Multi-query retrieval
- [ ] Query expansion
- [ ] Caching

---

## 🛠️ 推薦工具

| 工具 | 用途 |
|------|------|
| **LanceDB** | 向量資料庫（已選用）|
| **Nomic Embed Text v1.5** | Embedding 模型（已選用）|
| **sentence-transformers** | Embedding 框架 |
| **PyYAML** | YAML parsing |
| **rank-bm25** | 備用關鍵字搜尋（hybrid retrieval）|

**避免：**
- Pinecone / Weaviate（雲端服務，違反 single-host 部署）
- OpenAI Embeddings API（成本）
- 過於複雜嘅 reranking（無必要）
