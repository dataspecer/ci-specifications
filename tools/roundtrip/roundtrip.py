#!/usr/bin/env python3
"""Run an XML -> RDF -> XML round trip and write stable reports."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
from time import perf_counter, time
from functools import wraps
from urllib.request import OpenerDirector, build_opener
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import xmlschema
from lxml import etree
from pyshacl import validate as shacl_validate
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import RDF, RDFS, SH, XSD
from saxonche import PySaxonProcessor


REPORT_FILES = (
    "00-summary.txt",
    "01-schema-validation.txt",
    "02-rdf.xml",
    "02-lifting-error.txt",
    "03-rdf.ttl",
    "03-rdf.nq",
    "03-rdf-conversion-error.txt",
    "04-shacl-validation.txt",
    "05-sparql-results.xml",
    "05-sparql-conversion-error.txt",
    "06-roundtrip.xml",
    "06-lowering-error.txt",
    "07-roundtrip-comparison.txt",
    "08-roundtrip-schema-validation.txt",
)


def timed(function):
    """Keep wall-clock timings in the console, outside stable report files."""
    @wraps(function)
    def measured(*args, **kwargs):
        print(f"{function.__name__}: starting", flush=True)
        started = perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            print(f"{function.__name__}: {perf_counter() - started:.3f}s", flush=True)
    return measured


class SchemaOpener(OpenerDirector):
    """Cache successful HTTP schema reads without changing their base URLs.

    Returning seekable streams also avoids xmlschema downloading a remote
    resource twice when it checks for unsafe XML before parsing it.
    """
    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.delegate = build_opener()

    def open(self, fullurl, data=None, timeout=30):
        url = fullurl if isinstance(fullurl, str) else fullurl.full_url
        if not url.startswith(("http://", "https://")) or data is not None:
            return self.delegate.open(fullurl, data=data, timeout=timeout)
        self.directory.mkdir(parents=True, exist_ok=True)
        cached = self.directory / (hashlib.sha256(url.encode()).hexdigest() + ".xsd")
        if cached.is_file() and time() - cached.stat().st_mtime < 86400:
            return io.BytesIO(cached.read_bytes())
        started = perf_counter()
        print(f"Schema download: {url}", flush=True)
        try:
            with self.delegate.open(fullurl, timeout=timeout) as response:
                content = response.read()
            # Do not retain malformed responses (e.g. HTML error pages).
            root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
            if root.tag == "{http://www.w3.org/2001/XMLSchema}schema":
                with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as temporary:
                    temporary.write(content)
                    temporary_path = Path(temporary.name)
                try:
                    temporary_path.replace(cached)
                finally:
                    temporary_path.unlink(missing_ok=True)
            return io.BytesIO(content)
        finally:
            print(f"Schema download: {perf_counter() - started:.3f}s ({url})", flush=True)


@dataclass
class Stage:
    name: str
    status: str
    details: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    def nonempty(value: str) -> str:
        if not value.strip():
            raise argparse.ArgumentTypeError("must not be empty")
        return value

    for name in ("repo", "input", "schema", "lifting", "lowering", "shacl", "output", "base-iri"):
        parser.add_argument(f"--{name}", required=True, type=nonempty)
    parser.add_argument(
        "--schema-locations",
        required=True,
        help="semicolon-separated namespace=path overrides; pass an empty string for none",
    )
    parser.add_argument(
        "--fail-on",
        required=True,
        type=nonempty,
        help="comma-separated: pipeline,xsd,shacl,diff,all,none",
    )
    parser.add_argument("--schema-cache", help="HTTP schema cache directory (default: <repo>/_roundtrip/.schema-cache)")
    args = parser.parse_args()
    policies = {item.strip().lower() for item in args.fail_on.split(",")}
    if not policies <= {"pipeline", "xsd", "shacl", "diff", "all", "none"}:
        parser.error("--fail-on contains an unknown or empty policy")
    if not Path(args.repo).is_dir():
        parser.error("--repo must be an existing directory")
    return args


def resolve(repo: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo / path).resolve()


def display_path(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def clean_text(value: object, repo: Path, output: Path) -> str:
    text = " ".join(str(value or "").split())
    text = text.replace(str(repo), "<repo>").replace(str(output), "<report>")
    return text


def write_text(path: Path, lines: Iterable[str] | str) -> None:
    if isinstance(lines, str):
        content = lines
    else:
        content = "\n".join(lines)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def remove_stale_outputs(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in REPORT_FILES:
        candidate = output / name
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def parse_schema_locations(raw: str, repo: Path) -> dict[str, str]:
    locations: dict[str, str] = {}
    for entry in filter(None, (item.strip() for item in raw.split(";"))):
        if "=" not in entry:
            raise ValueError(f"invalid schema location {entry!r}; expected namespace=path")
        namespace, location = entry.rsplit("=", 1)
        local_path = resolve(repo, location)
        if local_path.exists():
            locations[namespace] = local_path.as_uri()
    return locations


def format_xsd_error(error: object, repo: Path, output: Path) -> tuple[str, list[str]]:
    path = clean_text(getattr(error, "path", "(schema)"), repo, output) or "(schema)"
    reason = clean_text(getattr(error, "reason", error), repo, output)
    line = getattr(error, "sourceline", None)
    signature = normalize_xsd_signature(path, reason)
    details = [f"path: {path}"]
    if line is not None:
        details.append(f"line: {line}")
    details.append(f"reason: {reason}")
    return signature, details


def normalize_xsd_signature(path: str, reason: str) -> str:
    """Remove instance-specific namespace notation before comparing findings."""
    normalized_path = re.sub(r"(?<=/)[A-Za-z_][\w.-]*:", "", path)
    normalized_reason = re.sub(r"\{[^{}]+\}", "", reason)
    normalized_reason = re.sub(r"(?<=')[A-Za-z_][\w.-]*:", "", normalized_reason)
    return f"{normalized_path} | {normalized_reason}"


@timed
def build_schema(
    schema_path: Path, locations: dict[str, str], repo: Path, output: Path,
    cache: Path | None = None,
) -> tuple[object | None, list[object], list[str], str | None]:
    caught: list[warnings.WarningMessage]
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            schema = xmlschema.XMLSchema11(
                schema_path,
                validation="lax",
                locations=locations,
                allow="all",
                defuse="remote",
                opener=SchemaOpener(cache or repo / "_roundtrip" / ".schema-cache"),
                timeout=30,
            )
        warning_lines = sorted(
            {clean_text(item.message, repo, output) for item in caught if str(item.message).strip()}
        )
        return schema, list(schema.all_errors), warning_lines, None
    except Exception as error:  # A schema loader failure belongs in the report.
        return None, [], [], clean_text(error, repo, output)


@timed
def validate_xml(
    xml_path: Path,
    schema_path: Path,
    schema: object | None,
    schema_errors: list[object],
    schema_warnings: list[str],
    schema_failure: str | None,
    report_path: Path,
    repo: Path,
    output: Path,
) -> dict[str, object]:
    instance_errors: list[object] = []
    failure = schema_failure
    if schema is not None:
        try:
            instance_errors = list(schema.iter_errors(xml_path, use_defaults=False))
        except Exception as error:
            failure = clean_text(error, repo, output)

    if failure:
        status = "ERROR"
    elif schema_errors or instance_errors:
        status = "INVALID"
    else:
        status = "VALID"

    lines = [
        f"Status: {status}",
        f"Document: {display_path(xml_path, repo)}",
        f"Schema: {display_path(schema_path, repo)}",
        "Schema language: XSD 1.1",
        "Validator: xmlschema.XMLSchema11",
        f"Schema build errors: {len(schema_errors)}",
        f"Document validation errors: {len(instance_errors)}",
        f"Schema warnings: {len(schema_warnings)}",
    ]
    if failure:
        lines.extend(["", "Fatal validator error:", failure])
    if schema_warnings:
        lines.extend(["", "Schema warnings:"])
        lines.extend(f"- {item}" for item in schema_warnings)

    signatures: list[str] = []
    all_errors = [("schema", item) for item in schema_errors] + [
        ("document", item) for item in instance_errors
    ]
    if all_errors:
        lines.extend(["", "Findings:"])
    formatted = []
    for category, error in all_errors:
        signature, details = format_xsd_error(error, repo, output)
        signatures.append(f"{category} | {signature}")
        formatted.append((category, signature, details))
    formatted.sort(key=lambda item: (item[0], item[1]))
    for index, (category, _signature, details) in enumerate(formatted, 1):
        lines.extend(["", f"[{index:03d}] category: {category}"])
        lines.extend(details)
    write_text(report_path, lines)
    return {
        "status": status,
        "schema_errors": len(schema_errors),
        "instance_errors": len(instance_errors),
        "signatures": sorted(signatures),
        "failure": failure,
    }


@timed
def run_command(
    command: list[str], cwd: Path, output_file: Path, stdout_is_output: bool = False
) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except Exception as error:
        return False, str(error)
    if stdout_is_output and completed.returncode == 0:
        output_file.write_text(completed.stdout, encoding="utf-8")
        diagnostic_parts = (completed.stderr,)
    else:
        diagnostic_parts = (completed.stdout, completed.stderr)
    diagnostic = "\n".join(part.strip() for part in diagnostic_parts if part.strip())
    return completed.returncode == 0 and output_file.is_file(), diagnostic


def run_xslt(
    stylesheet: Path, source: Path, destination: Path, repo: Path
) -> tuple[bool, str]:
    destination.unlink(missing_ok=True)
    label = display_path(stylesheet, repo)
    print(f"XSLT {label}: compiling", flush=True)
    started = perf_counter()
    try:
        with PySaxonProcessor(license=False) as processor:
            xslt = processor.new_xslt30_processor()
            executable = xslt.compile_stylesheet(stylesheet_file=str(stylesheet))
            compiled = perf_counter()
            print(f"XSLT {label}: compiled in {compiled - started:.3f}s; transforming", flush=True)
            executable.transform_to_file(source_file=str(source), output_file=str(destination))
            print(f"XSLT {label}: transformed in {perf_counter() - compiled:.3f}s", flush=True)
    except Exception as error:
        destination.unlink(missing_ok=True)
        return False, str(error)
    return destination.is_file(), ""


@timed
def canonicalize_rdf(raw_turtle: Path, turtle_path: Path, nquads_path: Path) -> int:
    parsed = Graph().parse(raw_turtle, format="turtle")
    canonical = to_canonical_graph(parsed)
    graph = Graph()
    prefixes = {
        "rdf": RDF,
        "rdfs": RDFS,
        "xsd": XSD,
        "sh": SH,
        "dcat": Namespace("http://www.w3.org/ns/dcat#"),
        "dcterms": Namespace("http://purl.org/dc/terms/"),
        "foaf": Namespace("http://xmlns.com/foaf/0.1/"),
        "geo": Namespace("http://www.opengis.net/ont/geosparql#"),
        "locn": Namespace("http://www.w3.org/ns/locn#"),
        "org": Namespace("http://www.w3.org/ns/org#"),
        "prov": Namespace("http://www.w3.org/ns/prov#"),
        "skos": Namespace("http://www.w3.org/2004/02/skos/core#"),
        "spdx": Namespace("http://spdx.org/rdf/terms#"),
        "time": Namespace("http://www.w3.org/2006/time#"),
        "vcard": Namespace("http://www.w3.org/2006/vcard/ns#"),
        "ccmm": Namespace("https://model.ccmm.cz/vocabulary/ccmm#"),
        "datacite": Namespace("https://w3id.org/tib/datacite/property/"),
        "adms": Namespace("http://www.w3.org/ns/adms#"),
    }
    for prefix, namespace in prefixes.items():
        graph.bind(prefix, namespace, override=True, replace=True)
    for triple in canonical:
        graph.add(triple)

    # Turtle is the human-facing view, so retain the conventional grouped form.
    # The canonical, sorted N-Quads companion is the stable diff/machine format.
    turtle = "\n".join(line.rstrip() for line in graph.serialize(format="longturtle").splitlines())
    turtle_path.write_text(turtle.rstrip() + "\n", encoding="utf-8")
    ntriples = graph.serialize(format="nt")
    lines = sorted(line for line in ntriples.splitlines() if line.strip())
    # Every N-Triples statement is also a legal default-graph N-Quads statement.
    write_text(nquads_path, lines)
    return len(graph)


def rdf_term(term: object | None) -> str:
    if term is None:
        return "(none)"
    if isinstance(term, URIRef):
        return f"<{term}>"
    if isinstance(term, BNode):
        return f"_:{term}"
    if isinstance(term, Literal):
        return term.n3()
    return str(term)


@timed
def run_shacl(data_path: Path, shapes_path: Path, report_path: Path) -> dict[str, object]:
    try:
        parsed_data = Graph().parse(data_path, format="nt")
        data_graph = Graph()
        for triple in to_canonical_graph(parsed_data):
            data_graph.add(triple)
        shapes_graph = Graph().parse(shapes_path, format="turtle")
        conforms, report_graph, _report_text = shacl_validate(
            data_graph=data_graph,
            shacl_graph=shapes_graph,
            inference="none",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
            advanced=False,
            meta_shacl=False,
            do_owl_imports=False,
        )
        results = []
        for result in report_graph.subjects(RDF.type, SH.ValidationResult):
            messages = sorted(rdf_term(value) for value in report_graph.objects(result, SH.resultMessage))
            item = {
                "severity": rdf_term(report_graph.value(result, SH.resultSeverity)),
                "focus": rdf_term(report_graph.value(result, SH.focusNode)),
                "path": rdf_term(report_graph.value(result, SH.resultPath)),
                "value": rdf_term(report_graph.value(result, SH.value)),
                "shape": rdf_term(report_graph.value(result, SH.sourceShape)),
                "constraint": rdf_term(report_graph.value(result, SH.sourceConstraintComponent)),
                "messages": messages,
            }
            results.append(item)
        results.sort(
            key=lambda item: (
                item["severity"],
                item["focus"],
                item["path"],
                item["constraint"],
                item["value"],
                tuple(item["messages"]),
            )
        )
        severity_counts = Counter(item["severity"] for item in results)
        lines = [
            f"Status: {'CONFORMS' if conforms else 'NON-CONFORMANT'}",
            f"Data: {data_path.name}",
            f"Shapes: {shapes_path.name}",
            "Validator: pySHACL (SHACL Core, no inference)",
            f"Validation results: {len(results)}",
        ]
        if severity_counts:
            lines.append("Severity counts:")
            lines.extend(f"- {severity}: {count}" for severity, count in sorted(severity_counts.items()))
        if results:
            lines.extend(["", "Findings:"])
        for index, item in enumerate(results, 1):
            lines.extend(
                [
                    "",
                    f"[{index:03d}] severity: {item['severity']}",
                    f"focus node: {item['focus']}",
                    f"result path: {item['path']}",
                    f"value: {item['value']}",
                    f"source shape: {item['shape']}",
                    f"constraint: {item['constraint']}",
                ]
            )
            lines.extend(f"message: {message}" for message in item["messages"])
        write_text(report_path, lines)
        return {"status": "CONFORMS" if conforms else "NON-CONFORMANT", "count": len(results)}
    except Exception as error:
        write_text(
            report_path,
            [
                "Status: ERROR",
                f"Data: {data_path.name}",
                f"Shapes: {shapes_path.name}",
                "",
                "Fatal validator error:",
                str(error),
            ],
        )
        return {"status": "ERROR", "count": 0, "failure": str(error)}


XML_NAMESPACES = {
    "https://schema.ccmm.cz/research-data/2.0": "ccmm",
    "http://www.opengis.net/gml/3.2": "gml",
    "http://www.w3.org/2001/XMLSchema-instance": "xsi",
    "http://www.w3.org/XML/1998/namespace": "xml",
}


def readable_xml_name(name: str) -> str:
    if not name.startswith("{"):
        return name
    namespace, local = name[1:].split("}", 1)
    prefix = XML_NAMESPACES.get(namespace)
    return f"{prefix}:{local}" if prefix else f"{{{namespace}}}{local}"


def local_xml_name(name: str) -> str:
    return name.split("}", 1)[-1] if name.startswith("{") else name


def qname_attribute_value(element: etree._Element, name: str, value: str) -> str:
    if name != "{http://www.w3.org/2001/XMLSchema-instance}type" or ":" not in value:
        return value
    prefix, local = value.split(":", 1)
    namespace = element.nsmap.get(prefix)
    return f"{{{namespace}}}{local}" if namespace else value


def parse_xml(path: Path) -> etree._Element:
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=True, resolve_entities=False, no_network=True)
    return etree.parse(str(path), parser).getroot()


def xml_content(root: etree._Element) -> Counter[tuple[str, str, str]]:
    content: Counter[tuple[str, str, str]] = Counter()

    def visit(element: etree._Element, parent_path: str) -> None:
        current_path = f"{parent_path}/{readable_xml_name(str(element.tag))}"
        content[("element", current_path, "")] += 1
        for name, value in element.attrib.items():
            normalized_value = qname_attribute_value(element, name, value)
            attribute_path = f"{current_path}/@{readable_xml_name(name)}"
            content[("attribute", attribute_path, normalized_value)] += 1
        if element.text is not None and element.text.strip():
            content[("text", current_path, element.text)] += 1
        for child in element:
            if isinstance(child.tag, str):
                visit(child, current_path)
            if child.tail is not None and child.tail.strip():
                content[("tail", current_path, child.tail)] += 1

    visit(root, "")
    return content


def semantic_fingerprint(element: etree._Element) -> tuple[object, ...]:
    attributes = tuple(
        sorted(
            (name, qname_attribute_value(element, name, value))
            for name, value in element.attrib.items()
        )
    )
    children = sorted(
        (semantic_fingerprint(child) for child in element if isinstance(child.tag, str)),
        key=repr,
    )
    text = element.text if element.text is not None and element.text.strip() else ""
    return str(element.tag), attributes, text, tuple(children)


def short_value(value: str, limit: int = 140) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return repr(collapsed)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{collapsed[:limit - 3]!r}... [sha256:{digest}]"


def describe_xml_element(element: etree._Element) -> str:
    name = readable_xml_name(str(element.tag))
    children = [child for child in element if isinstance(child.tag, str)]
    if not children:
        attributes = " ".join(
            f"@{readable_xml_name(attr)}={short_value(value, 50)}"
            for attr, value in sorted(element.attrib.items())
        )
        value = short_value(element.text or "", 70)
        return " ".join(part for part in (name, attributes, f"= {value}") if part)

    identifiers: list[str] = []
    for descendant in element.iterdescendants():
        if not isinstance(descendant.tag, str):
            continue
        if local_xml_name(str(descendant.tag)) not in {"iri", "value", "title", "name", "label"}:
            continue
        if descendant.text and descendant.text.strip():
            item = f"{readable_xml_name(str(descendant.tag))}={short_value(descendant.text, 45)}"
            if item not in identifiers:
                identifiers.append(item)
    if len(identifiers) > 2:
        identifiers = [identifiers[0], identifiers[-1]]
    suffix = f" ({'; '.join(identifiers)})" if identifiers else ""
    return name + suffix


def xml_order_changes(before: etree._Element, after: etree._Element) -> list[tuple[str, list[str], list[str]]]:
    changes: list[tuple[str, list[str], list[str]]] = []

    def visit(left: etree._Element, right: etree._Element, path: str) -> None:
        left_groups: dict[str, list[etree._Element]] = {}
        right_groups: dict[str, list[etree._Element]] = {}
        for child in left:
            if isinstance(child.tag, str):
                left_groups.setdefault(str(child.tag), []).append(child)
        for child in right:
            if isinstance(child.tag, str):
                right_groups.setdefault(str(child.tag), []).append(child)

        for tag in sorted(left_groups.keys() & right_groups.keys()):
            left_children = left_groups[tag]
            right_children = right_groups[tag]
            left_fingerprints = [semantic_fingerprint(child) for child in left_children]
            right_fingerprints = [semantic_fingerprint(child) for child in right_children]
            if (
                len(left_children) > 1
                and Counter(left_fingerprints) == Counter(right_fingerprints)
                and left_fingerprints != right_fingerprints
            ):
                changes.append(
                    (
                        f"{path}/{readable_xml_name(tag)}",
                        [describe_xml_element(child) for child in left_children],
                        [describe_xml_element(child) for child in right_children],
                    )
                )

            unused = list(range(len(right_children)))
            pairs: list[tuple[etree._Element, etree._Element]] = []
            for left_child, fingerprint in zip(left_children, left_fingerprints):
                matching = next(
                    (index for index in unused if right_fingerprints[index] == fingerprint),
                    None,
                )
                if matching is None and unused:
                    matching = unused[0]
                if matching is not None:
                    unused.remove(matching)
                    pairs.append((left_child, right_children[matching]))
            for left_child, right_child in pairs:
                visit(left_child, right_child, f"{path}/{readable_xml_name(tag)}")

    root_path = f"/{readable_xml_name(str(before.tag))}"
    visit(before, after, root_path)
    return changes


def format_content_change(item: tuple[str, str, str], count: int) -> str:
    kind, path, value = item
    occurrence = f" ({count} occurrences)" if count > 1 else ""
    if kind == "element":
        return f"element {path}{occurrence}"
    return f"{kind} {path} = {short_value(value)}{occurrence}"


@timed
def compare_xml(original: Path, roundtrip: Path, report_path: Path) -> dict[str, object]:
    try:
        before_root = parse_xml(original)
        after_root = parse_xml(roundtrip)
        before = xml_content(before_root)
        after = xml_content(after_root)
        missing = before - after
        added = after - before
        order_changes = xml_order_changes(before_root, after_root)
        identical = not missing and not added and not order_changes
        lines = [
            f"Status: {'MATCH' if identical else 'DIFFERENT'}",
            "Comparison: elements, attributes, text values, and repeated-element order",
            "Ignored: XML declaration, comments, indentation, attribute order, namespace prefixes",
            f"Missing content entries: {sum(missing.values())}",
            f"Added content entries: {sum(added.values())}",
            f"Sibling-order changes: {len(order_changes)}",
        ]
        if missing:
            lines.extend(["", "Missing from round-trip XML:"])
            lines.extend(
                f"- {format_content_change(item, count)}" for item, count in sorted(missing.items())
            )
        if added:
            lines.extend(["", "Added in round-trip XML:"])
            lines.extend(
                f"- {format_content_change(item, count)}" for item, count in sorted(added.items())
            )
        if order_changes:
            lines.extend(["", "Repeated elements with changed order:"])
            for path, original_order, roundtrip_order in order_changes:
                lines.extend(
                    [
                        f"- {path}",
                        f"  original: {' | '.join(original_order)}",
                        f"  round-trip: {' | '.join(roundtrip_order)}",
                    ]
                )
        write_text(report_path, lines)
        return {"status": "MATCH" if identical else "DIFFERENT", "identical": identical}
    except Exception as error:
        write_text(report_path, ["Status: ERROR", "", "Fatal comparison error:", str(error)])
        return {"status": "ERROR", "identical": False, "failure": str(error)}


@timed
def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    input_xml = resolve(repo, args.input)
    schema_path = resolve(repo, args.schema)
    lifting = resolve(repo, args.lifting)
    lowering = resolve(repo, args.lowering)
    shapes = resolve(repo, args.shacl)
    output = resolve(repo, args.output)
    script_dir = Path(__file__).resolve().parent
    remove_stale_outputs(output)

    required = {
        "input": input_xml,
        "schema": schema_path,
        "lifting stylesheet": lifting,
        "lowering stylesheet": lowering,
        "SHACL shapes": shapes,
    }
    missing = [f"{label}: {path}" for label, path in required.items() if not path.is_file()]
    if missing:
        write_text(output / "00-summary.txt", ["Status: ERROR", "", "Missing inputs:", *missing])
        return 2

    stages: list[Stage] = []
    pipeline_failures = 0
    locations = parse_schema_locations(args.schema_locations, repo)
    schema, schema_errors, schema_warnings, schema_failure = build_schema(
        schema_path, locations, repo, output,
        resolve(repo, args.schema_cache) if args.schema_cache else None,
    )

    initial = validate_xml(
        input_xml,
        schema_path,
        schema,
        schema_errors,
        schema_warnings,
        schema_failure,
        output / "01-schema-validation.txt",
        repo,
        output,
    )
    stages.append(Stage("01 XSD validation", str(initial["status"]), f"{initial['instance_errors']} findings"))

    rdf_xml = output / "02-rdf.xml"
    ok, diagnostic = run_xslt(lifting, input_xml, rdf_xml, repo)
    if ok:
        stages.append(Stage("02 lifting XSLT", "OK"))
    else:
        pipeline_failures += 1
        write_text(output / "02-lifting-error.txt", ["Status: ERROR", diagnostic or "No output produced."])
        stages.append(Stage("02 lifting XSLT", "ERROR"))

    turtle = output / "03-rdf.ttl"
    nquads = output / "03-rdf.nq"
    if rdf_xml.is_file():
        with tempfile.TemporaryDirectory(prefix="roundtrip-") as temp_dir:
            raw_turtle = Path(temp_dir) / "raw.ttl"
            node_command = ["node", str(script_dir / "xml2ttl.mjs"), str(rdf_xml), args.base_iri]
            success, diagnostic = run_command(node_command, repo, raw_turtle, stdout_is_output=True)
            if success:
                try:
                    triple_count = canonicalize_rdf(raw_turtle, turtle, nquads)
                    stages.append(Stage("03 RDF conversion", "OK", f"{triple_count} triples"))
                except Exception as error:
                    success = False
                    diagnostic = str(error)
            if not success:
                pipeline_failures += 1
                write_text(
                    output / "03-rdf-conversion-error.txt",
                    ["Status: ERROR", diagnostic or "No Turtle output produced."],
                )
                stages.append(Stage("03 RDF conversion", "ERROR"))
    else:
        pipeline_failures += 1
        write_text(output / "03-rdf-conversion-error.txt", "Status: SKIPPED\nReason: 02-rdf.xml is missing.")
        stages.append(Stage("03 RDF conversion", "SKIPPED"))

    shacl = run_shacl(nquads, shapes, output / "04-shacl-validation.txt") if nquads.is_file() else {
        "status": "SKIPPED",
        "count": 0,
    }
    if not nquads.is_file():
        write_text(
            output / "04-shacl-validation.txt",
            "Status: SKIPPED\nReason: 03-rdf.nq is missing.",
        )
    if shacl["status"] == "ERROR":
        pipeline_failures += 1
    stages.append(Stage("04 SHACL validation", str(shacl["status"]), f"{shacl['count']} findings"))

    sparql_xml = output / "05-sparql-results.xml"
    if nquads.is_file():
        command = ["node", str(script_dir / "ttl2sparql-result.mjs"), str(nquads), args.base_iri]
        success, diagnostic = run_command(command, repo, sparql_xml, stdout_is_output=True)
        if success:
            stages.append(Stage("05 SPARQL results conversion", "OK"))
        else:
            pipeline_failures += 1
            write_text(output / "05-sparql-conversion-error.txt", ["Status: ERROR", diagnostic])
            stages.append(Stage("05 SPARQL results conversion", "ERROR"))
    else:
        pipeline_failures += 1
        write_text(
            output / "05-sparql-conversion-error.txt",
            "Status: SKIPPED\nReason: 03-rdf.nq is missing.",
        )
        stages.append(Stage("05 SPARQL results conversion", "SKIPPED"))

    roundtrip_xml = output / "06-roundtrip.xml"
    if sparql_xml.is_file():
        ok, diagnostic = run_xslt(lowering, sparql_xml, roundtrip_xml, repo)
        if ok:
            stages.append(Stage("06 lowering XSLT", "OK"))
        else:
            pipeline_failures += 1
            write_text(output / "06-lowering-error.txt", ["Status: ERROR", diagnostic])
            stages.append(Stage("06 lowering XSLT", "ERROR"))
    else:
        pipeline_failures += 1
        write_text(output / "06-lowering-error.txt", "Status: SKIPPED\nReason: 05-sparql-results.xml is missing.")
        stages.append(Stage("06 lowering XSLT", "SKIPPED"))

    if roundtrip_xml.is_file():
        comparison = compare_xml(input_xml, roundtrip_xml, output / "07-roundtrip-comparison.txt")
        final = validate_xml(
            roundtrip_xml,
            schema_path,
            schema,
            schema_errors,
            schema_warnings,
            schema_failure,
            output / "08-roundtrip-schema-validation.txt",
            repo,
            output,
        )
    else:
        comparison = {"status": "SKIPPED", "identical": False}
        final = {"status": "SKIPPED", "instance_errors": 0, "signatures": []}
        write_text(output / "07-roundtrip-comparison.txt", "Status: SKIPPED\nReason: 06-roundtrip.xml is missing.")
        write_text(
            output / "08-roundtrip-schema-validation.txt",
            "Status: SKIPPED\nReason: 06-roundtrip.xml is missing.",
        )
    stages.append(Stage("07 XML comparison", str(comparison["status"])))
    stages.append(Stage("08 round-trip XSD validation", str(final["status"]), f"{final['instance_errors']} findings"))

    fail_on = {item.strip().lower() for item in args.fail_on.split(",") if item.strip()}
    if "all" in fail_on:
        fail_on = {"pipeline", "xsd", "shacl", "diff"}
    if "none" in fail_on:
        fail_on = set()
    failed_reasons: list[str] = []
    if pipeline_failures and "pipeline" in fail_on:
        failed_reasons.append(f"{pipeline_failures} pipeline stage failure(s)")
    if "xsd" in fail_on and (initial["status"] != "VALID" or final["status"] != "VALID"):
        failed_reasons.append("XSD validation is not valid")
    if "shacl" in fail_on and shacl["status"] != "CONFORMS":
        failed_reasons.append("SHACL validation is not conformant")
    if "diff" in fail_on and not comparison["identical"]:
        failed_reasons.append("round-trip XML differs")

    summary_status = "FAILED" if failed_reasons else "COMPLETED"
    summary = [
        f"Status: {summary_status}",
        f"Input: {display_path(input_xml, repo)}",
        f"Output directory: {display_path(output, repo)}",
        f"Fail policy: {args.fail_on}",
        "",
        "Stages:",
    ]
    for stage in stages:
        suffix = f" ({stage.details})" if stage.details else ""
        summary.append(f"- {stage.name}: {stage.status}{suffix}")
    if failed_reasons:
        summary.extend(["", "Failure reasons:"])
        summary.extend(f"- {reason}" for reason in failed_reasons)
    write_text(output / "00-summary.txt", summary)
    return 1 if failed_reasons else 0


if __name__ == "__main__":
    sys.exit(main())
