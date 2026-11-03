"""Static bilingual (Spanish / English) word lists used by the lexical judge.

All entries are accent-folded and lowercase, matching ``text.fold`` output.
Prefix lists are matched with ``str.startswith`` against folded tokens.
"""

from __future__ import annotations

STOPWORDS: frozenset[str] = frozenset(
    """
    a al ante bajo con contra de del desde durante en entre hacia hasta mediante para por segun sin
    sobre tras el la los las lo un una unos unas este esta estos estas ese esa esos esas aquel aquella
    y e o u ni que como cuando donde cual cuales quien quienes cuyo su sus mi mis tu tus nuestro nuestra
    se le les me te nos os ya muy mas tambien solo asi aun es son fue fueron ser sido siendo era eran sea sean seas
    esta estan estaba estaban estuvo ha han habia hay haber tiene tienen tenia tuvo hace hizo cada otro
    otra otros otras mismo misma porque pues si lo esto eso ello ademas respecto dicho dicha
    the a an of to in on at by for with from into over under about as and or but if then than that this
    these those it its is are was were be been being has have had do does did will would shall should
    can there their they them he she his her we our you your i me my which who whom whose what where
    when while also only just so such both each other same into onto per via
    """.split()
)

# Low-information words that carry no checkable content of their own: reporting/copular
# verbs, generic references to "the company" and temporal deixis ("actual", "now").
LOW_INFORMATION_WORDS: frozenset[str] = frozenset(
    """
    registro registra registraron registrado registrada alcanzo alcanza alcanzaron alcanzado reporto reporta
    reportaron reportado tiene tienen tenia tenian cuenta cuentan conto asciende ascendio ascienden totalizo
    totalizaron totaliza sera seran esta estan quedo quedaron suma suman sumo sumaron sumar
    supero superaron supera superan exceeded exceeds surpassed topped totals totalled
    llego llegaron llega llegan
    empresa empresas compania companias organizacion entidad
    actual actuales actualmente hoy presente vigente ahora
    reported reports reached reaches recorded records totaled totalled amounted amounts has had
    company companies organization organisation current currently now today
    aproximadamente alrededor cerca casi aprox about around approximately nearly roughly almost
    """.split()
)

NEGATIONS: frozenset[str] = frozenset(
    "no nunca jamas ningun ninguna ninguno ningunos ningunas tampoco nadie nada sin "
    "not never none nobody nothing neither nor without cannot dont doesnt didnt isnt arent wasnt werent".split()
)

# Fixed expressions that contain a negation word but do not negate the clause.
NEGATION_FALSE_FRIENDS: tuple[str, ...] = (
    "sin embargo",
    "no obstante",
    "no solo",
    "no solamente",
    "not only",
    "nonetheless",
)

HEDGE_WORDS: frozenset[str] = frozenset(
    """
    podria podrian podra podran puede pueden posible posiblemente probable probablemente quiza quizas
    estima estiman estimado estimada estimados estimadas estimacion preliminar preliminares tentativo
    tentativa borrador prevista previsto previstas previstos preve preven proyecta proyectan proyectado
    proyectada proyeccion espera esperan esperado esperada planea planean plan meta metas objetivo
    aproximado sujeto pendiente pendientes eventual eventualmente
    may might could possibly probably likely estimated estimate preliminary projected projection expected
    forecast forecasts forecasted pronostico pronostica pronostican
    expects planned plans target targets aims tentative draft unconfirmed potential potentially
    """.split()
)

HEDGE_PHRASES: tuple[str, ...] = (
    "se estima",
    "se espera",
    "se preve",
    "no confirmado",
    "sujeto a",
    "sujeta a",
    "sujetos a",
    "sujetas a",
    "condicion de que",
    "condicionado a",
    "condicionada a",
    "contingent on",
    "conditional on",
    "a confirmar",
    "por confirmar",
    "creo que",
    "en mi opinion",
    "i think",
    "i believe",
    "subject to",
    "to be confirmed",
)

UNIVERSAL_QUANTIFIERS: frozenset[str] = frozenset(
    "todos todas todo toda siempre nunca ningun ninguna ninguno cada totalidad integramente "
    "all every everyone always never none entire entirely whole".split()
)

PARTIAL_QUANTIFIERS: frozenset[str] = frozenset(
    "algunos algunas alguno alguna varios varias muchos muchas mayoria parte parcial parcialmente "
    "ocasionalmente frecuentemente generalmente minoria "
    "some several many most majority part partial partially often sometimes occasionally usually minority".split()
)

# Quantifiers that imply a proportion: (exclusive lower bound, exclusive upper bound) in percent.
PROPORTION_RANGES: dict[str, tuple[float, float]] = {
    "mayoria": (50.0, 100.01),
    "majority": (50.0, 100.01),
    "minoria": (-0.01, 50.0),
    "minority": (-0.01, 50.0),
    "mitad": (44.99, 55.01),
    "half": (44.99, 55.01),
}

APPROX_MARKERS: tuple[str, ...] = (
    "aproximadamente",
    "alrededor de",
    "cerca de",
    "casi",
    "unos",
    "unas",
    "aprox",
    "about",
    "around",
    "approximately",
    "nearly",
    "roughly",
    "almost",
    "close to",
    "~",
)
MIN_MARKERS: tuple[str, ...] = ("mas del", "superior al", "supero", "superaron", "supera", "superan",
                                "exceeded", "exceeds", "surpassed", "mas de", "por encima de", "al menos", "superior a", "more than", "over", "above", "at least")
MAX_MARKERS: tuple[str, ...] = ("menos del", "inferior al", "menos de", "por debajo de", "como maximo", "inferior a", "less than", "fewer than", "under", "below", "at most")

DIRECTION_UP_PREFIXES: tuple[str, ...] = (
    "aument", "crec", "crece", "increment", "subi", "subio", "alza", "elev", "amplio", "ampliaron", "expandi",
    "superior", "mejoro", "mejoraron", "increas", "rose", "rise", "rising", "grew", "grow", "gain", "expand",
    "improv", "higher",
)
DIRECTION_DOWN_PREFIXES: tuple[str, ...] = (
    "dismin", "reduj", "reduc", "bajar", "bajaron", "bajaba", "bajada", "bajan", "bajo", "cayo", "cayeron", "cae", "caida", "descend", "descen",
    "decrec", "contraj", "retroced", "empeor", "inferior", "decreas", "fell", "falls", "fallen", "falling",
    "drop", "declin",
    "shrank", "shrink", "lower", "worsen",
)
# Tokens that start like a direction prefix but are not directional.
DIRECTION_EXCEPTIONS: frozenset[str] = frozenset(
    "caen caer elevado crecientes superiores inferiores reducido reducida bajo".split()
)

MONTHS: dict[str, int] = {
    **{m: i + 1 for i, m in enumerate(
        "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
    )},
    "setiembre": 9,
    **{m: i + 1 for i, m in enumerate(
        "january february march april may june july august september october november december".split()
    )},
}
# "may" is too ambiguous in English text to be read as a month.
AMBIGUOUS_MONTHS: frozenset[str] = frozenset({"may"})

NON_CHECKABLE_PATTERNS: tuple[str, ...] = (
    "espero que",
    "no dudes",
    "si necesitas",
    "si tienes",
    "quedo atento",
    "con gusto",
    "hope this",
    "let me know",
    "feel free",
    "happy to help",
)

# Each group maps to the first entry as the canonical word.
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ingresos", "ventas", "facturacion", "revenue", "revenues", "sales"),
    ("empleados", "colaboradores", "trabajadores", "personal", "plantilla", "employees", "staff", "workforce"),
    ("camiones", "unidades", "vehiculos", "trucks", "vehicles"),
    ("gerente", "ceo", "director", "directora", "manager"),
    ("crecimiento", "crecer", "crecio", "crecieron", "aumento", "aumentar", "aumentaron", "incremento",
     "incrementar", "growth", "grow", "grew", "increase", "increased"),
    ("disminucion", "disminuir", "disminuyo", "disminuyeron", "reducir", "redujo", "redujeron", "reduccion",
     "decrease", "decreased", "reduce", "reduced", "reduction"),
    ("clientes", "customers", "clients"),
    ("emisiones", "emissions"),
    ("utilidad", "ganancia", "beneficio", "profit", "earnings"),
)

# ---------------------------------------------------------------------------
# Safety-guard lexicons (see safety.py). Exact folded tokens unless noted.
# ---------------------------------------------------------------------------

# "Nothing was found" statements: absence of evidence, not evidence of absence (phrases).
ABSENCE_PHRASES: tuple[str, ...] = (
    "no se encontro", "no se encontraron", "no se identifico", "no se identificaron", "no se detecto",
    "no se detectaron", "no consta", "no constan", "no se dispone", "no hay registro", "no existe registro",
    "no existen registros", "sin registro", "no fue posible verificar", "no se pudo verificar",
    "no fue posible confirmar", "no se pudo confirmar", "sin informacion", "no hay informacion",
    "no se reporto", "no se reportaron", "no se tiene informacion", "no se cuenta con informacion",
    "not found", "no record", "no records", "no evidence", "could not be verified", "could not be confirmed",
    "was not identified", "were not identified", "no information", "not available", "no disponible",
    "falta de pruebas", "falta de evidencia", "no hay evidencia", "no hay pruebas", "sin pruebas",
    "no fueron medid", "no fue medid", "no se midi", "no ha sido medid", "not measured", "not yet",
    "todavia no", "aun no", "not reported", "no se ha reportado", "no evidence of",
)

# Process stages: a request/proposal is not its outcome.
REQUEST_WORDS: frozenset[str] = frozenset(
    """
    solicito solicitaron solicita solicitan solicitado solicitada solicitud solicitudes pidio pidieron pide
    peticion postulo postularon postulacion propuso propusieron propuesta propone proponen tramita tramitan
    gestiona gestionan recomendo recomendaron recomendacion sugirio sugirieron planteo
    applied applies application applications requested request requests proposed proposal proposes pending
    recommended recommendation filed seeks sought seeking
    """.split()
)
REQUEST_PHRASES: tuple[str, ...] = (
    "en evaluacion", "en revision", "bajo revision", "en tramite", "a la espera", "under review", "being evaluated",
    "awaiting",
)
GRANT_WORDS: frozenset[str] = frozenset(
    """
    aprobo aprobaron aprobada aprobado aprobadas aprobados otorgo otorgaron otorgada otorgado otorgadas
    concedio concedieron concedida concedido autorizo autorizaron autorizada autorizado obtuvo obtuvieron
    obtenida obtenido adjudico adjudicaron adjudicada adjudicado
    granted approved authorized authorised awarded obtained
    """.split()
)
REJECT_WORDS: frozenset[str] = frozenset(
    "rechazo rechazaron rechazada rechazado denego denegaron denegada denegado desestimo desestimada "
    "rejected denied declined refused dismissed".split()
)

# Passive voice ("B fue adquirida por A") reverses surface order of agent and patient.
PASSIVE_AUXILIARIES: frozenset[str] = frozenset("fue fueron sido siendo es son was were been being is are".split())
PASSIVE_AGENT_MARKERS: frozenset[str] = frozenset({"por", "by"})

# Nouns naming populations whose claims are generic ("los socios recibieron...").
POPULATION_NOUNS: frozenset[str] = frozenset(
    """
    empleados trabajadores colaboradores socios clientes usuarios hogares productores proveedores tiendas
    sucursales oficinas plantas sedes distritos regiones alumnos estudiantes pacientes afiliados miembros
    contratos agricultores familias comunidades locales centros
    employees workers staff members customers clients users households producers suppliers stores branches
    offices plants sites districts regions students patients affiliates farmers families communities centers
    """.split()
)
# Words that restrict a population to a subset.
SEGMENT_WORDS: frozenset[str] = frozenset(
    """
    planta sede sucursal filial region zona area segmento division departamento turno piloto distrito
    provincia oficina unidad almacen local agencia
    plant site branch subsidiary region zone area segment division department shift pilot district province
    office warehouse agency
    """.split()
)

# Information attributed to a third party or unconfirmed (phrases).
REPORTED_SPEECH_PHRASES: tuple[str, ...] = (
    "afirmo que", "afirma que", "aseguro que", "asegura que", "sostuvo que", "declaro que", "dijo que",
    "alego que", "manifesto que", "segun fuentes", "segun un medio", "segun medios", "segun versiones",
    "de acuerdo con fuentes", "habria", "habrian", "presuntamente", "supuestamente", "trascendio",
    "extraoficialmente", "claimed that", "claims that", "alleged", "allegedly", "reportedly", "said that",
    "stated that", "according to sources", "rumored", "rumoured",
    # self-declared or unverified figures
    "declaro tener", "declara tener", "declaro contar", "segun declaro", "autodeclarad",
    "no pudo ser contrastad", "no pudo ser verificad", "no pudo ser confirmad", "no ha sido verificad",
    "no ha sido confirmad", "no ha confirmado", "sin confirmar", "sin verificar", "no verificad",
    "not been verified", "not been confirmed", "unverified", "unconfirmed", "self-reported",
)

# A sentence that corrects a figure: only the final value stands.
CORRECTION_WORDS: frozenset[str] = frozenset(
    "corregida corregido corrigio corrigieron rectifico rectificaron rectificada rectificado "
    "corrected restated retracted amended".split()
)

# Modality.
CONDITIONAL_WORDS: frozenset[str] = frozenset(
    "podria podrian tendria tendrian habria habrian seria serian haria harian would could might".split()
)
# Nouns that end like conditional verbs ("-ería", "-aría").
CONDITIONAL_FALSE_FRIENDS: frozenset[str] = frozenset(
    "secretaría tesorería ingeniería batería baterías galería lotería librería panadería cervecería ferretería "
    "mensajería consejería concejería alcaldía".split()
)
# "X, frente a Y": a figure compared with a baseline (phrases).
COMPARISON_MARKERS: tuple[str, ...] = (
    "frente a", "frente al", "comparado con", "en comparacion con", "compared with", "compared to", "versus",
)
POPULATION_DETERMINERS: frozenset[str] = frozenset("los las sus todos todas the all their".split())
PILOT_WORDS: frozenset[str] = frozenset("piloto pilotos pilot pilots prueba trial".split())
# Prepositions that mark an entity's role in a relation ("de X por Y", "from X to Y").
ROLE_PREPOSITIONS: frozenset[str] = frozenset("de del por a al para con contra desde hacia by of to from for with against".split())

# Closed-class operators that change what a sentence asserts about its content.
SCOPE_OPERATORS: frozenset[str] = frozenset(
    "o u ni excepto salvo exceptuando solo solamente unicamente sino or either nor except excluding "
    "only just merely solely instead segundo segunda tercero tercera tercer cuarto cuarta quinto quinta "
    "second third fourth fifth".split()
)
SCOPE_OPERATOR_PHRASES: tuple[str, ...] = (
    "en vez de", "en lugar de", "rather than", "a excepcion de", "other than", "una de las", "uno de los",
    "one of the",
)
# Words introducing an embedded proposition ("afirman que …", "it is unclear whether …").
COMPLEMENTIZERS: frozenset[str] = frozenset("que that whether".split())
# Words naming a sub-period ("primer semestre", "first quarter").
SUBPERIOD_WORDS: frozenset[str] = frozenset(
    "trimestre trimestres semestre semestres bimestre quarter quarters q1 q2 q3 q4 h1 h2 t1 t2 t3 t4 "
    "midyear interim".split()
)
SINGULAR_DETERMINERS: frozenset[str] = frozenset("un una uno one single".split())
NUMBER_WORDS: frozenset[str] = frozenset(
    "uno una dos tres cuatro cinco seis siete ocho nueve diez mitad tercio cuarto one two three four five six "
    "seven eight nine ten half third quarter".split()
)
# Verbs of saying/accusing whose complement is someone's statement, not an established fact.
REPORTING_VERBS: frozenset[str] = frozenset(
    """
    dijo dijeron dice dicen afirmo afirmaron afirma afirman aseguro aseguraron asegura aseguran declaro declararon
    sostuvo sostienen sostiene senalo senalaron indico indicaron anuncio anunciaron prometio prometieron promete
    nego negaron niega niegan denuncio denunciaron denuncia denuncian acuso acusaron acusa acusan acusada acusado
    alego alegaron alega investigada investigado investigan investiga absuelta absuelto
    said says say claim claims claimed stated states told announced promised denied denies deny alleged alleges
    accused accuses reported reports cleared acquitted investigated suspected declared declares pointed
    """.split()
)
# Attribution to a party (not to a cited document): "según la empresa", "according to a rumor".
SOURCE_PHRASES: tuple[str, ...] = tuple(
    f"{lead} {who}"
    for lead in ("segun", "de acuerdo con", "according to")
    for who in ("fuentes", "un medio", "medios", "su propio", "sus propios", "la empresa", "la compania", "el gerente",
                "la gerencia", "voceros", "un vocero", "un portavoz", "a rumor", "rumors", "sources", "the company",
                "its own", "a spokesperson", "management", "people familiar")
)
QUOTE_MARKS: tuple[str, ...] = ('"', "«", "»", "“", "”")
# A negation next to one of these is a report of not finding something ("found no …", "no se registraron …").
EPISTEMIC_PREFIXES: tuple[str, ...] = (
    "encontr", "hall", "identific", "detect", "registr", "report", "observ", "constat", "verific", "regist",
    "found", "identif", "detect", "record", "observ", "report", "verif", "measur", "medid", "midi",
)
# Present-tense state predicates vs past-tense event markers.
PRESENT_STATE_WORDS: frozenset[str] = frozenset(
    "es son esta estan tiene tienen cuenta cuentan opera operan ocupa ocupan sigue siguen continua continuan "
    "mantiene mantienen posee poseen dirige dirigen preside is are has have holds hold operates operate remains "
    "remain continues continue runs run leads lead".split()
)
PAST_STATE_WORDS: frozenset[str] = frozenset(
    "fue fueron era eran estuvo estuvieron tuvo tuvieron tenia tenian habia was were had used".split()
)
DETERMINERS: frozenset[str] = frozenset("el la los las al del lo un una unos unas the a an".split())

# ---------------------------------------------------------------------------
# English morphology and idioms (see text.py, numbers.py and safety.py).
# ---------------------------------------------------------------------------

# Words whose five-letter stem coincides with a synonym member's stem but which mean something else
# ("plant" is not "plantilla", the workforce; "direction" is not "director"). Each maps to its own base
# word, which is used as its term instead of the synonym.
STEM_COLLISIONS: dict[str, str] = {
    **dict.fromkeys(("plant", "plants", "planted", "planting"), "plant"),
    **dict.fromkeys(("plantation", "plantations"), "plantation"),
    **dict.fromkeys(("planta", "plantas"), "planta"),
    **dict.fromkeys(("plantacion", "plantaciones"), "plantacion"),
    **dict.fromkeys(("direction", "directions"), "direction"),
    **dict.fromkeys(("direct", "directly", "directed"), "direct"),
    **dict.fromkeys(("directive", "directives"), "directive"),
    **dict.fromkeys(("utility", "utilities"), "utility"),
    **dict.fromkeys(("utilize", "utilized", "utilization"), "utilize"),
    **dict.fromkeys(("profile", "profiles"), "profile"),
    **dict.fromkeys(("custody", "custodial"), "custody"),
    **dict.fromkeys(("custodian", "custodians"), "custodian"),
    **dict.fromkeys(("decree", "decrees", "decreed"), "decree"),
    **dict.fromkeys(("dismiss", "dismissed", "dismisses", "dismissal"), "dismiss"),
    **dict.fromkeys(("incredible", "incredibly"), "incredible"),
    **dict.fromkeys(("customs",), "customs"),
    **dict.fromkeys(("benefit", "benefits"), "benefit"),
    **dict.fromkeys(("decreto", "decretos"), "decreto"),
    **dict.fromkeys(("plantear", "plantea", "plantean", "planteo", "plantearon", "planteamiento", "planteamientos"),
                    "plantear"),
    **dict.fromkeys(("utilizar", "utiliza", "utilizan", "utilizo", "utilizaron", "utilizado", "utilizada",
                     "utilizados", "utilizadas", "utilizacion"), "utilizar"),
}

# Six-letter "-ly" adverbs that mean their four-letter base ("mainly" -> "main"); longer adverbs already share
# their base's five-letter stem. Other six-letter words ("highly", "firmly", "costly") keep their own stem.
SHORT_LY_ADVERBS: frozenset[str] = frozenset("mainly partly".split())

# Idioms that contain a segment word without naming a unit of the organization ("took office").
SEGMENT_IDIOMS: tuple[str, ...] = (
    "took office", "take office", "takes office", "taken office", "taking office", "assumed office",
    "assumes office", "left office", "leave office", "leaves office", "term of office", "remained in office",
    "remains in office",
)
# Sub-periods named by a phrase rather than a single word.
SUBPERIOD_PHRASES: tuple[str, ...] = ("first half", "second half")
# Ordinals that make "half" a period ("first half"), not a proportion.
HALF_PERIOD_ORDINALS: frozenset[str] = frozenset("first second primera primer segunda segundo".split())
# English singular nouns before which a determiner and a 4-digit number name a year ("the 2024 collection");
# plural nouns ("accounts", "results") are left out because they also follow counts ("its 2000 accounts").
ATTRIBUTIVE_YEAR_NOUNS: frozenset[str] = frozenset(
    """
    report financial annual fiscal budget census election harvest season edition campaign collection review
    survey audit plan filing
    """.split()
)
# Auxiliaries after which a verb is an infinitive, not a completed action ("could expand").
MODAL_AUXILIARIES: frozenset[str] = frozenset("can could may might must shall should will would".split())
