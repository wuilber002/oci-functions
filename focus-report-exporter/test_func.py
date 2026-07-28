import importlib
import json
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


# The local development environment may not have the Functions Development Kit.
# The helpers under test do not depend on it, so provide the small interface that
# func.py imports before loading the module.
if "fdk" not in sys.modules:
    sys.modules["fdk"] = types.ModuleType("fdk")
    sys.modules["fdk"].response = SimpleNamespace(Response=lambda *args, **kwargs: None)

func = importlib.import_module("func")


class PrefixTests(unittest.TestCase):
    def test_normalize_prefix_adds_one_separator(self):
        self.assertEqual(func.normalize_prefix("FOCUS-Reports"), "FOCUS-Reports/")
        self.assertEqual(func.normalize_prefix("/FOCUS-Reports//"), "FOCUS-Reports/")

    def test_lock_is_created_inside_the_destination_prefix(self):
        self.assertEqual(
            func.get_lock_object_name("FOCUS-Reports/"),
            "FOCUS-Reports/.focus-report-exporter.lock",
        )

    def test_relative_iterator_advances_across_unaligned_pages(self):
        responses = [
            SimpleNamespace(
                data=SimpleNamespace(objects=[
                    SimpleNamespace(name="FOCUS-Reports/2024/01/01/old.csv.gz"),
                    SimpleNamespace(name="FOCUS-Reports/2026/07/26/source.csv.gz"),
                ], next_start_with="FOCUS-Reports/2026/07/26/source.csv.gz"),
                headers={},
            ),
            SimpleNamespace(
                data=SimpleNamespace(objects=[
                    SimpleNamespace(name="FOCUS-Reports/2026/07/26/another.csv.gz"),
                ], next_start_with=None),
                headers={},
            ),
        ]
        received_kwargs = []

        def list_objects(**kwargs):
            received_kwargs.append(kwargs)
            return responses.pop(0)

        stats = {"destination_pages": 0, "dest": 0}
        objects = list(func.iter_relative_summaries(
            list_objects,
            "FOCUS-Reports/",
            stats,
            "destination_pages",
            "dest",
        ))

        self.assertEqual(stats, {"destination_pages": 2, "dest": 3})
        self.assertNotIn("start", received_kwargs[0])
        self.assertEqual(
            received_kwargs[1]["start"],
            "FOCUS-Reports/2026/07/26/source.csv.gz",
        )
        self.assertEqual([name for name, _ in objects], [
            "2024/01/01/old.csv.gz", "2026/07/26/source.csv.gz",
            "2026/07/26/another.csv.gz",
        ])

    def test_failed_listing_is_not_treated_as_an_empty_bucket(self):
        def list_objects(**kwargs):
            raise RuntimeError("falha simulada")

        with self.assertRaises(RuntimeError):
            list(func.iter_relative_summaries(
                list_objects,
                "FOCUS Reports/",
                {"source_pages": 0, "orig": 0},
                "source_pages",
                "orig",
            ))

    def test_object_match_requires_equal_md5_and_size(self):
        source = SimpleNamespace(size=10, md5="source", etag="source-etag")
        same = SimpleNamespace(size=10, md5="source", etag="destination-etag")
        different_size = SimpleNamespace(size=11, md5="source", etag="other-etag")
        different_md5 = SimpleNamespace(size=10, md5="other", etag="other-etag")

        self.assertTrue(func.objects_match(source, same))
        self.assertFalse(func.objects_match(source, different_size))
        self.assertFalse(func.objects_match(source, different_md5))

    def test_custom_destination_region_has_precedence(self):
        with patch.dict(
            func.os.environ,
            {"OCI_RESOURCE_PRINCIPAL_REGION": "sa-saopaulo-1"},
            clear=True,
        ):
            self.assertEqual(
                func.get_destination_region(
                    {"OCI_BUCKET_DESTINATION_REGION": "us-ashburn-1"}
                ),
                "us-ashburn-1",
            )

    def test_function_region_is_the_default_destination_region(self):
        with patch.dict(
            func.os.environ,
            {"OCI_RESOURCE_PRINCIPAL_REGION": "sa-saopaulo-1"},
            clear=True,
        ):
            self.assertEqual(
                func.get_destination_region({}),
                "sa-saopaulo-1",
            )


class CopyRequestTests(unittest.TestCase):
    @patch.object(func.time, "sleep")
    def test_only_completed_work_requests_are_counted_as_copied(self, sleep):
        client = SimpleNamespace(
            get_work_request=lambda work_request_id, **kwargs: SimpleNamespace(
                data=SimpleNamespace(status="COMPLETED")
            )
        )
        stats = {"copy": 0, "update": 0, "erro": 0, "pending": 0}

        func.wait_for_copy_requests(client, {"report.csv": ("request-id", False)}, stats)

        self.assertEqual(stats, {"copy": 1, "update": 0, "erro": 0, "pending": 0})

    def test_unavailable_work_request_is_reported_as_unknown(self):
        client = SimpleNamespace(
            get_work_request=lambda work_request_id, **kwargs: (_ for _ in ()).throw(
                RuntimeError("service unavailable")
            )
        )
        stats = {"copy": 0, "update": 0, "erro": 0, "pending": 0, "unknown": 0}

        with patch.object(func.time, "sleep"):
            func.wait_for_copy_requests(client, {"report.csv": ("request-id", False)}, stats)

        self.assertEqual(stats["unknown"], 1)

    @patch.object(func.time, "sleep")
    def test_failed_work_request_logs_oci_error_details(self, sleep):
        error = SimpleNamespace(to_dict=lambda: {"code": "403", "message": "Denied"})
        log_entry = SimpleNamespace(to_dict=lambda: {"message": "Copy failed"})
        client = SimpleNamespace(
            get_work_request=lambda work_request_id, **kwargs: SimpleNamespace(
                data=SimpleNamespace(status="FAILED")
            ),
            list_work_request_errors=lambda work_request_id, **kwargs: SimpleNamespace(
                data=[error]
            ),
            list_work_request_logs=lambda work_request_id, **kwargs: SimpleNamespace(
                data=[log_entry]
            ),
        )
        stats = {"copy": 0, "update": 0, "erro": 0, "pending": 0}

        with patch.object(func, "log_event") as log_event:
            func.wait_for_copy_requests(
                client, {"report.csv": ("request-id", False)}, stats
            )

        self.assertEqual(stats["erro"], 1)
        log_event.assert_called_once_with(
            func.logging.ERROR,
            "copy_failed",
            object_name="report.csv",
            work_request_id="request-id",
            status="FAILED",
            errors=[{"code": "403", "message": "Denied"}],
            logs=[{"message": "Copy failed"}],
        )


class HandlerFlowTests(unittest.TestCase):
    class Context:
        def Config(self):
            return {
                "OCI_TENANCY_OCID": "tenancy-id",
                "OCI_BUCKET_DESTINATION": "destination-bucket",
                "OCI_BUCKET_ROOT_PATH": "FOCUS-Reports",
            }

    class Client:
        def __init__(self, destination_objects, source_objects=None):
            self.destination_objects = destination_objects
            self.source_objects = source_objects or []
            self.list_calls = []
            self.copy_calls = []
            self.deleted_locks = []

        def get_namespace(self):
            return SimpleNamespace(data="destination-namespace")

        def put_object(self, **kwargs):
            return SimpleNamespace(headers={"etag": "lock-etag"})

        def delete_object(self, **kwargs):
            self.deleted_locks.append(kwargs)

        def list_objects(self, **kwargs):
            self.list_calls.append(kwargs)
            return SimpleNamespace(
                data=SimpleNamespace(objects=(
                    self.source_objects if kwargs["namespace_name"] == "bling"
                    else self.destination_objects
                )), headers={}
            )

        def copy_object(self, **kwargs):
            self.copy_calls.append(kwargs)
            return SimpleNamespace(
                status=202, headers={"opc-work-request-id": "copy-request"}
            )

    def setUp(self):
        self.response_patch = patch.object(
            func.response,
            "Response",
            side_effect=lambda ctx, response_data, status_code, headers: SimpleNamespace(
                body=response_data, status_code=status_code, headers=headers
            ),
        )
        self.response_patch.start()
        self.addCleanup(self.response_patch.stop)
        self.env_patch = patch.dict(
            func.os.environ,
            {"OCI_RESOURCE_PRINCIPAL_REGION": "sa-saopaulo-1"},
            clear=True,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    @staticmethod
    def object_summary(name, md5="md5", size=10, etag="etag"):
        return SimpleNamespace(name=name, md5=md5, size=size, etag=etag)

    def run_handler(self, source_objects, destination_objects, wait_side_effect=None):
        client = self.Client(destination_objects, source_objects)
        with patch.object(func, "get_oci_client", return_value=client), patch.object(
            func, "wait_for_copy_requests", side_effect=wait_side_effect
        ) as wait_for_copies:
            result = func.handler(self.Context())
        return result, client, wait_for_copies

    def test_equal_object_is_not_copied_and_lists_required_fields(self):
        source = self.object_summary("FOCUS Reports/2026/07/26/report.csv.gz")
        destination = self.object_summary("FOCUS-Reports/2026/07/26/report.csv.gz")

        result, client, wait_for_copies = self.run_handler([source], [destination])

        stats = json.loads(result.body)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(stats["same"], 1)
        self.assertFalse(client.copy_calls)
        self.assertFalse(wait_for_copies.call_args.args[1])
        self.assertEqual(client.list_calls[0]["fields"], func.OBJECT_SUMMARY_FIELDS)
        self.assertEqual(
            client.list_calls[1]["start"],
            "FOCUS-Reports/2026/07/26/report.csv.gz",
        )
        self.assertTrue(client.deleted_locks)

    def test_new_object_uses_create_only_precondition(self):
        source = self.object_summary("FOCUS Reports/2026/07/26/report.csv.gz")

        result, client, _ = self.run_handler([source], [])

        self.assertEqual(result.status_code, 200)
        details = client.copy_calls[0]["copy_object_details"]
        self.assertEqual(details.destination_object_if_none_match_e_tag, "*")
        self.assertIsNone(details.destination_object_if_match_e_tag)
        self.assertEqual(details.source_object_if_match_e_tag, "etag")

    def test_divergent_object_uses_destination_etag_precondition(self):
        source = self.object_summary("FOCUS Reports/2026/07/26/report.csv.gz", md5="new")
        destination = self.object_summary(
            "FOCUS-Reports/2026/07/26/report.csv.gz", md5="old", etag="old-etag"
        )

        result, client, _ = self.run_handler([source], [destination])

        self.assertEqual(result.status_code, 200)
        details = client.copy_calls[0]["copy_object_details"]
        self.assertEqual(details.destination_object_if_match_e_tag, "old-etag")
        self.assertIsNone(details.destination_object_if_none_match_e_tag)

    def test_invalid_configuration_returns_400(self):
        class InvalidContext:
            def Config(self):
                return {}

        result = func.handler(InvalidContext())

        self.assertEqual(result.status_code, 400)

    def test_active_lock_returns_409(self):
        client = self.Client([])
        with patch.object(func, "get_oci_client", return_value=client), patch.object(
            func, "acquire_execution_lock", return_value=None
        ):
            result = func.handler(self.Context())

        self.assertEqual(result.status_code, 409)


if __name__ == "__main__":
    unittest.main()

