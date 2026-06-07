"""Fix the jsonb_set SQL — ARRAY[$1, $2] is not valid in asyncpg.
Build the ARRAY[...] literal from the constants directly via
string concatenation (the keys are not user-controlled)."""
from pathlib import Path

target = Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\backend\ws\game_socket.py")
src = target.read_text(encoding="utf-8")

# Replace the broken jsonb_set block with one that builds the path
# literal via string concat (the values are constants).
old = """            if scene_output.get("state_changes"):
                        cs = scene_output["state_changes"]
                        for k, db_key, profile_section in (
                            ("stamina_level", "stamina_level", "physical"),
                            ("health_status", "health_status", "physical"),
                            ("morale_level", "morale_level", "mental"),
                        ):
                            if k in cs and cs[k]:
                                await conn.execute(
                                    _sql_text(
                                        "UPDATE character_states "
                                        "SET semantic_profile = jsonb_set("
                                        "    COALESCE(semantic_profile, '{}'::jsonb), "
                                        "    ARRAY[:section, :key]::text[], "
                                        "    to_jsonb(:val::text) "
                                        "), updated_at = now() "
                                        "WHERE character_id = :cid"
                                    ),
                                    {
                                        "section": profile_section,
                                        "key": db_key,
                                        "val": str(cs[k]),
                                        "cid": character_id,
                                    },
                                )"""

new = """            if scene_output.get("state_changes"):
                        cs = scene_output["state_changes"]
                        for k, db_key, profile_section in (
                            ("stamina_level", "stamina_level", "physical"),
                            ("health_status", "health_status", "physical"),
                            ("morale_level", "morale_level", "mental"),
                        ):
                            if k in cs and cs[k]:
                                # Build the path as a SQL ARRAY literal
                                # (jsonb_set needs a real ARRAY, not bound
                                # positional params which asyncpg does not
                                # support). The values are constants, not
                                # user-controlled.
                                path_array = (
                                    "ARRAY['" + profile_section
                                    + "','" + db_key + "']::text[]"
                                )
                                await conn.execute(
                                    _sql_text(
                                        "UPDATE character_states "
                                        "SET semantic_profile = jsonb_set("
                                        "    COALESCE(semantic_profile, '{}'::jsonb), "
                                        "    " + path_array + ", "
                                        "    to_jsonb(:val::text) "
                                        "), updated_at = now() "
                                        "WHERE character_id = :cid"
                                    ),
                                    {
                                        "val": str(cs[k]),
                                        "cid": character_id,
                                    },
                                )"""

if old in src:
    src = src.replace(old, new)
    target.write_text(src, encoding="utf-8")
    print("Patched.")
else:
    print("Pattern not found — file content may have changed.")
    # Try a fuzzy match
    import re
    m = re.search(r"if scene_output\.get\(\"state_changes\"\):.*?character_id,[\s\n]+[\s\n]+                              \),", src, re.DOTALL)
    if m:
        print("Fuzzy match found at:", m.start())
        # Look for the line
        line = src.split("\n")
        for i, l in enumerate(line):
            if "jsonb_set" in l and "ARRAY[:section" in l:
                print(f"  Line {i+1}: {l}")
