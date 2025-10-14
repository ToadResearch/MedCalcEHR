#!/usr/bin/env python3
"""
transform_fhir.py

Reads a FHIR Bundle JSON (default: example_fhir.json) and rewrites it so that:
  1) Every entry.resource gets a brand-new UUIDv4 as its resource id.
  2) The same UUID is added as an identifier with system "urn:ietf:rfc:3986" and value "urn:uuid:<uuid>".
  3) Each entry.fullUrl becomes "urn:uuid:<uuid>".
  4) All intra-bundle references (e.g., "Patient/123" or absolute URLs like
     "https://example.org/fhir/Observation/abc") are converted to their corresponding
     "urn:uuid:<uuid>" values, preserving contained-resource references that start with '#'
     and non-reference URLs such as code systems (e.g., http://loinc.org) and other metadata.
  5) The Bundle itself also receives a new id and identifier (system urn:ietf:rfc:3986),
     but its type and other fields are preserved.

Usage:
  python transform_fhir.py -i example_fhir.json -o transformed.json

Notes:
- Only fields named "reference" and entry.fullUrl are rewritten. Coding.system, CodeableConcept URLs,
  meta.profile, etc., are left untouched.
- If a reference contains stray whitespace or minor typos like spaces in the id, a conservative
  sanitizer attempts to fix it (e.g., replacing whitespace with '-'). Unresolvable references are
  reported to stderr but left as-is.
"""

from __future__ import annotations
import argparse
import json
import sys
import uuid
import re
from typing import Any, Dict, List, Tuple, Set
from pathlib import Path

FHIR_ID_RE = re.compile(r"^[A-Za-z0-9\-\.]{1,64}$")
# Matches optional base (http[s]://.../fhir/), then ResourceType/id
REF_RE = re.compile(r"^(?:https?://[^/]+/[^/]+/)?([A-Za-z][A-Za-z0-9]+)/([A-Za-z0-9\-\.]{1,64})$")

URN_SYSTEM = "urn:ietf:rfc:3986"
URN_PREFIX = "urn:uuid:"

# Resource types that PROBABLY support identifier (R4 common set). If a resource isn't listed,
# we still add 'identifier' conservatively—most servers ignore unknown elements during non-strict
# processing. If you want to be strict, put the allowed types here and skip others.
LIKELY_SUPPORTS_IDENTIFIER: Set[str] = {
    "Account","ActivityDefinition","AdverseEvent","AllergyIntolerance","Appointment","AppointmentResponse",
    "AuditEvent","Basic","Binary","BiologicallyDerivedProduct","BodyStructure","CarePlan","CareTeam",
    "CatalogEntry","ChargeItem","Claim","ClaimResponse","ClinicalImpression","CodeSystem","Communication",
    "CommunicationRequest","CompartmentDefinition","Composition","ConceptMap","Condition","Consent",
    "Contract","Coverage","CoverageEligibilityRequest","CoverageEligibilityResponse","DetectedIssue","Device",
    "DeviceDefinition","DeviceMetric","DeviceRequest","DeviceUseStatement","DiagnosticReport","DocumentManifest",
    "DocumentReference","Encounter","Endpoint","EnrollmentRequest","EnrollmentResponse","EpisodeOfCare",
    "EventDefinition","Evidence","EvidenceReport","EvidenceVariable","ExampleScenario","ExplanationOfBenefit",
    "FamilyMemberHistory","Flag","Goal","GraphDefinition","Group","GuidanceResponse","HealthcareService",
    "ImagingStudy","Immunization","ImmunizationEvaluation","ImmunizationRecommendation","ImplementationGuide",
    "InsurancePlan","Invoice","Library","Linkage","List","Location","Measure","MeasureReport","Media",
    "Medication","MedicationAdministration","MedicationDispense","MedicationRequest","MedicationStatement",
    "MedicinalProductDefinition","MessageDefinition","MessageHeader","MolecularSequence","NamingSystem",
    "NutritionOrder","Observation","Organization","Patient","PaymentNotice","PaymentReconciliation",
    "Person","PlanDefinition","Practitioner","PractitionerRole","Procedure","Provenance","Questionnaire",
    "QuestionnaireResponse","RelatedPerson","ResearchDefinition","ResearchElementDefinition","ResearchStudy",
    "ResearchSubject","RiskAssessment","Schedule","ServiceRequest","Slot","Specimen","StructureDefinition",
    "Subscription","Substance","SupplyDelivery","SupplyRequest","Task","TerminologyCapabilities","TestReport",
    "TestScript","ValueSet","VisionPrescription"
}


def gen_uuid() -> str:
    return str(uuid.uuid4())


def to_urn(u: str) -> str:
    return f"{URN_PREFIX}{u}"


def add_identifier(resource: Dict[str, Any], urn_value: str) -> None:
    """Append an identifier with system urn:ietf:rfc:3986 and value urn:uuid:<uuid>.
    Adds even if 'identifier' key does not previously exist."""
    ident = {"system": URN_SYSTEM, "value": urn_value}
    if "identifier" in resource:
        # Ensure it's a list
        if isinstance(resource["identifier"], list):
            # Avoid duplicating exactly the same identifier
            if not any(
                isinstance(x, dict) and x.get("system") == URN_SYSTEM and x.get("value") == urn_value
                for x in resource["identifier"]
            ):
                resource["identifier"].append(ident)
        elif isinstance(resource["identifier"], dict):
            # Convert to list preserving existing single object
            resource["identifier"] = [resource["identifier"], ident]
        else:
            # Unknown type: replace conservatively
            resource["identifier"] = [ident]
    else:
        resource["identifier"] = [ident]


def collect_uuid_map(bundle: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[Tuple[str, str], str], Dict[str, str]]:
    """
    First pass: assign a new UUID per entry and collect maps for lookups.

    Returns:
        by_fullurl: maps original entry.fullUrl (if present) -> urn:uuid:...
        by_type_id: maps (resourceType, old_id) -> urn:uuid:...
        by_typeid_str: maps 'ResourceType/old_id' -> urn:uuid:...
    """
    by_fullurl: Dict[str, str] = {}
    by_type_id: Dict[Tuple[str, str], str] = {}
    by_typeid_str: Dict[str, str] = {}

    entries = bundle.get("entry", [])
    for e in entries:
        res = e.get("resource", {})
        rtype = res.get("resourceType")
        old_id = res.get("id")
        new_uuid = gen_uuid()
        urn = to_urn(new_uuid)

        # Record lookup keys for later reference rewriting
        if isinstance(e.get("fullUrl"), str):
            by_fullurl[e["fullUrl"].strip()] = urn
        if rtype and isinstance(old_id, str):
            by_type_id[(rtype, old_id)] = urn
            by_typeid_str[f"{rtype}/{old_id}"] = urn

        # Stash the generated UUID directly on the entry for pass #2
        e.setdefault("_generated_uuid", new_uuid)

    return by_fullurl, by_type_id, by_typeid_str


def sanitize_ref_string(s: str) -> str:
    """Try small, safe normalizations to help match bad references.
    - Trim whitespace
    - Collapse internal whitespace to '-'
    - Remove any surrounding quotes
    """
    s2 = s.strip().strip('"\'')
    if s2.startswith(URN_PREFIX) or s2.startswith('#'):
        return s2
    # Replace runs of whitespace with a single '-'
    s2 = re.sub(r"\s+", "-", s2)
    return s2


def map_reference(ref: str, by_fullurl: Dict[str, str], by_typeid_str: Dict[str, str]) -> str | None:
    """Return the urn:uuid mapping for the given reference string, or None if unknown.
    We accept:
      - urn:uuid:* (returned as-is by caller)
      - '#local' contained refs (ignored by caller)
      - relative 'ResourceType/id'
      - absolute 'https://host/base/ResourceType/id'
    """
    candidate = sanitize_ref_string(ref)

    # Already an urn or local contained ref
    if candidate.startswith(URN_PREFIX) or candidate.startswith('#'):
        return candidate

    # Direct fullUrl match
    if candidate in by_fullurl:
        return by_fullurl[candidate]

    m = REF_RE.match(candidate)
    if m:
        key = f"{m.group(1)}/{m.group(2)}"
        if key in by_typeid_str:
            return by_typeid_str[key]

    # Not resolvable
    return None


def rewrite_references(obj: Any, by_fullurl: Dict[str, str], by_typeid_str: Dict[str, str], unknown: Set[str]) -> Any:
    """Recursively traverse the object and rewrite any 'reference' values we can map.
    Returns the modified object (in-place for dicts/lists)."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "reference" and isinstance(v, str):
                mapped = map_reference(v, by_fullurl, by_typeid_str)
                if mapped is not None:
                    obj[k] = mapped
                else:
                    # Leave as-is but track
                    if not v.startswith(URN_PREFIX) and not v.startswith('#'):
                        unknown.add(v)
            else:
                rewrite_references(v, by_fullurl, by_typeid_str, unknown)
    elif isinstance(obj, list):
        for i in range(len(obj)):
            rewrite_references(obj[i], by_fullurl, by_typeid_str, unknown)
    return obj


def transform_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    # 0) Assign new id/identifier to the bundle itself
    bundle_uuid = gen_uuid()
    bundle["id"] = bundle_uuid
    # Add/augment Bundle.identifier
    bund_ident = {"system": URN_SYSTEM, "value": to_urn(bundle_uuid)}
    if "identifier" in bundle:
        existing = bundle["identifier"]
        if isinstance(existing, dict):
            bundle["identifier"] = [existing, bund_ident]
        elif isinstance(existing, list):
            bundle["identifier"].append(bund_ident)
        else:
            bundle["identifier"] = [bund_ident]
    else:
        bundle["identifier"] = bund_ident  # Bundle.identifier is 0..1 (object) in R4, keep as object

    # 1) First pass: assign UUIDs and build lookups
    by_fullurl, by_type_id, by_typeid_str = collect_uuid_map(bundle)

    # 2) Rewrite each entry: set fullUrl, id, identifier; collect unknown refs while rewriting
    unknown_refs: Set[str] = set()
    for e in bundle.get("entry", []):
        res = e.get("resource", {})
        rtype = res.get("resourceType")
        new_uuid = e.get("_generated_uuid") or gen_uuid()
        urn = to_urn(new_uuid)

        # fullUrl -> urn:uuid
        e["fullUrl"] = urn

        # resource.id -> uuid
        res["id"] = new_uuid

        # resource.identifier -> include urn identifier
        add_identifier(res, urn)

        # Optional: if you want to ensure identifier only for resources likely supporting it,
        # uncomment the following two lines:
        # if rtype not in LIKELY_SUPPORTS_IDENTIFIER:
        #     res.pop("identifier", None)

        # Recurse through the resource to rewrite references
        rewrite_references(res, by_fullurl, by_typeid_str, unknown_refs)

        # Clean helper
        if "_generated_uuid" in e:
            del e["_generated_uuid"]

    # 3) Rewrite any lingering references at the Bundle level (e.g., Composition.section.entry list lives in resources,
    #     but we call again on the Bundle just in case there are other stray 'reference' fields outside entries)
    rewrite_references(bundle, by_fullurl, by_typeid_str, unknown_refs)

    # Warn about unresolved references
    if unknown_refs:
        print(
            "[WARN] The following references could not be resolved to entries in the bundle and were left as-is:\n  - "
            + "\n  - ".join(sorted(unknown_refs)),
            file=sys.stderr,
        )

    return bundle


def main():
    parser = argparse.ArgumentParser(description="Rewrite a FHIR Bundle to use urn:uuid fullUrls and references, adding UUID ids/identifiers.")
    parser.add_argument("-i", "--input", default="example_fhir.json", help="Path to input FHIR Bundle JSON (default: example_fhir.json)")
    project_root = Path(__file__).resolve().parent.parent
    default_output = str(project_root / "data" / "example_fhir_uuid.json")
    parser.add_argument("-o", "--output", default=default_output, help="Path to write transformed JSON (default: data/example_fhir.uuid.json)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            bundle = json.load(f)
    except Exception as e:
        print(f"Failed to read input JSON '{args.input}': {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        print("Input must be a FHIR Bundle JSON object.", file=sys.stderr)
        sys.exit(2)

    transformed = transform_bundle(bundle)

    try:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            if args.pretty:
                json.dump(transformed, f, indent=2, ensure_ascii=False)
            else:
                json.dump(transformed, f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"Failed to write output JSON '{args.output}': {e}", file=sys.stderr)
        sys.exit(3)

    print(f"Wrote transformed bundle to {out_path}")


if __name__ == "__main__":
    main()
