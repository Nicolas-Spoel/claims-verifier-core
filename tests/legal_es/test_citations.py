import unittest

from keepmehonest_legal_es import ReferenceKind, find_references, parse_identifier


class CitationsTests(unittest.TestCase):
    def test_identifiers_and_offsets(self):
        text = "Conforme a BOE-A-1978-31229 y ECLI:ES:TC:2024:1 (Roj: STS 123/2024)."
        refs = find_references(text)
        self.assertEqual([r.kind for r in refs], [ReferenceKind.BOE, ReferenceKind.ECLI, ReferenceKind.ROJ])
        self.assertEqual(refs[2].value, "ROJ: STS 123/2024")
        self.assertTrue(all(text[r.start:r.end].strip() for r in refs))

    def test_ecli_terminal_punctuation_not_part_of_identifier(self):
        refs = find_references("ECLI:ES:TC:2024:1.")
        self.assertEqual(refs[0].value, "ECLI:ES:TC:2024:1")
        self.assertEqual(parse_identifier("ECLI:ES:TC:2024:1"), (ReferenceKind.ECLI, "ECLI:ES:TC:2024:1"))

    def test_case_insensitive_normalization(self):
        self.assertEqual(parse_identifier("boe-a-1978-31229"), (ReferenceKind.BOE, "BOE-A-1978-31229"))
        self.assertEqual(parse_identifier("Roj: sts 123/2024"), (ReferenceKind.ROJ, "ROJ: STS 123/2024"))

    def test_reject_partial_or_ambiguous_identifier(self):
        for identifier in ["", "BOE-A-1978-31229 plus something", "ECLI:ES:TC:2024:1:EXTRA", "ECLI:ES:TC:2024:1.", "art. 24 CE", "BOE-A-1978-31229 BOE-A-2020-1"]:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                parse_identifier(identifier)

    def test_does_not_resolve_unimplemented_natural_citations(self):
        self.assertEqual(find_references("art. 24 CE; STC 1/2024"), ())
