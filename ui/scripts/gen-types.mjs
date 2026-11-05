// Erzeugt src/api/types.ts aus dem JSON-Schema von `visualcut schema`.
// Läuft aus ui/: `npm run types`. Braucht uv und das Python-Projekt eine Ebene höher.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..", "..");
const out = resolve(here, "..", "src", "api");

const raw = execFileSync("uv", ["run", "--project", repo, "visualcut", "schema"], { cwd: repo, encoding: "utf8" });
const schema = JSON.parse(raw);
writeFileSync(resolve(out, "schema.json"), JSON.stringify(schema, null, 2) + "\n");

// Titel an Feldern würden eigene Alias-Typen (Start1, End2 …) erzeugen; nur die $defs behalten ihre Namen.
for (const def of Object.values(schema.$defs)) {
  for (const prop of Object.values(def.properties ?? {})) delete prop.title;
}

// Oberste Ebene ist ein anyOf; wir wollen jede Definition als benannten Typ.
const ts = await compile({ ...schema, title: "VisualCutSchema" }, "VisualCutSchema", {
  bannerComment: "/* Generiert aus `visualcut schema` (npm run types). Nicht von Hand ändern. */",
  additionalProperties: false,
  style: { singleQuote: false, semi: true, printWidth: 110 },
});
writeFileSync(resolve(out, "types.ts"), ts);
console.log("types.ts geschrieben:", Object.keys(schema.$defs).join(", "));
