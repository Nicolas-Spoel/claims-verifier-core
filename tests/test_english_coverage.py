"""English lexical coverage: intended behaviour for each English construction, with counterexamples.

Every correction is paired with counterexamples that must not become a false SUPPORTED or CONTRADICTED, and
constructions the engine deliberately does not decide (bounds, comparatives, causes) are checked for the same
safety property. Spanish-language inputs here are deliberate (Spanish-language support test data): they check
that Spanish behaviour is preserved, except for two defects corrected in both languages: the stem collisions
and a stated proportion contradicted by the same proportion in another year.
"""

import unittest

from claims_verifier import ClaimsVerifier, Verdict, VerifierConfig, make_document
from claims_verifier.numbers import NumberKind, Qualifier, extract_numbers
from claims_verifier.safety import GuardCode, run_guards
from claims_verifier.signals import analyze
from claims_verifier.text import content_stems, synonym_map

COOPERATIVE = (
    "In 2024 the cooperative collected 4,850 tonnes of parchment coffee, 6% less than in 2023 as a result of the rains."
)
MEMBERS = "The cooperative brings together 2,300 producer members, 41% of whom are women."
DECISIVE = {Verdict.SUPPORTED, Verdict.CONTRADICTED}


def verdict(evidence, claim, config=VerifierConfig()):
    texts = [evidence] if isinstance(evidence, str) else evidence
    docs = [make_document(f"d{i}", text) for i, text in enumerate(texts)]
    return ClaimsVerifier.from_documents(docs, config).verify_claims([claim]).results[0].verdict


def guard_codes(claim, passage, numbers=False):
    return [g.signal.code for g in run_guards(claim, passage, frozenset(), frozenset(), numbers)]


class ApproximationTest(unittest.TestCase):
    def test_close_to_is_an_approximation_and_part_of_the_figure(self):
        self.assertIs(extract_numbers("close to 5,000 tonnes")[0].qualifier, Qualifier.APPROX)
        self.assertIs(verdict(COOPERATIVE, "Close to 5,000 tonnes of coffee were collected in 2024."), Verdict.SUPPORTED)

    def test_far_figure_is_not_supported_by_an_approximation(self):
        self.assertIsNot(verdict(COOPERATIVE, "Close to 9,000 tonnes of coffee were collected in 2024."), Verdict.SUPPORTED)

    def test_close_as_a_verb_is_still_a_content_term(self):
        self.assertIn(content_stems("close")[0], content_stems("The plant will close in 2025."))
        self.assertIsNot(verdict("The plant will open in 2025.", "The plant will close in 2025."), Verdict.SUPPORTED)

    def test_approximation_against_a_bound_decides_nothing(self):
        cases = (("The plant employs fewer than 590 workers.", "The plant employs about 600 workers."),
                 ("The firm has more than 4,900 employees.", "The firm has close to 5,000 employees."))
        for evidence, claim in cases:
            with self.subTest(claim=claim):
                self.assertNotIn(verdict(evidence, claim), DECISIVE)

    def test_qualified_evidence_cannot_confirm_an_exact_figure(self):
        for evidence in ("The company has fewer than 600 employees.", "The company has close to 600 employees."):
            with self.subTest(evidence=evidence):
                self.assertIsNot(verdict(evidence, "The company has 600 employees."), Verdict.SUPPORTED)


class BoundsComparativesAndCausesTest(unittest.TestCase):
    """Bound markers, comparatives and causes stay terms the evidence must contain: never assumed."""

    def test_bounded_claims_are_not_falsely_decided(self):
        evidence = "The company has 640 workers."
        self.assertIsNot(verdict(evidence, "The company has more than 600 workers."), Verdict.CONTRADICTED)
        self.assertIsNot(verdict(evidence, "The company has fewer than 600 workers."), Verdict.SUPPORTED)
        self.assertIsNot(verdict(evidence, "The company has no more than 600 workers."), Verdict.SUPPORTED)

    def test_comparatives_causes_and_baselines_must_appear_in_the_evidence(self):
        cases = (("The company hired 40 women in 2024 and 55 women in 2023.",
                  "The company hired more women in 2024 than in 2023."),
                 ("The plant closed and the drought continued.", "The plant closed because of the drought."),
                 ("Revenue grew 15% in 2022.", "Revenue grew 15% compared with 2022."))
        for evidence, claim in cases:
            with self.subTest(claim=claim):
                self.assertIsNot(verdict(evidence, claim), Verdict.SUPPORTED)


class AttributiveYearTest(unittest.TestCase):
    def test_year_after_a_determiner_before_a_period_noun(self):
        self.assertIs(extract_numbers("The 2024 collection fell by 6%")[0].kind, NumberKind.YEAR)
        self.assertIs(extract_numbers("its 2023 report")[0].kind, NumberKind.YEAR)
        self.assertIs(verdict(COOPERATIVE, "The 2024 collection fell by 6%."), Verdict.SUPPORTED)

    def test_counts_stay_quantities(self):
        for text in ("the 2000 workers", "employs 2000 workers", "the 2000 people", "the 1950 staff",
                     "its 2000 km network", "the 2000-seat stadium", "its 2000 accounts", "the 1950 statements"):
            with self.subTest(text=text):
                self.assertIs(extract_numbers(text)[0].kind, NumberKind.QUANTITY)

    def test_wrong_attributive_year_is_not_supported(self):
        self.assertIsNot(verdict(COOPERATIVE, "The 2022 collection fell by 6%."), Verdict.SUPPORTED)


class PartitiveScopeTest(unittest.TestCase):
    def test_fraction_in_a_relative_clause_still_restricts_the_claim(self):
        # The exemption for relative partitives let coordinated populations through ("coffee and cocoa sales …,
        # 70% of which came from cocoa"): withdrawn (EN-1A), so the conservative reading applies.
        self.assertIsNot(verdict(MEMBERS, "The cooperative has 2,300 members."), Verdict.SUPPORTED)
        self.assertIsNot(verdict("The cooperative's coffee and cocoa sales totalled $12 million, 70% of which came from cocoa.",
                                 "The cooperative's coffee sales totalled $12 million."), Verdict.SUPPORTED)

    def test_claim_about_the_subgroup_predicate_is_still_restricted(self):
        self.assertIsNot(verdict(MEMBERS, "The members are women."), Verdict.SUPPORTED)

    def test_proportion_against_a_relative_clause_decides_nothing(self):
        self.assertNotIn(verdict(MEMBERS, "The majority of the members are women."), DECISIVE)

    def test_partitive_subject_still_restricts_a_generic_claim(self):
        evidence = "30% of the stores adopted the new billing system."
        self.assertIsNot(verdict(evidence, "The stores adopted the new billing system."), Verdict.SUPPORTED)
        self.assertIn(GuardCode.SCOPE_OPERATOR, guard_codes("The stores adopted the new billing system.", evidence))

    def test_relative_clause_after_a_parenthetical_still_restricts(self):
        evidence = "The firm sold 500 trucks in 2024, 20% of which, in December, went to Chile."
        self.assertIsNot(verdict(evidence, "The firm sold 500 trucks to Chile in 2024."), Verdict.SUPPORTED)

    def test_first_half_is_a_period_not_a_proportion(self):
        self.assertIsNone(analyze("Exports grew in the first half of 2024.").proportion)
        self.assertIsNone(analyze("Las ventas crecieron en la primera mitad de 2024.").proportion)
        self.assertEqual(analyze("Half of the members are women.").proportion[0], "half")

    def test_a_proportion_in_another_year_is_another_period(self):
        # Corrects a defect present in both languages: the other year used to contradict the claim.
        self.assertIs(verdict("In 2022 the majority of customers paid online.",
                              "In 2023 the majority of customers paid online."), Verdict.NOT_ENOUGH_EVIDENCE)
        self.assertIs(verdict("En 2022 la mayoría de los clientes pagó en línea.",
                              "En 2023 la mayoría de los clientes pagó en línea."), Verdict.NOT_ENOUGH_EVIDENCE)

    def test_proportions_are_not_decided_from_ties_subgroups_or_other_periods(self):
        cases = (("Men make up 62% of the employees, and women 38%.", "The majority of the employees are women."),
                 ("62% of the women farmers own their land.", "The majority of the farmers are women."),
                 ("In 2022, 70% of customers paid online.", "In 2023 the majority of customers paid online."),
                 ("The plant operated normally in the first half of 2024, when exports reached 90% of plant output.",
                  "The plant operated normally in the first half of 2024."))
        for evidence, claim in cases:
            with self.subTest(claim=claim):
                self.assertNotIn(verdict(evidence, claim), DECISIVE)


class IrregularFormsAndAdverbsTest(unittest.TestCase):
    def test_irregular_past_forms_are_not_mapped_to_their_base(self):
        # Mapping "sold" to "sell" also matched nouns such as "sell-off" and "teachers": withdrawn (EN-1A).
        for form, base in (("sold", "sell"), ("taught", "teach"), ("wrote", "write"), ("knew", "know")):
            with self.subTest(form=form):
                self.assertNotEqual(content_stems(form), content_stems(base))
        evidence = "The cooperative did not sell coffee to the United States in 2024."
        self.assertIsNot(verdict(evidence, "The cooperative sold coffee to the United States in 2024."), Verdict.SUPPORTED)

    def test_forms_whose_base_is_a_noun_and_homographs_are_not_mapped(self):
        for form, base in (("paid", "pay"), ("dealt", "deal"), ("ran", "run"), ("made", "make"), ("led", "lead")):
            with self.subTest(form=form):
                self.assertNotEqual(content_stems(form), content_stems(base))

    def test_other_actions_attempts_or_plans_do_not_support_a_completed_sale(self):
        claim = "The cooperative sold coffee to the United States in 2024."
        for evidence in ("The cooperative bought coffee from the United States in 2024.",
                         "The cooperative plans to sell coffee to the United States in 2024.",
                         "In 2024 the cooperative refused to sell coffee to the United States.",
                         "The cooperative can sell coffee to the United States in 2024."):
            with self.subTest(evidence=evidence):
                self.assertIsNot(verdict(evidence, claim), Verdict.SUPPORTED)

    def test_only_listed_ly_adverbs_share_the_stem_of_their_base(self):
        self.assertEqual(content_stems("mainly"), content_stems("main"))
        for word, other in (("highly", "high"), ("firmly", "firm"), ("costly", "cost"), ("hardly", "hard")):
            with self.subTest(word=word):
                self.assertNotEqual(content_stems(word), content_stems(other))
        self.assertEqual(content_stems("supply"), content_stems("suppliers"))


class IdiomAndCollisionTest(unittest.TestCase):
    def test_taking_office_is_not_a_unit_of_the_organization(self):
        evidence = "The general manager of Nimbus Logística is Lucía Ramos, who took office in January 2021."
        self.assertIs(verdict(evidence, "The general manager is Lucía Ramos."), Verdict.SUPPORTED)

    def test_a_named_office_is_still_a_subset(self):
        evidence = "Employees at the regional office received a productivity bonus."
        self.assertIs(verdict(evidence, "Employees received a productivity bonus."), Verdict.PARTIALLY_SUPPORTED)
        self.assertIsNot(verdict("Complaints at the regional office fell 20% after the new mayor took office.",
                                 "Complaints fell 20% after the new mayor took office."), Verdict.SUPPORTED)

    def test_plant_is_not_a_synonym_of_employees(self):
        self.assertNotEqual(content_stems("plant"), content_stems("employees"))
        self.assertNotEqual(content_stems("planta"), content_stems("plantilla"))
        self.assertEqual(content_stems("plantilla"), content_stems("employees"))  # Spanish "workforce" keeps its synonym

    def test_plant_claim_is_not_supported_by_workforce_evidence(self):
        self.assertIsNot(verdict("The workforce was expanded in 2024.", "The plant was expanded in 2024."), Verdict.SUPPORTED)
        self.assertIsNot(verdict("La plantilla fue ampliada en 2024.", "La planta fue ampliada en 2024."), Verdict.SUPPORTED)

    def test_other_stem_collisions_are_not_synonyms(self):
        pairs = (("direction", "manager"), ("directly", "manager"), ("utility", "profit"), ("profile", "profit"),
                 ("decree", "decrease"), ("dismissed", "decrease"), ("custody", "customers"), ("incredibly", "growth"),
                 ("customs", "customers"), ("benefits", "profit"), ("decreto", "disminucion"),
                 ("utilizacion", "utilidad"), ("planteo", "plantilla"))
        for word, other in pairs:
            with self.subTest(word=word):
                self.assertNotEqual(content_stems(word), content_stems(other))

    def test_caller_synonyms_can_still_group_a_listed_word(self):
        synonyms = synonym_map((("factory", "plant"),))
        self.assertEqual(content_stems("plant", synonyms), content_stems("factory", synonyms))


class SignalCoverageTest(unittest.TestCase):
    def test_declared_and_pointed_out_are_reported_speech(self):
        self.assertIn(GuardCode.REPORTED_SPEECH,
                      guard_codes("Employees are satisfied.", "78% of employees declared themselves satisfied."))
        self.assertIn(GuardCode.REPORTED_SPEECH,
                      guard_codes("Employees need more training.", "Some employees pointed out the need for more training."))

    def test_infinitive_after_a_modal_is_non_finite(self):
        self.assertIn(GuardCode.NONFINITE_PREDICATE,
                      guard_codes("The company expanded its fleet.", "The company could expand its fleet."))

    def test_first_half_is_part_of_the_period(self):
        self.assertIn(GuardCode.PERIOD_SUBSET,
                      guard_codes("The accident rate decreased in 2024.",
                                  "In the first half of 2024, the accident rate decreased by 18%."))

    def test_half_as_a_fraction_is_not_a_period(self):
        self.assertNotIn(GuardCode.PERIOD_SUBSET,
                         guard_codes("Employees received a bonus.", "Half of the employees received a bonus."))


class SpanishPreservationTest(unittest.TestCase):
    """The same constructions in Spanish keep their previous verdicts."""

    COOPERATIVA = "En 2024 la cooperativa acopió 4.850 toneladas de café, un 6% menos que en 2023 por las lluvias."

    def test_spanish_bounds_and_approximations(self):
        self.assertIs(verdict("La empresa cuenta con 640 trabajadores.", "La empresa tiene más de 600 trabajadores."),
                      Verdict.SUPPORTED)
        self.assertIs(verdict(self.COOPERATIVA, "Cerca de 5.000 toneladas de café fueron acopiadas en 2024."),
                      Verdict.SUPPORTED)

    def test_spanish_direction_proportion_and_people(self):
        self.assertIs(verdict(self.COOPERATIVA, "El acopio de café aumentó en 2024 respecto a 2023."), Verdict.CONTRADICTED)
        socios = "La cooperativa agrupa a 2.300 socios, de los cuales el 41% son mujeres."
        self.assertIs(verdict(socios, "La mayoría de los socios son mujeres."), Verdict.CONTRADICTED)
        self.assertIs(verdict(socios, "La cooperativa tiene 2.300 socios."), Verdict.SUPPORTED)
        self.assertIs(verdict("La empresa emplea a 500 empleados.", "La empresa emplea a 500 personas."), Verdict.SUPPORTED)


# Counterexamples written independently of the corrections, by two separate reviews: each pair produced a false
# SUPPORTED or CONTRADICTED with an earlier version of these corrections and must never do so again. Spanish
# pairs are deliberate (Spanish-language support test data).
COUNTEREXAMPLE_PAIRS = (
    ('The plant closed because of the drought.',
     'The plant closed and the drought continued.', ('SUPPORTED', 'CONTRADICTED')),
    ('The company hired more women in 2024 than in 2023.',
     'The company hired 40 women in 2024 and 55 women in 2023.', ('SUPPORTED',)),
    ('The firm has close to 5,000 employees.',
     'The firm has more than 4,900 employees.', ('SUPPORTED', 'CONTRADICTED')),
    ('The firm has fewer than 600 employees.',
     'The firm has more than 500 employees.', ('SUPPORTED', 'CONTRADICTED')),
    ('Fewer than 600 households received water.',
     'In total, 600 households received water.', ('SUPPORTED',)),
    ('The default rate was more than 5%.',
     'The default rate was 4.6%.', ('SUPPORTED',)),
    ('Unemployment was less than 10% in 2024.',
     'Unemployment was 10.4% in 2024.', ('SUPPORTED',)),
    ('The fund has more than 500 investors.',
     'The fund has less than 900 investors.', ('SUPPORTED', 'CONTRADICTED')),
    ('The default rate was above 5%.',
     'The default rate was 5%.', ('SUPPORTED',)),
    ('The company sold the plant in 2024.',
     'In 2024 the company refused to sell the plant.', ('SUPPORTED',)),
    ('The company made a profit in 2024.',
     'In 2024 the company failed to make a profit.', ('SUPPORTED',)),
    ('The company paid the fine.',
     'The company refused to pay the fine.', ('SUPPORTED',)),
    ('The minister met the protesters.',
     'The minister declined to meet the protesters.', ('SUPPORTED',)),
    ('The firm won the tender.',
     'The firm hoped to win the tender.', ('SUPPORTED',)),
    ('The government kept the subsidy.',
     'The government wanted to keep the subsidy.', ('SUPPORTED',)),
    ('The union led the strike.',
     'The union threatened to lead the strike.', ('SUPPORTED',)),
    ('The company took control of the port.',
     'The company attempted to take control of the port.', ('SUPPORTED',)),
    ('Perez led the investigation.',
     'The investigation by Perez found lead in the water.', ('SUPPORTED',)),
    ('The firm makes 500 cars a year.',
     'The firm imports 500 cars a year made in Japan.', ('SUPPORTED',)),
    ('The company builds 200 homes a year.',
     'The company buys 200 homes a year built by others.', ('SUPPORTED',)),
    ('The firm rejected the offer.',
     'The union firmly rejected the offer.', ('SUPPORTED',)),
    ('The project cost 5 million dollars.',
     'The costly project received 5 million dollars.', ('SUPPORTED',)),
    ('The plant was inspected for a year.',
     'The plant was inspected yearly.', ('SUPPORTED',)),
    ("The company's customers grew 10% in 2024.",
     "The company's customs payments grew 10% in 2024.", ('SUPPORTED',)),
    ("The company's profit rose 8% in 2024.",
     "The company's employee benefits rose 8% in 2024.", ('SUPPORTED',)),
    ('In 2021 the project relocated the 2000 people living in the valley.',
     'In 2021 the project relocated 2000 people living in the valley.', ('CONTRADICTED',)),
    ('Its 2000 km network carried 5 million passengers in 2023.',
     'Its 1200 km network carried 5 million passengers in 2023.', ('SUPPORTED',)),
    ('The 2000-seat stadium cost 50 million dollars.',
     'The 1500-seat stadium cost 50 million dollars.', ('SUPPORTED',)),
    ('In 2022 the firm retrained the 1950 staff of the plant.',
     'In 2022 the firm retrained 1950 staff of the plant.', ('CONTRADICTED',)),
    ('The majority of members voted for the merger.',
     'Three of the members voted for the merger.', ('SUPPORTED',)),
    ('The majority of farmers adopted drip irrigation.',
     '62% of the women farmers adopted drip irrigation.', ('SUPPORTED',)),
    ('Sales rose 12% in the first half of 2024.',
     'Sales at 30% of the stores rose 12% in the first half of 2024.', ('SUPPORTED',)),
    ('The plant operated normally in the first half of 2024.',
     'The plant operated normally in the first half of 2024, when exports reached 90% of plant output.', ('CONTRADICTED',)),
    ("The majority of the cooperative's members are women.",
     "The cooperative's board has 12 members, 60% of whom are women.", ('SUPPORTED',)),
    ('The firm sold 500 trucks to Chile in 2024.',
     'The firm sold 500 trucks in 2024, 20% of which, in December, went to Chile.', ('SUPPORTED',)),
    ('A minority of the employees received bonuses.',
     'Two of the employees received bonuses.', ('SUPPORTED',)),
    ('Complaints fell 20% after the new mayor took office.',
     'Complaints at the regional office fell 20% after the new mayor took office.', ('SUPPORTED',)),
    ('In 2023 the majority of customers paid online.',
     'In 2022, 70% of customers paid online.', ('SUPPORTED', 'CONTRADICTED')),
    ('The majority of residents support the dam.',
     'Among the 200 residents surveyed in the valley, 60% of the young support the dam.', ('SUPPORTED',)),
    ('Revenue rose in the first half of 2024.',
     'Revenue rose 40% of the time in the first half of 2024.', ('CONTRADICTED',)),
    ('La empresa tiene menos de 600 empleados.',
     'La empresa tiene más de 500 empleados.', ('SUPPORTED', 'CONTRADICTED')),
    ('La planta operó con normalidad en la primera mitad de 2024.',
     'La planta operó con normalidad en la primera mitad de 2024, cuando las exportaciones alcanzaron el 90% de la producción de la planta.', ('CONTRADICTED',)),
    ('La mayoría de los agricultores adoptó riego por goteo.',
     'El 62% de las mujeres agricultoras adoptó riego por goteo.', ('SUPPORTED',)),
    ('La mayoría de los socios votó a favor.',
     'Un tercio de los socios votó a favor.', ('SUPPORTED',)),
    ('La empresa tiene cerca de 5.000 empleados.',
     'La empresa tiene más de 4.900 empleados.', ('SUPPORTED', 'CONTRADICTED')),
    ('Las ventas crecieron 12% en la primera mitad de 2024.',
     'Las ventas del 30% de las tiendas crecieron 12% en la primera mitad de 2024.', ('SUPPORTED',)),
    ('The company sold the plant in 2024.',
     'In 2024 the company agreed to sell the plant.', ('SUPPORTED',)),
    ('The fund has more than 500 investors.',
     'The fund has about 480 investors.', ('SUPPORTED',)),
    ('The fund has fewer than 500 investors.',
     'The fund has close to 510 investors.', ('SUPPORTED',)),
    ('The majority of the 5 directors resigned.',
     '2 of the 5 directors resigned.', ('SUPPORTED',)),
    ('The plant produced more copper in 2024.',
     'The plant produced copper in 2024.', ('SUPPORTED',)),
    ('El desempleo fue menos del 10% en 2024.',
     'El desempleo fue 10,4% en 2024.', ('SUPPORTED',)),
    ('Al menos 600 trabajadores se unieron a la huelga.',
     'Alrededor de 590 trabajadores se unieron a la huelga.', ('SUPPORTED',)),
    ('The company paid the fine.',
     'The company must pay the fine.', ('SUPPORTED',)),
    ('The company sold the plant.',
     'The company can sell the plant.', ('SUPPORTED',)),
    ('The regulator met the operators.',
     'The regulator should meet the operators.', ('SUPPORTED',)),
    ('The court ordered the firm to pay; the firm paid the fine.',
     'The court ordered the firm to pay the fine.', ('SUPPORTED',)),
    ('The bank kept its rating in 2024.',
     'In 2024 the bank failed to keep its rating.', ('SUPPORTED',)),
    ('The firm had more than 1.22 million customers in 2023.',
     'The firm had 1.2 million customers in 2023.', ('SUPPORTED', 'CONTRADICTED')),
    ('The project cost about $5 million.',
     'The project cost more than $5.1 million.', ('SUPPORTED', 'CONTRADICTED')),
    ('The plant employs about 600 workers.',
     'The plant employs fewer than 590 workers.', ('SUPPORTED', 'CONTRADICTED')),
    ('The plant employs close to 600 workers.',
     'The plant employs more than 610 workers.', ('SUPPORTED', 'CONTRADICTED')),
    ('The company has 1.2 million customers.',
     'The company has more than 1.22 million customers.', ('SUPPORTED', 'CONTRADICTED')),
    ('The program reached 5,000 children under 12.',
     'The program reached 5,000 children under 12.', ('CONTRADICTED',)),
    ('The company has no more than 600 employees.',
     'The company has 550 employees.', ('CONTRADICTED',)),
    ('The company has no fewer than 600 employees.',
     'The company has 650 employees.', ('CONTRADICTED',)),
    ('The company has no less than 600 employees.',
     'The company has 650 employees.', ('CONTRADICTED',)),
    ('The company employs more than 550 people.',
     'The company employs between 500 and 600 people.', ('SUPPORTED', 'CONTRADICTED')),
    ('The company employs fewer than 600 people.',
     'The company employs 500 to 700 people.', ('SUPPORTED', 'CONTRADICTED')),
    ('La empresa facturó cerca de 5 millones de soles en 2023.',
     'La empresa facturó más de 5,1 millones de soles en 2023.', ('SUPPORTED', 'CONTRADICTED')),
    ('The agency processed roughly 10,000 requests in 2024.',
     'The agency processed fewer than 9,800 requests in 2024.', ('SUPPORTED', 'CONTRADICTED')),
    ('The majority of the employees are women.',
     'Men make up 62% of the employees, and women 38%.', ('SUPPORTED',)),
    ('The majority of the members approved the merger.',
     '62% of the members who voted approved the merger.', ('SUPPORTED', 'CONTRADICTED')),
    ('The majority of the employees are women.',
     'In the 2024 promotion round, 41% of the employees promoted were women.', ('SUPPORTED', 'CONTRADICTED')),
    ('The majority of the board members are women.',
     'The cooperative has 2,300 members; 41% of the members are women, and the board has 12 members.', ('SUPPORTED', 'CONTRADICTED')),
    ('The majority of the farmers are women.',
     '62% of the women farmers own their land.', ('SUPPORTED', 'CONTRADICTED')),
    ('In 2024 the bank migrated its 2000 accounts to the new platform.',
     'In 2024 the bank migrated 2000 accounts to the new platform.', ('CONTRADICTED',)),
    ('The bank closed the 2000 accounts flagged by the auditors in 2024.',
     'In 2024 the bank closed 2000 accounts flagged by the auditors.', ('CONTRADICTED',)),
    ('In 2024 the archive digitized the 1950 statements.',
     'In 2024 the archive digitized 1950 statements.', ('CONTRADICTED',)),
    ('The firm dealt with the regulator.',
     'The firm made a deal with the regulator.', ('SUPPORTED', 'CONTRADICTED')),
    ('The company paid its 300 workers in March.',
     'In March the company froze the pay of its 300 workers.', ('SUPPORTED', 'CONTRADICTED')),
    ('Acme bought back shares worth $5 million.',
     'Acme approved a buy-back of shares worth $5 million.', ('SUPPORTED', 'CONTRADICTED')),
    ('The bonds are highly rated.',
     'The bonds carry high risk and are rated junk.', ('SUPPORTED', 'CONTRADICTED')),
    ('Revenue grew 15% compared with 2022.',
     'Revenue grew 15% in 2022.', ('SUPPORTED', 'CONTRADICTED')),
    ('The fund has not more than 40 investors.',
     'The fund has 35 investors.', ('CONTRADICTED',)),
    ('The program trained no fewer than 600 teachers in 2024.',
     'The program trained 640 teachers in 2024.', ('CONTRADICTED',)),
    ('La empresa tiene no menos de 600 empleados.',
     'La empresa tiene 650 empleados.', ('CONTRADICTED',)),
    ('La empresa tiene unos 600 empleados.',
     'La empresa tiene menos de 590 empleados.', ('SUPPORTED', 'CONTRADICTED')),
    ('The cooperative exported around 2,000 tonnes in 2023.',
     'The cooperative exported over 2,050 tonnes in 2023.', ('SUPPORTED', 'CONTRADICTED')),
    ('The plan will cost more than $3 million.',
     'The plan will cost from $2 million to $4 million.', ('SUPPORTED', 'CONTRADICTED')),
    ('La mayoría de los socios son mujeres.',
     'Los hombres son el 62% de los socios y las mujeres el 38%.', ('SUPPORTED',)),
    ('The majority of the shareholders are pension funds.',
     "Banks hold 55% of the shareholders' votes, and pension funds 30%.", ('SUPPORTED', 'CONTRADICTED')),
    ('Exports rose 8% compared to 2023.',
     'Exports rose 8% in 2023.', ('SUPPORTED', 'CONTRADICTED')),
    ('In 2024 the lab published its 2000 results.',
     'In 2024 the lab published 2000 results.', ('CONTRADICTED',)),
    ('The firm dealt with 300 suppliers in 2023.',
     'The firm signed a deal with 300 suppliers in 2023.', ('SUPPORTED', 'CONTRADICTED')),
    ('Depositors ran the bank in 2023.',
     'Depositors started a run on the bank in 2023.', ('SUPPORTED', 'CONTRADICTED')),
)


# The twelve false SUPPORTED verdicts found by the final acceptance review of the EN-1 corrections, caused by the
# irregular-verb mapping and the relative-partitive exemption, both withdrawn. None may be supported again.
ACCEPTANCE_REGRESSION_PAIRS = (
    ('The government sold its 30% stake in the utility in 2024.',
     'In 2024 the government postponed the sell-off of its 30% stake in the utility.'),
    ('The city sold its water utility in 2023.',
     'In 2023 the city council rejected the sell-off of its water utility.'),
    ('The bank wrote off $2 million in farm loans in 2024.',
     "In 2024 regulators blocked the bank's write-off of $2 million in farm loans."),
    ('The fund wrote down its stake in the mine by 40% in 2024.',
     "In 2024 auditors questioned the fund's write-down of its stake in the mine by 40%."),
    ('The cooperative taught accounting to 200 members in 2024.',
     'In 2024 the cooperative hired accounting teachers for 200 members.'),
    ('The foundation taught financial literacy to 500 women in 2024.',
     'In 2024 the foundation trained 20 financial literacy teachers for 500 women.'),
    ('The agency wrote 40 reports on rural roads in 2024.',
     'In 2024 the agency hired 40 writers for reports on rural roads.'),
    ('The minister spoke at the cooperative assembly in March.',
     'The minister was on the list of speakers at the cooperative assembly in March.'),
    ('The staff knew the new procurement rules.',
     'The staff lacked know-how on the new procurement rules.'),
    ("The cooperative's coffee sales totalled $12 million.",
     "The cooperative's coffee and cocoa sales totalled $12 million, 70% of which came from cocoa."),
    ("The fund's loans to farmers totalled $5 million in 2024.",
     "The fund's loans to farmers and traders totalled $5 million in 2024, 80% of which went to traders."),
    ('Revenue from coffee reached $12 million in 2024.',
     'Revenue from coffee and cocoa reached $12 million in 2024, 70% of which came from cocoa.'),
)


class AcceptanceRegressionsTest(unittest.TestCase):
    def test_withdrawn_mechanisms_no_longer_produce_false_support(self):
        for claim, evidence in ACCEPTANCE_REGRESSION_PAIRS:
            with self.subTest(claim=claim):
                self.assertIsNot(verdict(evidence, claim), Verdict.SUPPORTED)


class CounterexamplePairsTest(unittest.TestCase):
    def test_no_forbidden_decisive_verdict(self):
        for claim, evidence, forbidden in COUNTEREXAMPLE_PAIRS:
            with self.subTest(claim=claim, evidence=evidence):
                self.assertNotIn(verdict(evidence, claim).value, forbidden)


if __name__ == "__main__":
    unittest.main()
