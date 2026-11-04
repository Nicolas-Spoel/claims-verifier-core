"""M3-A: synthetic fail-closed documentary anchoring regressions (no network)."""
from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from keepmehonest_legal_es import LegalEvidence, Origin, SourceKind
from keepmehonest_legal_es.grounding import anchor_claim, CONTRACT

BOE = 'BOE-A-1978-31229'
TC = 'ECLI:ES:TC:2024:1'
PASSAGE = 'Todas las personas tienen derecho a la tutela judicial efectiva sin indefensión.'
FJ_TEXT = 'El fundamento jurídico sintetico expone las razones procesales de la sentencia.'


def boe(section='a24', text=PASSAGE, version='1978-12-29', origin=Origin.TEST_FIXTURE):
    return LegalEvidence(
        source=SourceKind.BOE, identifier=BOE, section_id=section,
        text=text, official_url='https://www.boe.es/buscar/act.php?id='+BOE,
        title='Prueba sintética (NO ARTÍCULO OFICIAL)', version_date=version, origin=origin,
    )


def tc(section='FJ1', text=FJ_TEXT):
    return LegalEvidence(
        source=SourceKind.TC, identifier=TC, section_id=section,
        text=text, official_url='https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/30062',
        title='Sentencia sintética para pruebas', decision_date='2024-01-15',
        origin=Origin.TEST_FIXTURE,
    )


class DocumentaryGroundingTests(unittest.TestCase):
    def test_valid_exact_quote_is_documentary_only_not_legal_support(self):
        claim=f'El art. 24 de {BOE} exige «{PASSAGE}»; por tanto cualquier causa debe ganarse.'
        result=anchor_claim(claim,[boe()])
        self.assertEqual(result['contract'], CONTRACT)
        self.assertEqual(result['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')
        self.assertEqual(result['cited_section_id'],'a24')
        self.assertEqual(result['evidence_char_span'],[0,len(PASSAGE)])
        self.assertEqual(result['legal_support'],'NOT_ASSESSED')
        self.assertEqual(result['legal_applicability'],'NOT_ASSESSED')
        self.assertTrue(result['requires_human_review'])
        self.assertIn('QUOTE_DOES_NOT_ESTABLISH_LEGAL_ENTAILMENT',result['review_flags'])
        self.assertIn('BOE_TEMPORAL_APPLICABILITY_UNCHECKED',result['review_flags'])

    def test_same_identifier_wrong_article_is_not_anchored(self):
        claim=f'El art. 25 de {BOE} dice «{PASSAGE}».'
        result=anchor_claim(claim,[boe('a24')])
        self.assertEqual(result['anchor_status'],'CITED_SECTION_NOT_SUPPLIED')
        self.assertIsNone(result['evidence_key'])

    def test_same_ecli_wrong_fj_is_not_anchored(self):
        claim=f'El FJ 2 de {TC} dice «{FJ_TEXT}».'
        self.assertEqual(anchor_claim(claim,[tc('FJ1')])['anchor_status'],'CITED_SECTION_NOT_SUPPLIED')

    def test_wrong_quote_is_not_grounded(self):
        claim=f'El artículo 24 de {BOE} dice «La demanda deberá rechazarse automáticamente en cualquier supuesto».'
        result=anchor_claim(claim,[boe()])
        self.assertEqual(result['anchor_status'],'QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION')
        self.assertEqual(result['legal_support'],'NOT_ASSESSED')

    def test_normalize_line_break_but_not_text(self):
        src=boe(text='Primera línea de texto\n  con continuación documental de prueba.')
        claim=f'El art. 24 de {BOE} contiene «Primera línea de texto con continuación documental de prueba.»'
        result=anchor_claim(claim,[src])
        self.assertEqual(result['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')
        self.assertEqual(result['evidence_char_span'],[0,len(src.text)])
        wrong=claim.replace('Primera línea','Segunda línea')
        self.assertEqual(anchor_claim(wrong,[src])['anchor_status'],'QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION')

    def test_no_quote_is_section_only_not_support(self):
        result=anchor_claim(f'Art. 24 de {BOE} permite presentar cualquier demanda.',[boe()])
        self.assertEqual(result['anchor_status'],'SECTION_LOCATED_NO_EXPLICIT_QUOTATION')
        self.assertEqual(result['legal_support'],'NOT_ASSESSED')

    def test_no_section_never_infers_single_supplied_section(self):
        claim=f'La norma {BOE} reconoce un derecho amplio.'
        self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'SECTION_NOT_EXPLICITLY_IDENTIFIED')

    def test_no_explicit_id_must_not_autoresolve_ce(self):
        self.assertEqual(anchor_claim('El art. 24 CE reconoce tutela judicial efectiva.',[boe()])['anchor_status'],'NO_EXPLICIT_IDENTIFIER')

    def test_multiple_citations_require_mapping(self):
        claim=f'El art. 24 de {BOE} se aplica junto al FJ1 de {TC}.'
        self.assertEqual(anchor_claim(claim,[boe(),tc()])['anchor_status'],'MULTIPLE_IDENTIFIERS_REQUIRE_MAPPING')

    def test_multiple_sections_block_mapping(self):
        claim=f'Los artículos 24 y 25 de {BOE} tienen el mismo régimen.'
        result=anchor_claim(claim,[boe()])
        # Conservative parser: article 25 not explicitly prefixed here; the
        # unsupported shorthand is never treated as a positive quotation.
        self.assertNotEqual(result['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')
        direct=f'El art. 24 y el art. 25 de {BOE} contienen «{PASSAGE}».'
        self.assertEqual(anchor_claim(direct,[boe()])['anchor_status'],'MULTIPLE_SECTIONS_AMBIGUOUS')

    def test_subarticle_requires_review(self):
        claim=f'El art. 24.1 de {BOE} contiene «{PASSAGE}».'
        self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'SUBARTICLE_SCOPE_UNSUPPORTED')

    def test_duplicate_versions_same_section_are_ambiguous(self):
        claim=f'El art. 24 de {BOE} contiene «{PASSAGE}».'
        a=boe(); b=boe(text=PASSAGE+' Contexto adicional.', version='2024-01-01')
        self.assertEqual(anchor_claim(claim,[a,b])['anchor_status'],'MULTIPLE_EVIDENCE_VERSIONS_AMBIGUOUS')

    def test_truncated_quotation_rejected(self):
        claim=f'El art. 24 de {BOE} dice «Todas las personas ... sin indefensión».'
        self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'SECTION_LOCATED_QUOTATION_HAS_OMISSIONS')

    def test_short_quote_rejected(self):
        claim=f'El art. 24 de {BOE} dice «derecho».'
        self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'SECTION_LOCATED_QUOTATION_TOO_SHORT')

    def test_multiple_quotes_rejected(self):
        claim=f'El art. 24 de {BOE} dice «{PASSAGE}» y «otra interpretación normativa relevante».'
        self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'SECTION_LOCATED_MULTIPLE_QUOTATIONS_AMBIGUOUS')

    def test_wrong_quotes_cannot_be_upgraded_from_lexical_overlap(self):
        claim=f'El art. 24 de {BOE} niega «Todas las personas tienen derecho a la indefensión sin tutela».'
        self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION')

    def test_tc_fj_alias_and_exact_quote(self):
        claim=f'En el fundamento jurídico 1 de {TC} se afirma «{FJ_TEXT}».'
        result=anchor_claim(claim,[tc()])
        self.assertEqual(result['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')
        self.assertEqual(result['cited_section_id'],'FJ1')
        self.assertIn('TC_RATIO_AND_PROCEDURAL_CONTEXT_UNCHECKED',result['review_flags'])

    def test_tc_fallo_never_infers_fj(self):
        claim=f'El fallo de {TC} contiene «{FJ_TEXT}».'
        self.assertEqual(anchor_claim(claim,[tc('FJ1')])['anchor_status'],'CITED_SECTION_NOT_SUPPLIED')
        self.assertEqual(anchor_claim(claim,[tc('FALLO')])['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')

    def test_unmatched_quote_not_implicitly_matched(self):
        claim=f'Art. 24 de {BOE}: «{PASSAGE}'
        self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'SECTION_LOCATED_NO_EXPLICIT_QUOTATION')

    def test_test_fixture_never_promoted_to_official(self):
        claim=f'El art. 24 de {BOE} señala «{PASSAGE}».'
        result=anchor_claim(claim,[boe()])
        self.assertEqual(result['source_origin'],Origin.TEST_FIXTURE.value)
        self.assertIn('SOURCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED',result['review_flags'])

    def test_no_network_when_grounding(self):
        claim=f'El art. 24 de {BOE} señala «{PASSAGE}».'
        with patch('keepmehonest_legal_es.sources.transport.SecureHTTP.get',side_effect=AssertionError('network')):
            self.assertEqual(anchor_claim(claim,[boe()])['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')

    def test_claim_hash_changes_if_proposition_changes(self):
        a=anchor_claim(f'Art. 24 {BOE} permite recurso.',[boe()])
        b=anchor_claim(f'Art. 24 {BOE} prohíbe recurso.',[boe()])
        self.assertNotEqual(a['claim_sha256'],b['claim_sha256'])


    def test_abbreviation_mask_restores_exact_original_spelling(self):
        from keepmehonest_legal_es.independent import _protect_legal_abbreviations, _restore_legal_abbreviations
        text='El art. 24 y el FJ. 1 de la resolución. El art. no identificado.'
        protected=_protect_legal_abbreviations(text)
        self.assertEqual(len(protected),len(text))
        self.assertNotIn('art. 24',protected)
        self.assertIn('art. no',protected)
        self.assertEqual(_restore_legal_abbreviations(protected),text)

    def test_boe_evidence_section_alias(self):
        claim=f'El artículo 24 de {BOE} contiene «{PASSAGE}».'
        self.assertEqual(anchor_claim(claim,[boe('art24')])['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')

    def test_unavailable_source_not_false_claim(self):
        result=anchor_claim(f'El art. 24 de {BOE} establece un derecho.',[])
        self.assertEqual(result['anchor_status'],'CITED_SECTION_NOT_SUPPLIED')
        self.assertEqual(result['legal_support'],'NOT_ASSESSED')


HAS_CORE=importlib.util.find_spec('claims_verifier') is not None


@unittest.skipUnless(HAS_CORE, 'requires full Core 0.1.1 checkout')
class EndToEndM3Tests(unittest.TestCase):
    def test_m3_in_report_without_mutating_core(self):
        from keepmehonest_legal_es.independent import verify_argument
        text=f'El art. 24 de {BOE} dice «{PASSAGE}».'
        result=verify_argument(text,[boe()])
        self.assertEqual(result['schema_version'],'keepmehonest-legal-es/0.3.1')
        self.assertEqual(result['claims'][0]['documentary_grounding']['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')
        self.assertEqual(result['claims'][0]['legal_support'],'NOT_ASSESSED')
        self.assertEqual(result['coverage']['documentary_grounding']['claims_with_exact_documentary_quote'],1)
    def test_no_quote_and_unrelated_section_no_support(self):
        from keepmehonest_legal_es.independent import verify_argument
        result=verify_argument(f'El art. 24 de {BOE} ordena expulsar a todos.',[boe('a25')])
        self.assertEqual(result['claims'][0]['documentary_grounding']['anchor_status'],'CITED_SECTION_NOT_SUPPLIED')
        self.assertEqual(result['claims'][0]['legal_support'],'NOT_ASSESSED')

    def test_legal_abbreviation_does_not_split_claim_before_number(self):
        from keepmehonest_legal_es.independent import verify_argument
        claim=f'El art. 24 de {BOE} dice «{PASSAGE}».'
        result=verify_argument(claim,[boe()])
        self.assertEqual(len(result['claims']),1)
        self.assertEqual(result['claims'][0]['documentary_grounding']['anchor_status'],'DOCUMENTARY_QUOTE_MATCH')

    def test_source_attempts_and_unchanged_status(self):
        from keepmehonest_legal_es.independent import verify_argument
        attempts=[{'source':'BOE','identifier':BOE,'status':'UNAVAILABLE','reason':'source offline'}]
        result=verify_argument(f'El art. 24 de {BOE} exige tutela judicial.',[],attempted_sources=attempts)
        self.assertEqual(result['status'],'SOURCES_REQUIRED')
        self.assertEqual(result['coverage']['source_attempts'],attempts)
        self.assertEqual(result['coverage']['documentary_grounding']['claims_with_exact_documentary_quote'],0)


if __name__ == '__main__':
    unittest.main()
