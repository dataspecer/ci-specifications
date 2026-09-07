#!/usr/bin/env node

import { readFileSync } from "node:fs";
import rdflib from "rdflib";

const inputFile = process.argv[2];
const baseIri = process.argv[3];

if (!inputFile || !baseIri) {
  console.error("Usage: node xml2ttl.mjs <rdf-xml-file> <base-iri>");
  process.exit(2);
}

try {
  const source = readFileSync(inputFile, "utf8");
  const store = rdflib.graph();
  rdflib.parse(source, store, baseIri, "application/rdf+xml");
  process.stdout.write(rdflib.serialize(null, store, baseIri, "text/turtle"));
} catch (error) {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exit(1);
}
