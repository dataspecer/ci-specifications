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
The additional Python `--schema-cache` option is optional.

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

## Schema loading and stage timings

All major Python stages print start messages and elapsed wall time; XSLT also
separates compilation from execution. Timings are excluded from stable reports.
Schema downloads log their URL and duration so network waits are visible.

Remote XSD responses are cached for 24 hours in
`<repo>/_roundtrip/.schema-cache`, shared by samples and Docker invocations using
the same export mount. The first sample populates the cache. Python callers can
choose another writable directory with `--schema-cache`. Delete the cache to
force an immediate refresh. Local schemas and namespace overrides are always
read directly, so regenerated schemas take effect immediately.

The cache retains original URLs as the base for relative imports and uses atomic
writes. Failed downloads are not cached, and expired entries must be refreshed;
network failures continue to appear in validator diagnostics. Remote connection
attempts time out after 30 seconds (previously the validator default of 300).
Seekable downloaded responses also avoid a second HTTP fetch during XML safety
checks. Validation remains XSD 1.1 with the same findings and failure policies.

Cache regression tests can be run in the image with the source directory mounted:

```sh
docker run --rm --entrypoint python3 \
  --mount "type=bind,src=$PWD/tools/roundtrip,dst=/tests,readonly" \
  metadata-roundtrip -m unittest discover -s /tests
```

Measured against the four existing CCMM exports (2026-09-07, pinned Docker
image dependencies), sequential roundtrip processing took 38.4 seconds before
and 20.2 seconds with a warm cache, excluding Docker startup. All 40 report files
matched after normalizing output directories. An isolated `ccmm_sample.xml`
run spent 10.5 seconds loading schemas but only 0.044 seconds validating input.
The first optimized run downloaded 56 remote schemas and took 9.1 seconds total;
subsequent runs avoid those downloads. Warm schema construction still takes
about 3.2–3.7 seconds per sample. These measurements cover the roundtrip harness,
not Dataspecer export generation or Docker image pulls in `build-all.sh`.

GitHub Actions restores and saves the schema cache between CCMM jobs. Each run
saves a new cache snapshot so refreshed schemas replace expired entries in future
runs; the loader still applies its 24-hour TTL. Cache files are excluded from the
published export archive.

The workflow builds the harness with `docker/build-push-action` and the
[GitHub Actions layer cache](https://docs.docker.com/build/ci/github-actions/cache/),
then loads the image into Docker. `ROUNDTRIP_IMAGE` tells the CCMM build script to
use that prebuilt image. When unset, local builds continue building the harness
as before. Docker caches are scoped by matrix target to avoid parallel jobs
replacing each other's cache.
