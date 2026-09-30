"""Offline checks for the resumable Antigravity catalog translation tool."""

import copy
import json
import re
import unittest

from scripts.translate_catalog import OUTPUT, SOURCE, prose_entries, put_path, validate_translation


class CatalogTranslationTest(unittest.TestCase):
    def test_all_russian_prose_is_enumerated_without_code_examples(self):
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        entries = prose_entries(source)
        paths = [item["path"] for item in entries]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertGreater(len(paths), 1_000)
        self.assertIn("smells/17/detection_metrics/token_similarity", paths)
        self.assertNotIn("smells/0/bad_example/code", paths)

    def test_translated_values_preserve_order_and_numbers(self):
        request = [{"path": "smells/17/detection_metrics/token_similarity",
                    "text": "> 85% совпадения токенов в блоках от 6 строк"}]
        valid = {"translations": [{"path": request[0]["path"],
                                   "text": "> 85% token match in blocks of 6 or more lines"}]}
        self.assertEqual(validate_translation(request, valid)[request[0]["path"]],
                         valid["translations"][0]["text"])
        invalid_number = copy.deepcopy(valid)
        invalid_number["translations"][0]["text"] = "> 80% token match in blocks of 6 lines"
        with self.assertRaisesRegex(ValueError, "numeric values changed"):
            validate_translation(request, invalid_number)
        invalid_language = copy.deepcopy(valid)
        invalid_language["translations"][0]["text"] = request[0]["text"]
        with self.assertRaisesRegex(ValueError, "untranslated"):
            validate_translation(request, invalid_language)
        invalid_path = copy.deepcopy(valid)
        invalid_path["translations"][0]["path"] = "other"
        with self.assertRaisesRegex(ValueError, "missing or reordered"):
            validate_translation(request, invalid_path)

    def test_path_replacement_preserves_other_fields(self):
        data = {"smells": [{"definition": "русский", "code": "print('да')"}]}
        put_path(data, "smells/0/definition", "English")
        self.assertEqual(data["smells"][0]["definition"], "English")
        self.assertEqual(data["smells"][0]["code"], "print('да')")

    def test_english_mirror_preserves_code_identifiers_in_prose(self):
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        english = json.loads(OUTPUT.read_text(encoding="utf-8"))

        def at_path(data, path):
            for component in path.split("/"):
                data = data[int(component)] if isinstance(data, list) else data[component]
            return data

        for entry in prose_entries(source):
            original_tokens = [token for token in re.findall(r"`([^`]+)`", entry["text"])
                               if not re.search(r"[\u0400-\u04ff]", token)]
            translated_text = at_path(english, entry["path"])
            for token in original_tokens:
                self.assertIn(f"`{token}`", translated_text, entry["path"])


if __name__ == "__main__":
    unittest.main()
