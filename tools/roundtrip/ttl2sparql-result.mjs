#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { Parser } from "n3";

const inputFile = process.argv[2];
const baseIri = process.argv[3];

if (!inputFile || !baseIri) {
  console.error("Usage: node ttl2sparql-result.mjs <turtle-or-nquads-file> <base-iri>");
  process.exit(2);
}

const escapeText = (value) =>
  String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

const escapeAttribute = (value) =>
  escapeText(value).replaceAll('"', "&quot;").replaceAll("'", "&apos;");

const termKey = (term) => {
  if (term.termType === "Literal") {
    return `L\u0000${term.value}\u0000${term.language}\u0000${term.datatype?.value || ""}`;
  }
  return `${term.termType}\u0000${term.value}`;
};

const termToXml = (term) => {
  if (term.termType === "Literal") {
    if (term.language) {
      return `<literal xml:lang="${escapeAttribute(term.language)}">${escapeText(term.value)}</literal>`;
    }
    const datatype = term.datatype?.value;
    const datatypeAttribute = datatype ? ` datatype="${escapeAttribute(datatype)}"` : "";
    return `<literal${datatypeAttribute}>${escapeText(term.value)}</literal>`;
  }
  if (term.termType === "BlankNode") {
    return `<bnode>${escapeText(term.value)}</bnode>`;
  }
  if (term.termType === "NamedNode") {
    return `<uri>${escapeText(term.value)}</uri>`;
  }
  throw new Error(`Unsupported RDF term type: ${term.termType}`);
};

try {
  const source = readFileSync(inputFile, "utf8");
  const format = inputFile.endsWith(".nq") ? "N-Quads" : "text/turtle";
  const quads = new Parser({ baseIRI: baseIri, format }).parse(source);
  quads.sort((left, right) => {
    const leftKey = [termKey(left.subject), termKey(left.predicate), termKey(left.object)].join("\u0001");
    const rightKey = [termKey(right.subject), termKey(right.predicate), termKey(right.object)].join("\u0001");
    return leftKey.localeCompare(rightKey, "en");
  });

  const results = quads
    .map(
      ({ subject, predicate, object }) => `    <result>
      <binding name="s">${termToXml(subject)}</binding>
      <binding name="p">${termToXml(predicate)}</binding>
      <binding name="o">${termToXml(object)}</binding>
    </result>`,
    )
    .join("\n");

  process.stdout.write(`<?xml version="1.0" encoding="UTF-8"?>
<sparql xmlns="http://www.w3.org/2005/sparql-results#">
  <head>
    <variable name="s"/>
    <variable name="p"/>
    <variable name="o"/>
  </head>
  <results>
${results}
  </results>
</sparql>
`);
} catch (error) {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exit(1);
}
