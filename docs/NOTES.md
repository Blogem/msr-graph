## Goal

Run a knowledge graph POC on molten salt reactor related data, to show:

- Knowledge graph: build a knowledge graph with ontology and instantiation of the domain (domain needs to be focused)
- NER: parse unstructured data to populate the graph with entities and relationships
- Self-evolving graph: detect new classes and properties based on incoming data, and provide simple interface to evolve the ontology after human review
- Structured data: connect structured data to the graph (does not have to be loaded in the graph), for analysis
- AI data analysis: show what happens when an LLM both understand the domain (the knowledge graph) and has access to the data. It should show more interesting outcomes.

So two main concepts need to be highlighted:

- self-evolving ontology
- AI data analysis grounded by a knowledge graph and real data

The domain is:

- engineering of molten salt reactors
- IAEA safety standards related to molten salt reactors

## Ontology & vocabulary

### DIAMOND

- https://github.com/idaholab/DIAMOND
- not maintained and never left alpha state
- is there anything better? maybe fine for the POC

### IAEA INIS thesaurus

- https://www.iaea.org/publications/7678/inis-multilingual-thesaurus-arabic-chinese-english-french-german-russian-spanish
- no machine readable version publicly available
- PDF version is available, so can be parsed: https://www.iaea.org/sites/default/files/18/09/inis_thesaurus_2018_09_english.pdf
- model using SKOS

## Data

### msr-archive (unstructured)

- https://github.com/openmsr/msr-archive
- curated documents pertaining to early molten salt reactor research
- NER into the graph

### IAEA safety standards (unstructured)

- https://www-pub.iaea.org/MTCD/Publications/PDF/PUB2027_Web.pdf
- APPLICABILITY OF IAEA SAFETY STANDARDS TO NON-WATER COOLED REACTORS AND SMALL MODULAR REACTORS
- NER into the graph. Possibily extend ontology with safety (haven't reviewed the ontology yet)

### NIST Properties of Molten Salts Database (structured)

- https://catalog.data.gov/dataset/data-from-nist-properties-of-molten-salts-database-formerly-srd-27
- The database was designed to provide engineers and scientists rapid access to critically evaluated data for inorganic salts in the molten state. Properties include density, viscosity, electrical conductance, and surface tension, although not all properties are given for all salts.
- model _what_ each column contains (e.g. the "Salt" column in density-csv.txt contains MoltenSalt (class))
- the unstructured data should contain similar information as some of the NIST properties data, so that AI can learn about the domain through the modelled unstructured data and then use that to query structured data

## Architecture

### Data architecture

- Needs to be focused on molten salt reactors, possibly a subdomain of that
- mapping key engineering data domains such as design, simulations, tests, requirements, safety, and documentation, and by defining shared models, taxonomies, and metadata structures.
- design the digital thread that links requirements, functions, design decisions, simulations, validation tests, safety evidence, and regulatory deliverables. This includes defining business objects, their relationships, and traceability rules across the full engineering lifecycle, ensuring that engineering justification can be followed, audited, and reused.
- needs to be available in the different datasets chosen

Related concepts to molten salt reactor:

MOLTEN SALT REACTORS
BT1 reactors
NT1 molten salt cooled reactors
NT2 msre reactor
NT1 molten salt fueled reactors
RT metal transfer process
RT molten salt fuels
RT reductive extraction

### Technical components

- Graph database: GraphDB (local docker)
- NER: spaCy
- Programming languages: Go where possibly, Python when needed
