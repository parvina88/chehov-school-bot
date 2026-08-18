"""Self-check: python test_ai_bot.py"""
from ai_bot import split_message

lines = [f"строка {i}" for i in range(1000)]
parts = split_message("\n".join(lines))
assert len(parts) > 1
assert all(len(p) <= 4000 for p in parts)
assert "\n".join(parts).splitlines() == lines

assert split_message("короткий ответ") == ["короткий ответ"]
assert split_message("") == [""]
assert all(len(p) <= 4000 for p in split_message("x" * 9000))  # no line breaks at all
print("ok")
