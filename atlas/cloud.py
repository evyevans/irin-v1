"""Opt-in Supabase service-worker adapter. No default project or credentials."""

import json, os, re, urllib.request, urllib.error
from .storage import Conflict


class CloudError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CloudError("Redirect refused")


class CloudStore:
    def __init__(self):
        ref = os.environ.get("ATLAS_SUPABASE_PROJECT_REF", "").strip()
        self.key = os.environ.get("ATLAS_SUPABASE_SECRET_KEY", "")
        if not re.fullmatch("[a-z0-9]{20}", ref) or not self.key:
            raise CloudError("Set this installation project ref and server secret key")
        self.base = "https://" + ref + ".supabase.co/rest/v1/rpc/"

    def rpc(self, name, args):
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        # New backend secret keys are not JWTs. Legacy service-role JWTs need Bearer.
        if not self.key.startswith("sb_secret_"):
            headers["Authorization"] = "Bearer " + self.key
        req = urllib.request.Request(
            self.base + name,
            data=json.dumps(args, allow_nan=False).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.build_opener(NoRedirect).open(
                req, timeout=30
            ) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            # SQL serialization conflict is a PostgREST 500/409 depending on version. Never expose raw response.
            try:
                code = json.loads(e.read(4096)).get("code")
            except (ValueError, AttributeError):
                code = None
            finally:
                e.close()
            if code == "40001":
                raise Conflict(
                    "Concurrent or idempotency conflict; reload/recompute"
                ) from None
            raise CloudError(
                "Cloud request failed; inspect private provider logs"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise CloudError(
                "Cloud transport failed; retry with same request ID"
            ) from None

    def read(self):
        return self.rpc("atlas_store_read", {})

    def commit(self, revision, key, state):
        return self.rpc(
            "atlas_store_commit",
            dict(expected_revision=revision, request_id=key, new_state=state),
        )

    def verify_audit(self, expected_head=None):
        result = self.rpc("atlas_store_audit_verify", {})
        if expected_head is not None:
            result["valid"] = result["valid"] and result["head"] == expected_head
        return result
