#!/usr/bin/env python3
"""Update TestEquipmentConstraints to assert HIDDEN state."""
from pathlib import Path
import re

p = Path(__file__).resolve().parents[1] / "tests" / "test_prompt_builder.py"
text = p.read_text(encoding="utf-8")

# Locate the TestEquipmentConstraints class and rewrite all 3 test bodies
# by replacing assert-X-in-prompt with assert-X-not-in-prompt + updated docstrings.

# 1) fallback
old1 = (
    "    def test_equipment_constraints_fallback(self, no_palace_builder, basic_state, basic_action_context):\n"
    '        """When world_db is None, prompt equipment section should fallback gracefully."""\n'
    "        import asyncio\n"
    "        prompt = asyncio.run(\n"
    "            no_palace_builder.build(\n"
    '                character_id="alice",\n'
    "                current_state=basic_state,\n"
    "                action_context=basic_action_context,\n"
    "                world_db=None\n"
    "            )\n"
    "        )\n"
    '        assert "(\u96b1\u5f0f\u88dd\u5099\u7269\u7406\u7d04\u675f\u8cc7\u8a0a)" in prompt\n'
)
new1 = (
    "    def test_equipment_constraints_fallback(self, no_palace_builder, basic_state, basic_action_context):\n"
    '        """HIDDEN 2026-06-08: items / equipment system is disabled.\n'
    "        The equipment section is no longer injected into the prompt.\n"
    '        This test now asserts the section is empty regardless of world_db."""\n'
    "        import asyncio\n"
    "        prompt = asyncio.run(\n"
    "            no_palace_builder.build(\n"
    '                character_id="alice",\n'
    "                current_state=basic_state,\n"
    "                action_context=basic_action_context,\n"
    "                world_db=None\n"
    "            )\n"
    "        )\n"
    "        # Equipment section header must NOT appear\n"
    '        assert "\u88dd\u5099" not in prompt  # \u88dd\u5099 = equipment (CJK)\n'
    "        # Item-tag translation must NOT appear\n"
    '        assert "\u92ea\u5229" not in prompt  # \u92ea\u5229 = sharp\n'
)
if old1 in text:
    text = text.replace(old1, new1, 1)
    print("replaced test_equipment_constraints_fallback")
else:
    print("NOT FOUND test_equipment_constraints_fallback (checking looser pattern)")
    # Try without the literal CJK chars (file may have different escape)
    m = re.search(r"def test_equipment_constraints_fallback.*?in prompt\n", text, re.DOTALL)
    if m:
        # Use a more surgical approach: just flip the assertion semantics
        block = m.group()
        flipped = re.sub(
            r"assert (.+?) in prompt", r"assert \1 not in prompt  # HIDDEN 2026-06-08", block
        )
        text = text.replace(block, flipped, 1)
        print("  fallback: applied loose-pattern flip")

# 2) no_equipped
old2 = (
    "    def test_equipment_constraints_no_equipped(self, no_palace_builder, basic_state, basic_action_context):\n"
    '        """When world_db is provided but character has no equipped items."""\n'
    "        import asyncio\n"
    "        db = self.MockWorldDB()\n"
    "        # basic_state has no inventory or items.\n"
    "        prompt = asyncio.run(\n"
    "            no_palace_builder.build(\n"
    '                character_id="alice",\n'
    "                current_state=basic_state,\n"
    "                action_context=basic_action_context,\n"
    "                world_db=db\n"
    "            )\n"
    "        )\n"
    '        assert "(\u7121\u7576\u524d\u88dd\u5099)" in prompt\n'
)
new2 = (
    "    def test_equipment_constraints_no_equipped(self, no_palace_builder, basic_state, basic_action_context):\n"
    '        """HIDDEN 2026-06-08: items / equipment system is disabled.\n'
    "        Even when world_db is provided and character has no equipped items,\n"
    '        the equipment section is empty."""\n'
    "        import asyncio\n"
    "        db = self.MockWorldDB()\n"
    "        prompt = asyncio.run(\n"
    "            no_palace_builder.build(\n"
    '                character_id="alice",\n'
    "                current_state=basic_state,\n"
    "                action_context=basic_action_context,\n"
    "                world_db=db\n"
    "            )\n"
    "        )\n"
    "        # Equipment section header must NOT appear\n"
    '        assert "\u88dd\u5099" not in prompt\n'
    '        assert "\u92ea\u5229" not in prompt\n'
)
if old2 in text:
    text = text.replace(old2, new2, 1)
    print("replaced test_equipment_constraints_no_equipped")
else:
    m = re.search(r"def test_equipment_constraints_no_equipped.*?in prompt\n", text, re.DOTALL)
    if m:
        block = m.group()
        flipped = re.sub(
            r"assert (.+?) in prompt", r"assert \1 not in prompt  # HIDDEN 2026-06-08", block
        )
        text = text.replace(block, flipped, 1)
        print("  no_equipped: applied loose-pattern flip")

# 3) injection — flip all `assert X in prompt` to `assert X not in prompt`
m = re.search(
    r"def test_equipment_constraints_injection.*?(?=\n    def |\nclass |\Z)", text, re.DOTALL
)
if m:
    block = m.group()
    flipped = re.sub(
        r"assert (.+?) in prompt", r"assert \1 not in prompt  # HIDDEN 2026-06-08", block
    )
    # Update docstring
    flipped = flipped.replace(
        '"""When character has an equipped item, physical tags and constraints are injected."""',
        '"""HIDDEN 2026-06-08: items / equipment system is disabled.\n        Even with a fully-equipped character, the equipment section is empty."""',
    )
    text = text.replace(block, flipped, 1)
    print("replaced test_equipment_constraints_injection (loose pattern)")

p.write_text(text, encoding="utf-8")
print("done")
