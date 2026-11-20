# Schemas

`tei_all.rng` — TEI P5 version 4.12.0 (28 July 2026), RELAX NG, unchanged copy of
<https://www.tei-c.org/Vault/P5/4.12.0/xml/tei/custom/schema/relaxng/tei_all.rng>
(downloaded 2026-11-20 from the `release/` link, sha256 `b0f11509...7e48`).
Licence: CC BY 3.0 / BSD-2 (TEI Consortium).

Used by `tei_translate.pipeline.validate` (check "TEI schema (tei_all)") through
lxml/libxml2, so no Java is needed. Pinned on purpose: `release/` moves with every
TEI version. To upgrade, replace the file, update this note and rerun
`scripts/check_schema_corpus.py`.

Not covered: the Schematron rules embedded in the schema (`sch:` elements); lxml's
RELAX NG validation ignores them.

The Perseus files declare the stricter EpiDoc schema (`tei-epidoc.rng`); the team
chose `tei_all` (2026-11-20).
