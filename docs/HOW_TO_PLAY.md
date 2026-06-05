# 🎮 How to Play — OpenClaw Sandbox RPG

> **Audience:** Anyone who successfully ran the 5-command deploy from `QUICKSTART_LOCAL_DEPLOY.md` and now wants to start a game session.
> **Scope:** 1-4 players + up to 100 NPCs per scene.

---

## 🕹️ 3 Steps to In-Game

### Step 1 — Pick your character (single-player quick start)

In your browser at `http://localhost:5173/demo.html`:

- The page loads a character list on the left
- Click on a character name (e.g. "Test Hero") to select
- If no characters exist, click "Create New Character" and pick:
  - **Name:** anything (e.g. "Adventurer")
  - **Class:** warrior / mage / rogue (visual only for now)
  - **Starting state:** you'll start as "非常健康" (very healthy)

### Step 2 — Enter a scene

- Click "Start Adventure" or "Enter Scene"
- You'll spawn into a default scene (currently: `phandalin_town`, a D&D 5e starter town)
- The right panel shows:
  - **Scene description** (narrative)
  - **NPC list** (up to 100, click to interact)
  - **Action input** (text box + submit)

### Step 3 — Take your first action

Type something in the action input, for example:

```
我向 blacksmith 查詢鐵劍價錢
```

Then press Enter. The framework will:

1. Validate your action (`is_action_allowed` — physics lock check)
2. Generate narrative via the LLM (default: MockLLMClient, returns canned response)
3. Update your semantic state if needed (e.g. "tired" → "exhausted")
4. Save to Memory Palace (so next time you ask, the blacksmith remembers)
5. Broadcast to other connected players (if any)

**Your action result will appear in the right panel within 1-3 seconds.**

---

## 👥 1-4 Player Multiplayer

### Add more players

Each player opens `http://localhost:5173/demo.html` in a **separate browser tab** (or different browser/device).

- Player 1 clicks "Join as Player 1"
- Player 2 clicks "Join as Player 2" (in a new tab)
- ... up to 4 players
- A WebSocket connects each player to the scene
- Actions are broadcast to all 4 players in real time

### Hard cap: 4 players

The 5th join attempt returns a 409 "scene_full" error. The framework is locked to 1-4 player scope.

---

## 🤖 NPC Interaction (up to 100 per scene)

- Each NPC has its own character state and Memory Palace
- Click on an NPC name to view their profile
- Use action verb + NPC name: `向 [NPC name] [action]`
- Example: `向 blacksmith 講: 你有什麼武器?`
- The NPC "remembers" past interactions (via Memory Palace recall)

### NPC dialogue arbitration

If 2 players ask the same NPC at the same time, the system uses **first-come-first-served** ordering via the async turn queue. The 2nd player sees a "NPC is currently busy" notice.

---

## 🧠 What Makes This Different from a Chatbot

| Feature | What it does |
|---------|--------------|
| **Persistent state** | Close the browser, come back tomorrow — your state survives |
| **Memory Palace** | Every NPC remembers past conversations (semantic recall) |
| **Soul transfer** | If your character dies, your soul can move to another vessel |
| **Pure-text semantic state** | No hidden HP/mana — state is "right hand fractured" or "very healthy", human-readable |
| **Real LLM** | Set `LLM_PROVIDER=minimax` env var for real MiniMax-M3 instead of mock |
| **R1 audit** | LM Studio on :1234 = real DeepSeek-R1-14B verifies actions before commit |

---

## 🎯 Quick Action Examples

```
# Movement
move north
go to the tavern

# Combat
attack the goblin
defend with shield

# Dialogue
talk to the innkeeper
ask the blacksmith about iron swords

# Item use
drink healing potion
equip leather armor

# State interaction
check my injuries
rest for the night
```

---

## 🛠️ Troubleshooting

| Symptom | Fix |
|---------|-----|
| Page shows "WebSocket offline" | Check backend is running on :8000 (`curl /health`) |
| NPC responses are canned (mock) | Set `LLM_PROVIDER=minimax` env var + `MINIMAX_API_KEY=...` then restart backend |
| Action rejected ("not allowed") | Physics lock check failed — try a different verb |
| Memory recall returns nothing | Your embedding was too different from when the memory was stored |
| Multiplayer says "scene full" | Only 4 players allowed; the 5th is hard-rejected |
| Browser shows CORS error | Don't open demo.html via `file://` — use `http://localhost:5173` (serve_demo.py) |

---

## 🔌 Under the Hood (for the curious)

When you click "Submit Action":

```
Browser  →  POST /api/action/process  →  ActionProcessor.process()
   │                                              │
   │                                              ├─→ validate (whitelist + state machine)
   │                                              ├─→ physics lock (per-character)
   │                                              ├─→ prompt_builder.build() (state always on top)
   │                                              ├─→ llm_client.generate_with_state_contract() (with retry)
   │                                              ├─→ state_machine.apply_mutations() (strict Pydantic)
   │                                              └─→ memory_palace.remember() (state anchor)
   │
   ←  {"status":"processed","narrative":"...","mutation":{...},"action_id":"..."}
```

---

## 🎯 Recommended First Session (5 minutes)

1. **Open** `http://localhost:5173/demo.html`
2. **Create** character "Adventurer"
3. **Enter** scene "phandalin_town"
4. **Type:** `look around`
5. **See** the scene description populate the right panel
6. **Click** on "Blacksmith" NPC
7. **Type:** `向 blacksmith 講: 你好`
8. **See** the blacksmith "respond" (with mock LLM: canned text; with real LLM: generated)
9. **Close** the tab
10. **Reopen** it 5 minutes later
11. **Click** on "Blacksmith" again
12. **Notice:** the blacksmith still remembers you (Memory Palace persistence)

That last step is the magic. Most RPGs forget everything on browser close. This one doesn't.

---

_This file was added 2026-06-05 after deployment verification confirmed the framework is locally runnable. See `QUICKSTART_LOCAL_DEPLOY.md` for the 5-command deploy._
