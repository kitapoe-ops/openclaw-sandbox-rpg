"""Find the dangling 'except Exception as e:' that's not inside any
'try:' block (the orphan from my prior fix) and remove it.
"""
from pathlib import Path

target = Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\backend\ws\game_socket.py")
lines = target.read_text(encoding="utf-8").splitlines()

# Find the orphan except block — it's the one whose body is the
# STEP 3 FAILED mark, but it sits at indent level 12 (inside the
# STEP 2 async with) instead of 8 (its parent try).
# Pattern: 12 spaces + "except Exception as e:" and the following
# block is the FAILED-mark code we want to preserve but move to
# the right place.
out = []
i = 0
skip_to_next = None
while i < len(lines):
    line = lines[i]
    if skip_to_next is not None:
        if i < skip_to_next:
            i += 1
            continue
        else:
            skip_to_next = None
    out.append(line)
    # Detect orphan: 12-space indent except Exception as e:
    if line.startswith("            except Exception as e:"):
        # Check if previous non-blank line is a try: at the SAME indent.
        # If not, this except is dangling.
        j = len(out) - 2
        while j >= 0 and out[j].strip() == "":
            j -= 1
        prev = out[j] if j >= 0 else ""
        if not prev.strip().startswith("try:"):
            # Orphan — drop the whole block (up to and including the
            # next "raise" at the same indent).
            i += 1
            while i < len(lines):
                inner = lines[i]
                # Stop when we hit a line at LESS indentation OR another
                # except at the same indent (next handler)
                if (
                    inner.strip() == ""
                    or inner.startswith("                    ")  # 20 spaces — inside
                    or inner.startswith("                ")  # 16 spaces — sibling
                    or inner.startswith("            except")  # next handler
                    or inner.startswith("        except")  # outer except
                ):
                    if inner.strip().startswith("except") and not inner.startswith("                    "):
                        break
                    i += 1
                    continue
                break
            # Skip the orphan body — already added the except line, undo
            out.pop()
            continue
    i += 1

target.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"Done. {len(out)} lines (was {len(lines)})")
