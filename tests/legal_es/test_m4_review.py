"""Human labeling gates refuse to mistake pending or fake labels for legal gold."""
from __future__ import annotations
import copy
import unittest
from keepmehonest_legal_es.m4_review import (
    CONTRACT, AnnotationError, summarize_review_queue, validate_annotation,
)


def pending():
    return dict(contract=CONTRACT,case_id="PUB-TEST-001",source_kind="BOE",
                evidence_sha256="a"*64,argument_sha256="b"*64,
                contains_confidential_data=False,reuse_reviewed=True,status="PENDING_EXPERT",
                reviewer_a=None,reviewer_b=None,adjudication=None)


def assessor(name):
    return dict(reviewer_id=name, reviewed_on="2026-11-03",documentary_label="EXACT_QUOTE",
                legal_support_label="INSUFFICIENT_EVIDENCE",facts_available=False,
                temporal_applicability_reviewed=False,
                reason="Cita documental comprobada, hechos jurídicos del caso ausentes.",
                evidence_locator="art. 24, texto de ejemplo")


def adjudicated():
    p=pending();p['status']='ADJUDICATED'
    p['reviewer_a']=assessor('reviewer-001');p['reviewer_b']=assessor('reviewer-002')
    p['adjudication']=dict(adjudicator_id='reviewer-003',adjudicated_on='2026-11-04',
                           documentary_label='EXACT_QUOTE',legal_support_label='INSUFFICIENT_EVIDENCE',
                           conflicts_resolved=True,
                           reason='Sin expediente de hechos no se emite un juicio sobre aplicación.',
                           evidence_locator='art. 24, revisión por humanos')
    return p


class ReviewGateTests(unittest.TestCase):
    def test_pending_not_gold(self):
        self.assertEqual(validate_annotation(pending())['status'],'PENDING_EXPERT')
        self.assertEqual(summarize_review_queue([pending()])['adjudicated'],0)

    def test_pending_cannot_contain_labels(self):
        r=pending();r['reviewer_a']=assessor('a')
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_valid_adjudication_requires_three_distinct_people(self):
        self.assertEqual(validate_annotation(adjudicated())['status'],'ADJUDICATED')

    def test_same_reviewer_denied(self):
        r=adjudicated();r['reviewer_b']['reviewer_id']='reviewer-001'
        with self.assertRaisesRegex(AnnotationError,'independent'):validate_annotation(r)

    def test_adjudicator_cannot_be_reviewer(self):
        r=adjudicated();r['adjudication']['adjudicator_id']='reviewer-001'
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_confidential_data_denied(self):
        r=pending();r['contains_confidential_data']=True
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_reuse_not_cleared_denied(self):
        r=pending();r['reuse_reviewed']=False
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_missing_hash_denied(self):
        r=pending();r['evidence_sha256']=None
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_no_facts_no_direct_support(self):
        r=adjudicated();r['adjudication']['legal_support_label']='DIRECT_SUPPORT'
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_expert_cannot_assert_direct_support_without_facts(self):
        r=adjudicated();r['reviewer_a']['legal_support_label']='DIRECT_SUPPORT'
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_insufficient_reason_rejected(self):
        r=adjudicated();r['reviewer_a']['reason']='ok'
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_duplicate_case_rejected(self):
        r=pending()
        with self.assertRaisesRegex(AnnotationError,'duplicate'):summarize_review_queue([r,copy.deepcopy(r)])

    def test_future_date_rejected(self):
        r=adjudicated();r['reviewer_a']['reviewed_on']='2099-01-01'
        with self.assertRaises(AnnotationError):validate_annotation(r)

    def test_experts_cannot_label_cendoj(self):
        r=pending();r['source_kind']='ORDINARY_COURTS'
        with self.assertRaises(AnnotationError):validate_annotation(r)


if __name__=='__main__':unittest.main()
