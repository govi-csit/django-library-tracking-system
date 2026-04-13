def deduplicate_list_preserving_order(original_list):
    deduplicated_list = []
    for item in original_list:
        if item not in deduplicated_list:
            deduplicated_list.append(item)

    return deduplicated_list


def group_by_dept_employees(items):
    result = {}
    for item in items:
        if item['dept'] in result:
            result[item['dept']].append(item['name'])
        else:
            result[item['dept']] = [item['name']]

    return result


if __name__ == "__main__":
    # # 1. Flatten this nested dictionary into {"a.b": 1, "a.c.d": 2}
    # nested_dict = {"a": {"b": 1, "c": {"d": 2}}}

    # 2. Deduplicate this list preserving order → [3, 1, 2, 4]
    duplicated_list = [3, 1, 2, 3, 2, 4, 1]
    duplicated_result_list = deduplicate_list_preserving_order(duplicated_list)
    print(f"Deduplicated list: {duplicated_result_list}")

    # 3. Group by "dept" → {"eng": ["Alice", "Bob"], "sales": ["Carol"]}
    employees = [
        {"dept": "eng", "name": "Alice"},
        {"dept": "eng", "name": "Bob"},
        {"dept": "sales", "name": "Carol"},
    ]

    group_by_dept_result = group_by_dept_employees(employees)
    print(f"Group by dept employees: {group_by_dept_result}")
