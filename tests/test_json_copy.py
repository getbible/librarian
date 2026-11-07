"""Response copies detach validated JSON without Python recursion."""

import unittest
from copy import deepcopy

from getbible._json_copy import copy_json


class TestJsonCopy(unittest.TestCase):
    def test_matches_deepcopy_for_json_values_and_preserves_order(self) -> None:
        value = {
            "text": "Scripture — العربية",
            "scalars": [None, True, False, 42, -9, 0.125],
            "nested": {"empty_list": [], "empty_object": {}, "verse": {"text": "Faith"}},
        }
        copied = copy_json(value)
        self.assertEqual(copied, deepcopy(value))
        self.assertEqual(list(copied), list(value))
        copied["scalars"].append("changed")
        copied["nested"]["verse"]["text"] = "changed"
        self.assertEqual(value["scalars"], [None, True, False, 42, -9, 0.125])
        self.assertEqual(value["nested"]["verse"]["text"], "Faith")

    def test_deep_containers_are_copied_without_recursion(self) -> None:
        value = {"note": "Published annotation"}
        for level in range(1500):
            value = {"children": value} if level % 2 else [value]
        copied = copy_json(value)
        original_node, copied_node = value, copied
        for _ in range(1500):
            self.assertIsNot(original_node, copied_node)
            if isinstance(original_node, dict):
                original_node, copied_node = original_node["children"], copied_node["children"]
            else:
                original_node, copied_node = original_node[0], copied_node[0]
        self.assertIsNot(original_node, copied_node)
        self.assertEqual(copied_node, {"note": "Published annotation"})
        copied_node["note"] = "Caller mutation"
        self.assertEqual(original_node, {"note": "Published annotation"})

    def test_shared_branches_preserve_aliases_without_sharing_source_objects(self) -> None:
        shared = {"text": ["Faith"]}
        copied = copy_json([shared, shared])
        self.assertIs(copied[0], copied[1])
        self.assertIsNot(copied[0], shared)
        self.assertIsNot(copied[0]["text"], shared["text"])

    def test_cycles_and_non_json_mutable_values_are_rejected(self) -> None:
        cyclic_list: list = []
        cyclic_list.append(cyclic_list)
        cyclic_dict: dict = {}
        cyclic_dict["child"] = [cyclic_dict]
        for value in (cyclic_list, cyclic_dict):
            with (
                self.subTest(kind=type(value).__name__),
                self.assertRaisesRegex(ValueError, "Circular reference"),
            ):
                copy_json(value)
        for value in ({"not JSON"}, {"nested": {"not JSON"}}):
            with self.assertRaisesRegex(TypeError, "Only JSON values"):
                copy_json(value)


if __name__ == "__main__":
    unittest.main()
