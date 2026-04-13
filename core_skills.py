from collections import defaultdict

# 1. Flatten this nested dictionary into {"a.b": 1, "a.c.d": 2}
nested_dict = {"a": {"b": 1, "c": {"d": 2}}}

# 2. Deduplicate this list preserving order → [3, 1, 2, 4]
duplicated_list = [3, 1, 2, 3, 2, 4, 1]

# 3. Group by "dept" → {"eng": ["Alice", "Bob"], "sales": ["Carol"]}
employees = [
    {"dept": "eng", "name": "Alice"},
    {"dept": "eng", "name": "Bob"},
    {"dept": "sales", "name": "Carol"},
]
