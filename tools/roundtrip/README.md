# Metadata round-trip test

The harness runs the complete path without treating ordinary XSD or SHACL
findings as pipeline failures:

1. XML Schema 1.1 validation with `xmlschema.XMLSchema11`.
2. XML to RDF/XML with SaxonC-HE (`saxonche`) and the lifting stylesheet.
3. RDF/XML to conventional, readable Turtle and sorted, canonical N-Quads.
4. SHACL Core validation with pySHACL against the canonical RDF statements.
5. Canonical N-Quads to SPARQL Results XML, preserving language and datatype metadata.
6. SPARQL Results XML to XML with the lowering stylesheet.
7. A concise, prefix-insensitive XML content and ordering comparison.
8. XSD 1.1 validation of the round-trip XML.

Reports are written to the required `ROUNDTRIP_OUTPUT` directory. Validation report entries and
N-Quads statements are sorted to keep future Git diffs useful. Turtle is left in
a conventional grouped form for reading. The N-Quads file uses canonical
blank-node identifiers and is the machine input for the later stages.

## Run in Docker

From the repository root, build the image and mount a generated CCMM export:

```sh
docker build -t metadata-roundtrip tools/roundtrip
mkdir -p exports/ccmm/_roundtrip
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$PWD/exports/ccmm,dst=/workspace" \
  --env ROUNDTRIP_REPO=/workspace \
  --env ROUNDTRIP_SCHEMA=dataset/schema.xsd \
  --env ROUNDTRIP_LIFTING=dataset/lifting.xslt \
  --env ROUNDTRIP_LOWERING=dataset/lowering.xslt \
  --env ROUNDTRIP_SHACL=shacl.ttl \
  --env ROUNDTRIP_BASE_IRI=urn:roundtrip:base: \
  --env ROUNDTRIP_SCHEMA_LOCATIONS= \
  --env ROUNDTRIP_FAIL_ON=pipeline \
  --env ROUNDTRIP_INPUT=_xml/ccmm_sample.xml \
  --env ROUNDTRIP_OUTPUT=_roundtrip/ccmm_sample \
  metadata-roundtrip
```

The image contains only the harness; the export must be mounted at `/workspace`.
`specifications/ccmm/build.sh` builds the image and runs every XML sample, writing
reports to `_roundtrip/<sample-name>/` in the export.

## Configuration

Every variable below must be explicitly set. Missing or empty values fail before
processing, except `ROUNDTRIP_SCHEMA_LOCATIONS`, which may be explicitly empty.
All paths are relative to `ROUNDTRIP_REPO` unless absolute. The Python CLI likewise
requires every corresponding option, and both Node helpers require a base IRI.

| Variable | Meaning |
| --- | --- |
| `ROUNDTRIP_REPO` | Existing root directory containing the inputs |
| `ROUNDTRIP_INPUT` | Input XML file |
| `ROUNDTRIP_SCHEMA` | XSD schema |
| `ROUNDTRIP_LIFTING` | Lifting stylesheet |
| `ROUNDTRIP_LOWERING` | Lowering stylesheet |
| `ROUNDTRIP_SHACL` | SHACL shapes file |
| `ROUNDTRIP_OUTPUT` | Report directory |
| `ROUNDTRIP_BASE_IRI` | Base IRI for RDF conversion |
| `ROUNDTRIP_SCHEMA_LOCATIONS` | Semicolon-separated `namespace=path` mappings; empty for none |
| `ROUNDTRIP_FAIL_ON` | Comma-separated failure policies |

Validation may require network access to resolve remote schema imports when no
local mappings are supplied.

`ROUNDTRIP_FAIL_ON` accepts `pipeline`, `xsd`, `shacl`, `diff`, `all`, or
`none`, separated by commas. `pipeline` exits non-zero for broken
transformation/conversion/validator stages while reporting data quality findings.
For a strict gate, use `all`.

The Docker build context is `tools/roundtrip`; its `.dockerignore` includes only
the harness source, dependency manifests, and Docker build files.

## XSLT performance

Lifting and lowering use the native [SaxonC-HE processor](https://www.saxonica.com/saxon-c/doc13/python/xslt/processor.html). Each stage logs separate
compilation and transformation times to the console; timing is excluded from
report files to keep their diffs stable. Generated stylesheets are compiled as
exported, preserving their import precedence. No compiled stylesheet cache or
additional configuration is required.

Compared with SaxonJS, XML serialization can change namespace declaration order,
including inside GML literals. This can also change canonical blank-node labels
in RDF reports. XML content and element ordering are checked separately from
these serialization differences.
