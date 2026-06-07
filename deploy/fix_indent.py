"""Remove duplicate orphan code block from game_socket.py (lines 778-804)."""
from pathlib import Path

target = Path(r"C:\Users\kitap\.openclaw\workspace\sandbox-rpg-tmp\backend\ws\game_socket.py")
lines = target.read_text(encoding="utf-8").splitlines()

# Find the orphan block. It starts after the first "raise" at the
# end of the first "except Exception as e" handler (around line 777)
# and runs until the start of the second "except Exception as e"
# that follows (around line 805).
out = []
i = 0
found_first_raise = False
skip_until_next_except = False
while i < len(lines):
    line = lines[i]
    if not skip_until_next_except:
        out.append(line)
        # First raise at column 0 after the FAILED mark block:
        # ``raise`` followed by an indented orphan block is the bug.
        if line.strip() == "raise" and not found_first_raise:
            # Look ahead: if the next non-empty line is indented but
            # NOT a comment, we have an orphan block.
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines):
                next_line = lines[j]
                # Orphan code: indented under a function-level except, but
                # NOT at the same indent as the try: body
                if next_line.startswith("                        ") and not next_line.lstrip().startswith("#"):
                    found_first_raise = True
                    skip_until_next_except = True
        i += 1
    else:
        # Skip lines until we hit the second "except Exception as e:"
        # that is at the same indent as the first one (4 spaces in).
        if line.startswith("            except Exception as e:"):
            skip_until_next_except = False
            out.append(line)
            i += 1
        else:
            i += 1

target.write_text("\n".join(out) + "\n", encoding="utf-8")
print("Cleaned orphan code block.")
print(f"New file: {len(out)} lines (was {len(lines)})")
