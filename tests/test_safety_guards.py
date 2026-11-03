"""Safety guards: entities, absence of evidence, process stage, population, reported speech and roles.

Spanish-language inputs in this module are deliberate: they exercise the Spanish lexicon, which the
engine keeps as language-support data alongside English.
"""

import unittest

from claims_verifier.safety import Effect, GuardCode, claim_entities, role_inversion, run_guards
from claims_verifier.text import content_stems


def guards(claim, passage, context="", entities=frozenset(), numbers=False):
    return run_guards(claim, passage, frozenset(content_stems(context)), entities, numbers)


def codes(result):
    return [g.signal.code for g in result]


class RoleInversionTest(unittest.TestCase):
    def test_swapped_actors_are_detected(self):
        self.assertIsNotNone(role_inversion("Andina compró Vértice.", "Vértice compró Andina."))
        self.assertIsNotNone(role_inversion("El proveedor pagó al cliente.", "El cliente pagó al proveedor."))

    def test_moved_adverbials_and_same_order_are_not_inversions(self):
        self.assertIsNone(role_inversion("Andina compró Vértice en marzo.", "En marzo Andina compró Vértice."))
        self.assertIsNone(
            role_inversion(
                "La empresa abrió un centro de distribución en Arequipa en marzo de 2023.",
                "En marzo de 2023 la empresa abrió un centro de distribución en Arequipa.",
            )
        )

    def test_passive_voice_is_not_judged(self):
        self.assertIsNone(role_inversion("Andina compró Vértice.", "Vértice fue comprada por Andina."))


class EntityGuardTest(unittest.TestCase):
    def test_claim_entities(self):
        corpus_entities = frozenset(content_stems("Vértice"))
        self.assertEqual(claim_entities("Vértice compró la planta de Ica.", corpus_entities),
                         frozenset(content_stems("Vértice Ica")))
        self.assertEqual(claim_entities("Los ingresos crecieron en Marzo.", frozenset()), frozenset())

    def test_missing_entity_makes_the_passage_irrelevant(self):
        result = guards("La sucursal Sur vendió 400 equipos.", "La sucursal Norte vendió 300 equipos.")
        self.assertEqual(result[0].effect, Effect.IGNORE)
        self.assertEqual(result[0].signal.code, GuardCode.ENTITY_NOT_IN_EVIDENCE)

    def test_entity_in_document_context_is_enough(self):
        result = guards("Vértice vendió 300 equipos.", "La empresa vendió 300 equipos.", context="Memoria de Vértice")
        self.assertNotIn(GuardCode.ENTITY_NOT_IN_EVIDENCE, codes(result))


class AbsenceGuardTest(unittest.TestCase):
    def test_absence_statement_does_not_decide_existence(self):
        result = guards("Hubo irregularidades en el manejo de caja.", "No se identificaron irregularidades en caja.")
        self.assertIn(GuardCode.ABSENCE_OF_EVIDENCE, codes(result))
        result = guards("La empresa no tiene certificación ISO.", "No se encontró registro de certificación ISO.")
        self.assertIn(GuardCode.ABSENCE_OF_EVIDENCE, codes(result))

    def test_same_epistemic_act_is_decidable(self):
        result = guards("Los auditores identificaron observaciones.", "No se identificaron observaciones.")
        self.assertNotIn(GuardCode.ABSENCE_OF_EVIDENCE, codes(result))


class StageGuardTest(unittest.TestCase):
    def test_request_is_not_grant(self):
        result = guards("La empresa obtuvo la licencia ambiental.", "La empresa solicitó la licencia ambiental.")
        self.assertEqual(result[0].signal.code, GuardCode.STAGE_NOT_REACHED)
        self.assertEqual(result[0].effect, Effect.ABSTAIN)
        result = guards("La planta fue ampliada.", "La ampliación de la planta está en evaluación.")
        self.assertIn(GuardCode.STAGE_NOT_REACHED, codes(result))

    def test_request_claim_matches_request_evidence(self):
        self.assertEqual(guards("La empresa solicitó la licencia.", "La empresa solicitó la licencia."), ())

    def test_granted_request_is_an_outcome(self):
        result = guards("El regulador aprobó la licencia.", "El regulador aprobó la solicitud de licencia.")
        self.assertNotIn(GuardCode.STAGE_NOT_REACHED, codes(result))

    def test_rejection_contradicts_grant(self):
        result = guards("La licencia fue otorgada.", "La solicitud de licencia fue rechazada.")
        self.assertEqual(result[0].effect, Effect.CONTRADICT)


class PopulationAndReportedTest(unittest.TestCase):
    def test_subset_evidence_weakens_generic_claim(self):
        result = guards("Los empleados recibieron un bono.", "Los empleados de la planta de Ica recibieron un bono.")
        self.assertEqual(result[0].signal.code, GuardCode.POPULATION_SUBSET)
        self.assertEqual(result[0].effect, Effect.WEAKEN)

    def test_matching_scope_or_figures_are_not_flagged(self):
        self.assertEqual(guards("Los empleados de Ica recibieron un bono.", "Los empleados de Ica recibieron un bono."), ())
        result = guards("La empresa tiene 300 empleados.", "La planta de Ica tiene 300 empleados.", numbers=True)
        self.assertIn(GuardCode.POPULATION_SUBSET, codes(result))

    def test_pilot_is_not_rollout(self):
        result = guards("La empresa implementó la receta electrónica.", "La empresa inició un piloto de receta electrónica.")
        self.assertEqual(result[0].signal.code, GuardCode.POPULATION_SUBSET)

    def test_reported_speech(self):
        result = guards("La empresa duplicó sus ventas.", "El gerente afirmó que la empresa duplicó sus ventas.")
        self.assertEqual(result[0].signal.code, GuardCode.REPORTED_SPEECH)


class RoleMarkerTest(unittest.TestCase):
    def test_swapped_prepositional_roles(self):
        result = guards(
            "La CNCV autorizó la adquisición de Fenwar por parte de Ostrilla.",
            "La CNCV autorizó la adquisición de Ostrilla por Fenwar.",
        )
        self.assertIn(GuardCode.ROLE_INVERSION, codes(result))

    def test_same_roles_are_not_flagged(self):
        result = guards(
            "La CNCV autorizó la adquisición de Ostrilla por parte de Fenwar.",
            "La CNCV autorizó la adquisición de Ostrilla por Fenwar.",
        )
        self.assertNotIn(GuardCode.ROLE_INVERSION, codes(result))

    def test_specialized_entity_is_a_subset(self):
        result = guards("La morosidad de Pucarumi fue de 4,2%.", "La morosidad de Pucarumi Norte fue de 4,2%.", numbers=True)
        self.assertIn(GuardCode.POPULATION_SUBSET, codes(result))

    def test_unverified_self_declaration_is_attributed(self):
        result = guards("San Bruno tiene 230 trabajadores.",
                        "San Bruno declaró tener 230 trabajadores, pero la cifra no pudo ser contrastada.", numbers=True)
        self.assertIn(GuardCode.REPORTED_SPEECH, codes(result))


if __name__ == "__main__":
    unittest.main()
