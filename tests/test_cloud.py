"""Cloud adapter boundary tests, with transport replaced to avoid remote writes."""

import io, json, os, unittest, urllib.error
from unittest.mock import patch
from atlas.cloud import CloudStore, CloudError, NoRedirect
from atlas.storage import Conflict


class CloudBoundary(unittest.TestCase):
    def test_no_default_installation(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CloudError):
                CloudStore()

    def test_invalid_project_never_accepts_url_or_path(self):
        for ref in ["short", "https://example.com", "a" * 20 + "/extra"]:
            with patch.dict(
                os.environ,
                dict(
                    ATLAS_SUPABASE_PROJECT_REF=ref,
                    ATLAS_SUPABASE_SECRET_KEY="test-only",
                ),
            ):
                with self.assertRaises(CloudError):
                    CloudStore()

    def test_provider_errors_do_not_echo_response_or_key(self):
        with patch.dict(
            os.environ,
            dict(
                ATLAS_SUPABASE_PROJECT_REF="a" * 20,
                ATLAS_SUPABASE_SECRET_KEY="private-test-value",
            ),
        ):
            store = CloudStore()
        error = urllib.error.HTTPError(
            store.base, 500, "bad", {}, io.BytesIO(b'{"message":"private-test-value"}')
        )
        with patch("urllib.request.OpenerDirector.open", side_effect=error):
            with self.assertRaises(CloudError) as caught:
                store.read()
        self.assertNotIn("private-test-value", str(caught.exception))

    def test_revision_error_has_explicit_conflict_type(self):
        with patch.dict(
            os.environ,
            dict(
                ATLAS_SUPABASE_PROJECT_REF="a" * 20,
                ATLAS_SUPABASE_SECRET_KEY="test-only",
            ),
        ):
            store = CloudStore()
        error = urllib.error.HTTPError(
            store.base, 500, "bad", {}, io.BytesIO(b'{"code":"40001"}')
        )
        with patch("urllib.request.OpenerDirector.open", side_effect=error):
            with self.assertRaises(Conflict):
                store.commit(0, "request", {})

    def test_redirect_refused(self):
        with self.assertRaises(CloudError):
            NoRedirect().redirect_request(
                None, None, 302, "redirect", {}, "https://elsewhere.example.com"
            )

    def test_new_secret_key_is_not_sent_as_bearer_jwt(self):
        with patch.dict(
            os.environ,
            dict(
                ATLAS_SUPABASE_PROJECT_REF="a" * 20,
                ATLAS_SUPABASE_SECRET_KEY="sb_secret_" + "test-only",
            ),
        ):
            store = CloudStore()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        captured = []

        def transport(opener, request, timeout):
            captured.append(request)
            return Response(b'{"revision":0,"state":null}')

        with patch("urllib.request.OpenerDirector.open", new=transport):
            store.read()
        self.assertEqual(captured[0].get_header("Apikey"), "sb_secret_" + "test-only")
        self.assertIsNone(captured[0].get_header("Authorization"))
