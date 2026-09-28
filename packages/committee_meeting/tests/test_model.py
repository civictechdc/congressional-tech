"""Design acceptance cases, including failures that would mislead explorer users."""
import json
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

from pydantic import ValidationError

from committee_meeting import Catalog, CoverageMetric, PublicationManifest
from committee_meeting.common import ReportedTime
from committee_meeting.provenance import SourceRecord

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from worked_catalog import worked_catalog, reference


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.data = worked_catalog().model_dump(mode="json")

    def row(self, id):
        return next(row for row in self.data["records"] if row["id"] == id)

    def invalid(self, pattern):
        with self.assertRaisesRegex(ValidationError, pattern):
            Catalog.model_validate(self.data)

    def test_roundtrip_preserves_joint_hearing_and_distinct_same_name_appearances(self):
        catalog = Catalog.model_validate_json(json.dumps(self.data))
        self.assertEqual(Catalog.model_validate_json(catalog.model_dump_json()), catalog)
        self.assertEqual(len(self.row("hearing")["committees"]), 2)
        self.assertEqual(self.row("witness-a")["name"], self.row("witness-b")["name"])
        self.assertIsNone(self.row("witness-a")["person"])
        self.assertNotEqual(self.row("witness-a")["affiliation"], self.row("witness-b")["affiliation"])

    def test_standalone_transcript_versions_formats_and_shared_links(self):
        self.assertEqual(self.row("print")["details"]["category"], "transcript")
        versions = [r for r in self.data["records"] if r["kind"] == "material_version" and r["material"]["id"] == "print"]
        files = [r for r in self.data["records"] if r["kind"] == "representation" and r["version"]["id"] == "print-v2"]
        links = [r for r in self.data["records"] if r["kind"] == "material_link" and r["material"]["id"] == "print"]
        self.assertEqual((len(versions), len(files), len(links)), (2, 3, 2))
        self.assertFalse(any(r["kind"] == "material_relation" for r in self.data["records"]))

    def test_unlinked_recording_and_inferred_captions_do_not_invent_a_track(self):
        self.assertFalse(any(r["kind"] == "material_link" and r["material"]["id"] == "archive-video" for r in self.data["records"]))
        self.assertEqual(self.row("caption-estimate")["provenance"]["basis"], "inferred")
        self.assertEqual(self.row("caption-estimate")["results"], [])
        self.row("caption-estimate")["provenance"]["method"] = None
        self.invalid("named, versioned method")

    def test_not_found_requires_a_real_dated_scoped_observation(self):
        assessment = self.row("caption-estimate")
        assessment["status"] = "not_found"
        self.invalid("dated check")
        assessment.update(observed_at="2026-09-26T12:00:00Z", scope="Automatic and manual tracks on example player")
        Catalog.model_validate(self.data)
        assessment["observed_at"] = "2026-09-28T12:00:00Z"
        self.invalid("observation cannot follow")

    def test_date_only_is_not_midnight_and_naive_fetch_time_is_rejected(self):
        stamp = ReportedTime(date="2026-09-01")
        self.assertIsNone(stamp.time)
        self.assertIsNone(stamp.timezone)
        with self.assertRaises(ValidationError):
            ReportedTime(date="2026-09-01", precision="minute")
        self.data["sources"][0]["retrieved_at"] = "2026-09-27T12:00:00"
        self.invalid("timezone")

    def test_exact_urls_and_unmapped_source_fields_survive(self):
        url = "http://docs.house.gov/billsthisweek/20170710/BILLS%20-115HR2810-RCP115-23.xml"
        self.row("print-xml")["locations"][0]["url"] = url
        self.data["sources"][0]["payload"]["unmodeled"] = {"raw-code": "NA", "future": [1, None]}
        catalog = Catalog.model_validate(self.data)
        output = json.loads(catalog.model_dump_json())
        self.assertEqual(output["sources"][0]["payload"]["unmodeled"], self.data["sources"][0]["payload"]["unmodeled"])
        self.assertIn(url, catalog.model_dump_json())
        self.row("print-xml")["locations"][0]["url"] = "../invented.xml"
        self.invalid("absolute HTTP")

    def test_unknown_domain_fields_are_rejected(self):
        self.row("hearing")["committee_id"] = "legacy-single-committee"
        self.invalid("Extra inputs")

    def test_duplicate_identity_and_missing_evidence_are_rejected(self):
        self.data["records"].append(dict(self.row("hearing")))
        self.invalid("duplicate record identity")
        self.data["records"].pop()
        self.data["sources"] = []
        self.invalid("missing source_record")

    def test_wrong_ref_type_and_dangling_links_are_rejected(self):
        link = self.row("print-hearing")
        link["subject"] = reference("person", "nobody")
        self.invalid("Input should be")
        link["subject"] = reference("meeting", "nobody")
        self.invalid("missing meeting/nobody")

    def test_appearance_cannot_borrow_another_meetings_panel_or_occurrence(self):
        self.row("witness-a")["meeting"] = reference("meeting", "markup")
        self.invalid("panel belongs to another meeting")
        self.row("witness-a")["panel"] = None
        self.row("witness-a")["occurrence"] = reference("occurrence", "day-1")
        self.invalid("occurrence belongs to another meeting")

    def test_cross_congress_committee_is_rejected(self):
        self.row("term-b")["congress"] = 118
        self.invalid("committee Congress differs")

    def test_version_and_exact_file_must_belong_to_linked_material(self):
        self.row("print-hearing")["version"] = reference("material_version", "archive-v1")
        self.invalid("linked version belongs to another material")
        self.row("print-hearing")["version"] = reference("material_version", "print-v2")
        self.row("print-hearing")["extent"]["representation"] = reference("representation", "archive-player")
        self.invalid("extent file belongs to another version")

    def test_cycles_in_revision_hierarchy_and_amendments_are_rejected(self):
        for id, key, value in (
            ("print-v1", "supersedes", reference("material_version", "print-v2")),
            ("term-a", "parent", reference("committee_term", "term-a")),
            ("amendment-1", "target", reference("amendment", "amendment-2")),
        ):
            with self.subTest(id=id):
                original = self.row(id).get(key)
                self.row(id)[key] = value
                self.invalid("cycle")
                self.row(id)[key] = original

    def test_amendment_group_and_vote_do_not_cross_meetings(self):
        self.row("enbloc")["meeting"] = reference("meeting", "hearing")
        self.invalid("group member belongs to another meeting")
        self.row("enbloc")["meeting"] = reference("meeting", "markup")
        self.row("vote-1")["meeting"] = reference("meeting", "hearing")
        self.invalid("vote subject belongs to another meeting")

    def test_vote_and_amendment_need_no_file_or_invented_tally(self):
        catalog = Catalog.model_validate(self.data)
        vote = next(r for r in catalog.records if r.id == "vote-1")
        self.assertIsNone(vote.tally)
        self.assertEqual(vote.ballots, ())
        self.assertEqual(vote.outcome, "unknown")

    def test_field_disagreement_preserved_and_selected_path_checked(self):
        hearing = self.row("hearing")
        hearing["field_evidence"] = [{"path": "/title", "selected": hearing["provenance"],
            "alternatives": [{"value": "Earlier title", "provenance": hearing["provenance"]}],
            "selection_reason": "Example publisher correction"}]
        Catalog.model_validate(self.data)
        hearing["field_evidence"][0]["path"] = "/not_a_field"
        self.invalid("field evidence path does not exist")

    def test_retained_bytes_and_stated_digest_cannot_disagree(self):
        self.row("print-pdf").update(sha256="a" * 64, retained={"uri": "artifact:example.pdf", "sha256": "b" * 64})
        self.invalid("same digest")

    def test_source_evidence_requires_payload_or_pinned_content(self):
        source = self.data["sources"][0]
        source["payload"] = None
        with self.assertRaisesRegex(ValidationError, "retain the source"):
            SourceRecord.model_validate(source)
        source["retained"] = {"uri": "artifact:source.xml", "sha256": "a" * 64}
        Catalog.model_validate(self.data)

    def test_json_schema_has_discriminated_records_and_closed_domain_fields(self):
        schema = Catalog.model_json_schema()
        records = schema["properties"]["records"]["items"]
        self.assertEqual(records["discriminator"]["propertyName"], "kind")
        self.assertIn("material_link", records["discriminator"]["mapping"])
        self.assertFalse(schema["$defs"]["Meeting"]["additionalProperties"])

    def test_real_house_fixture_preserves_document_groups_and_all_format_urls(self):
        # Retained, trimmed source fixture from main 3108a6d; no network probe.
        xml = Path(__file__).with_name("house-formats.xml").read_text()
        root = ET.fromstring(xml)
        records, expected_urls = [], []
        for index, document in enumerate(root.findall("meeting-documents/meeting-document")):
            evidence = {"basis": "reported", "citations": [{"source": reference("source_record", "house"),
                "selector_type": "xpath", "selector": f"./meeting-documents/meeting-document[{index + 1}]"}]}
            id = f"document-{index}"
            records += [
                {"kind": "material", "id": id, "provenance": evidence, "title": document.findtext("description"),
                 "congress": int(root.attrib["congress-num"]), "chamber": "house", "details": {"type": "document"}},
                {"kind": "material_version", "id": id, "provenance": evidence, "material": reference("material", id)},
            ]
            for file_index, file in enumerate(document.findall("files/file")):
                url = file.attrib["doc-url"]
                expected_urls.append(url)
                records.append({"kind": "representation", "id": f"{id}-{file_index}", "provenance": evidence,
                    "version": reference("material_version", id), "format_label": file.attrib["doc-type"],
                    "locations": [{"url": url, "role": "download"}]})
        catalog = Catalog.model_validate({"sources": [{"id": "house", "provider": "docs.house.gov",
            "identifier": {"scheme": "house-meeting", "value": root.attrib["meeting-id"]}, "payload": xml}], "records": records})
        materials = [r for r in catalog.records if r.kind == "material"]
        files = [r for r in catalog.records if r.kind == "representation"]
        self.assertEqual((len(materials), len(files)), (3, 6))
        self.assertEqual([r.locations[0].url for r in files], expected_urls)
        self.assertTrue(all(r.xml_root is None and r.retained is None for r in files))
        self.assertIsNone(catalog.sources[0].retrieved_at)

    def test_manifest_and_coverage_state_the_population_and_input_identity(self):
        manifest = {"publication_id": "example", "generated_at": "2026-09-27T12:00:00Z",
            "producer": {"name": "example-export", "version": "1"},
            "inputs": [{"id": "snapshot", "provider": "example", "artifact": {"uri": "artifact:input", "sha256": "a" * 64},
                        "last_attempt_status": "failed", "limitations": ["Retained last successful input."]}]}
        parsed = PublicationManifest.model_validate(manifest)
        self.assertIsNone(parsed.inputs[0].last_observed_at)
        manifest["source_scopes"] = [{"provider": "example", "scope": "Older transcript editions",
            "status": "not_collected", "explanation": "Historical editions have not been collected."}]
        self.assertEqual(PublicationManifest.model_validate(manifest).source_scopes[0].input_snapshot_ids, ())
        manifest["source_scopes"][0].update(status="included", input_snapshot_ids=["missing-input"])
        with self.assertRaisesRegex(ValidationError, "unknown input snapshot"):
            PublicationManifest.model_validate(manifest)
        manifest["source_scopes"][0]["input_snapshot_ids"] = ["snapshot"]
        PublicationManifest.model_validate(manifest)
        manifest["inputs"].append(manifest["inputs"][0])
        with self.assertRaisesRegex(ValidationError, "IDs must be unique"):
            PublicationManifest.model_validate(manifest)
        metric = {"id": "text", "label": "Confirmed transcript coverage", "unit": "meeting",
            "population": "Held, open meetings in Congress 119", "method": {"name": "example-count", "version": "1"},
            "input_snapshot_ids": ["snapshot"], "numerator": 1, "denominator": 3, "unknown": 2, "evidence_basis": "confirmed"}
        CoverageMetric.model_validate(metric)
        metric["unknown"] = 3
        with self.assertRaisesRegex(ValidationError, "exceed denominator"):
            CoverageMetric.model_validate(metric)

    def test_day_only_successful_check_keeps_its_precision(self):
        check = self.row("caption-estimate")
        check.update(status="not_found", observed_at={"date": "2026-09-26"}, scope="Publisher caption track list")
        parsed = Catalog.model_validate(self.data)
        observation = next(r for r in parsed.records if r.id == check["id"]).observed_at
        self.assertIsNone(observation.time)
        self.assertIsNone(observation.timezone)

    def test_missing_issue_requires_expectation_and_correction_requires_evidence(self):
        issue = {"kind": "data_issue", "id": "gap", "subject": reference("meeting", "hearing"),
            "category": "missing", "summary": "Expected attachment is unavailable", "detected_at": "2026-09-25T12:00:00Z",
            "provenance": self.row("hearing")["provenance"]}
        self.data["records"].append(issue)
        self.invalid("supported expectation")
        issue["expected"] = "The retained publisher notice lists this attachment."
        Catalog.model_validate(self.data)
        issue["status"] = "resolved"
        self.invalid("closed issues require a resolution")
        issue["resolution"] = {"decided_at": "2026-09-26T12:00:00Z", "explanation": "Publisher added the attachment.",
                               "provenance": self.row("hearing")["provenance"]}
        Catalog.model_validate(self.data)
        self.assertEqual(issue["summary"], "Expected attachment is unavailable")

    def test_issue_field_must_exist_and_inference_cannot_establish_error(self):
        issue = {"kind": "data_issue", "id": "error", "subject": reference("meeting", "hearing"),
            "category": "incorrect", "summary": "Incorrect time", "detected_at": "2026-09-25T12:00:00Z",
            "provenance": self.row("caption-estimate")["provenance"]}
        self.data["records"].append(issue)
        self.invalid("inference alone")
        issue["provenance"] = self.row("hearing")["provenance"]
        issue["field_path"] = "/time_that_does_not_exist"
        self.invalid("issue field path does not exist")
        issue["field_path"] = "/title"
        Catalog.model_validate(self.data)


if __name__ == "__main__":
    unittest.main()
