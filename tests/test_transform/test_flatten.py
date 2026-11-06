from piimask.transform.flatten import field_path, split_document


def test_nested_dict_becomes_dotted_columns():
    (row,) = split_document({"a": 1, "b": {"c": {"d": 2}}}, "k")
    assert row.table == "" and row.parent_key is None
    assert row.fields == {"a": 1, "b.c.d": 2}


def test_array_of_objects_becomes_child_rows():
    root, first, second = split_document({"Batteries": [{"Serial": "x"}, {"Serial": "y"}]}, "k")
    assert root.fields == {}
    assert (first.table, first.parent_key, first.index, first.fields) == ("Batteries", "k", 0, {"Serial": "x"})
    assert second.index == 1 and second.key != first.key


def test_array_of_scalars_uses_value_column():
    _, row = split_document({"tags": ["a"]}, "k")
    assert row.table == "tags" and row.fields == {"value": "a"}


def test_array_inside_nested_object_keeps_full_path():
    _, row = split_document({"a": {"b": [{"c": 1}]}}, "k")
    assert field_path(row.table, "c") == "a.b[].c"


def test_array_inside_array_links_to_its_own_parent_row():
    rows = list(split_document({"a": [{"b": [{"c": 1}]}]}, "k"))
    assert [row.table for row in rows] == ["", "a", "a[].b"]
    assert rows[2].parent_key == rows[1].key
    assert field_path(rows[2].table, "c") == "a[].b[].c"


def test_array_inside_array_without_object():
    rows = list(split_document({"a": [[1, 2]]}, "k"))
    assert [row.fields for row in rows[2:]] == [{"value": 1}, {"value": 2}]


def test_empty_and_null_values():
    (row,) = split_document({"a": None, "b": "", "c": {}, "d": []}, "k")
    assert row.fields == {"a": None, "b": "", "c": {}}
