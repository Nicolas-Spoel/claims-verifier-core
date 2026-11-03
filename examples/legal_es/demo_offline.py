"""Fully synthetic, offline example — does not fetch or authenticate a judgment."""
from keepmehonest_legal_es import LegalEvidence, Origin, SourceKind, review_claim

source = LegalEvidence(
    source=SourceKind.TC,
    identifier="ECLI:ES:TC:2024:1",  # identifier-shaped synthetic demonstration
    section_id="FJ3",
    text="EJEMPLO SINTÉTICO: El tribunal de prueba recibió la petición ficticia.",
    title="Ejemplo inventado; NO es el texto de una resolución real",
    official_url="https://hj.tribunalconstitucional.es/HJ/es/Busqueda/Index",
    decision_date="2024-01-01",
    origin=Origin.TEST_FIXTURE,
)
review = review_claim(
    "ECLI:ES:TC:2024:1 contiene una referencia a la petición ficticia.",
    source,
    quote="El tribunal de prueba recibió la petición ficticia.",
)
print(review)
