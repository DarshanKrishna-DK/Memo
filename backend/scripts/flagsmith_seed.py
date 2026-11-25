"""Seed a (self-hosted) Flagsmith with Memo's project, environments, features and segments. Idempotent.

    cd backend && .venv/Scripts/python scripts/flagsmith_seed.py [--env Development] [--url http://localhost:8001/api/v1/]

Auth (Admin API): FLAGSMITH_ADMIN_API_KEY (organisation key, header `Authorization: Api-Key <key>`), else
FLAGSMITH_ADMIN_EMAIL + FLAGSMITH_ADMIN_PASSWORD (token login; then an organisation API key is created and saved).
Writes FLAGSMITH_ENVIRONMENT_KEY (server-side `ser.` key of --env) and FLAGSMITH_API_URL into D:/Memo/.env.local
(or --env-file). Never prints secret values.

What it creates (only what is missing; values someone changed in the dashboard are left alone):
- organisation "Memo" (only when logging in with a fresh admin), project "Memo", environments Development + Production
- one feature per key in app.flags.DEFAULTS: booleans are plain flags (enabled = default), everything else is a
  remote-config value (enabled, value = default; dicts as JSON). Environment defaults are written only when this run
  creates the feature. Exception: Production starts with phone_allowlist OFF (pilot only).
- followup_variant is multivariate: control "a" 50 % / variant "b" 50 % (hashed per family).
- segments (traits come from app/flags.py FlagsmithProvider.traits):
    phone_pilot       family_id IN $FLAGSMITH_PHONE_PILOT_FAMILIES (comma-separated uuids)  -> phone_allowlist ON
    hindi_or_kannada  language IN hi-IN,kn-IN                                               -> tts_voice_by_language
  Segment rules and these two overrides are re-asserted on every run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config, flags  # noqa: E402

PROJECT = "Memo"
ENVS = ("Development", "Production")
SERVER_KEY_NAME = "memo-backend"
TTS_SEGMENT_VALUE = {"hi-IN": {"grandma": "neha"}, "kn-IN": {"grandma": "neha"}}   # pins Grandma's voice for hi/kn


def set_env_var(path: Path, key: str, value: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{re.escape(key)}=.*$", text, re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", lambda _m: line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + ("\n" if text else "") + line + "\n"
    path.write_text(text, encoding="utf-8")


class Admin:
    def __init__(self, base: str, env_file: Path) -> None:
        self.base = base.rstrip("/") + "/"
        self.root = self.base.split("/api/v1/")[0] + "/"
        self.env_file = env_file
        self.http = httpx.Client(timeout=30)

    # ---- auth ----
    def login(self) -> None:
        key = config.env("FLAGSMITH_ADMIN_API_KEY")
        if key:
            self.http.headers["Authorization"] = f"Api-Key {key}"
            return
        email, pw = config.env("FLAGSMITH_ADMIN_EMAIL"), config.env("FLAGSMITH_ADMIN_PASSWORD")
        if not (email and pw):
            sys.exit("Set FLAGSMITH_ADMIN_API_KEY, or FLAGSMITH_ADMIN_EMAIL + FLAGSMITH_ADMIN_PASSWORD (see docs/FLAGSMITH.md).")
        r = self.http.post(self.base + "auth/login/", json={"email": email, "password": pw})
        if r.status_code != 200:
            sys.exit(f"Flagsmith login failed (HTTP {r.status_code}).")
        self.http.headers["Authorization"] = f"Token {r.json()['key']}"

    def req(self, method: str, path: str, **kw: Any) -> Any:
        url = path if path.startswith("http") else (self.root + path.lstrip("/") if path.startswith("/api/")
                                                    else self.base + path.lstrip("/"))
        r = self.http.request(method, url, **kw)
        if r.status_code >= 400:
            raise SystemExit(f"{method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else None

    def list(self, path: str, **params: Any) -> list:
        out: list = []
        data = self.req("GET", path, params={"page_size": 100, **params})
        while True:
            if isinstance(data, list):
                return data
            out.extend(data.get("results", []))
            if not data.get("next"):
                return out
            data = self.req("GET", data["next"])

    # ---- objects ----
    def organisation(self) -> int:
        orgs = self.list("organisations/")
        if orgs:
            org = next((o for o in orgs if o["name"] == PROJECT), orgs[0])
        else:
            org = self.req("POST", "organisations/", json={"name": PROJECT})
            print(f"created organisation {org['name']}")
        if not config.env("FLAGSMITH_ADMIN_API_KEY"):
            k = self.req("POST", f"organisations/{org['id']}/master-api-keys/",
                         json={"name": "memo-seed", "is_admin": True})
            set_env_var(self.env_file, "FLAGSMITH_ADMIN_API_KEY", k["key"])
            os.environ["FLAGSMITH_ADMIN_API_KEY"] = k["key"]
            self.http.headers["Authorization"] = f"Api-Key {k['key']}"
            print("created organisation API key -> FLAGSMITH_ADMIN_API_KEY in", self.env_file.name)
        return int(org["id"])

    def project(self, org: int) -> int:
        p = next((p for p in self.list("projects/", organisation=org) if p["name"] == PROJECT), None)
        if not p:
            p = self.req("POST", "projects/", json={"name": PROJECT, "organisation": org})
            print(f"created project {PROJECT}")
        return int(p["id"])

    def environments(self, project: int) -> dict[str, dict]:
        have = {e["name"]: e for e in self.list("environments/", project=project)}
        for name in ENVS:
            if name not in have:
                have[name] = self.req("POST", "environments/", json={"name": name, "project": project})
                print(f"created environment {name}")
        return have

    def features(self, project: int) -> tuple[dict[str, dict], set[str]]:
        have = {f["name"]: f for f in self.list(f"projects/{project}/features/")}
        created: set[str] = set()
        for key, default in flags.DEFAULTS.items():
            if key in have:
                continue
            body: dict[str, Any] = {"name": key, "description": f"Memo flag (code default: {json.dumps(default)})"}
            if isinstance(default, bool):
                body.update(default_enabled=default)
            else:
                body.update(default_enabled=True,
                            initial_value=json.dumps(default) if isinstance(default, dict) else str(default))
            if key == "followup_variant":
                body.update(type="MULTIVARIATE", multivariate_options=[
                    {"type": "unicode", "string_value": "b", "default_percentage_allocation": 50}])
            have[key] = self.req("POST", f"projects/{project}/features/", json=body)
            created.add(key)
            print(f"created feature {key}")
        return have, created

    def segment(self, project: int, name: str, description: str, prop: str, values: str) -> int:
        rules = [{"type": "ALL", "conditions": [], "rules": [
            {"type": "ANY", "rules": [], "conditions": [{"operator": "IN", "property": prop, "value": values}]}]}]
        seg = next((s for s in self.list(f"projects/{project}/segments/") if s["name"] == name), None)
        if not seg:
            seg = self.req("POST", f"projects/{project}/segments/",
                           json={"name": name, "description": description, "project": project, "rules": rules})
            print(f"created segment {name}")
            return int(seg["id"])
        cur = [c for r in seg.get("rules", []) for rr in r.get("rules", []) for c in rr.get("conditions", [])]
        if [(c.get("property"), c.get("operator"), c.get("value")) for c in cur] != [(prop, "IN", values)]:
            old = [dict(r, delete=True) for r in seg.get("rules", [])]
            self.req("PUT", f"projects/{project}/segments/{seg['id']}/",
                     json={"name": name, "description": description, "project": project, "rules": old + rules})
            print(f"updated segment {name}")
        return int(seg["id"])

    def feature_state(self, env_key: str, feature_id: int) -> dict:
        return self.req("GET", f"/api/__future__/environments/{env_key}/features/{feature_id}/")

    def put_feature_state(self, env_key: str, feature_id: int, body: dict) -> None:
        def clean(d: dict) -> dict:     # "variants": [] is rejected for non-multivariate features
            return {k: v for k, v in d.items() if not (k == "variants" and not v)}
        body = {"environment_default": clean(body["environment_default"]),
                "segment_overrides": [clean(o) for o in body.get("segment_overrides", [])]}
        self.req("PUT", f"/api/__future__/environments/{env_key}/features/{feature_id}/", json=body)

    def server_key(self, env_key: str) -> str:
        keys = self.list(f"environments/{env_key}/api-keys/")
        k = next((k for k in keys if k.get("name") == SERVER_KEY_NAME and k.get("active", True)), None)
        if not k:
            k = self.req("POST", f"environments/{env_key}/api-keys/", json={"name": SERVER_KEY_NAME, "active": True})
            print(f"created server-side key {SERVER_KEY_NAME}")
        return k["key"]


def fs_value(v: Any) -> dict:
    if isinstance(v, bool):
        return {"type": "boolean", "value": str(v).lower()}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    return {"type": "string", "value": json.dumps(v) if isinstance(v, (dict, list)) else str(v)}


def upsert_override(a: Admin, env_key: str, feature_id: int, segment_id: int, enabled: bool, value: Any) -> None:
    """Read-modify-write: keep the environment default and other overrides; (re)set this segment's override."""
    st = a.feature_state(env_key, feature_id)
    overrides = [o for o in (st.get("segment_overrides") or []) if int(o["segment"]["id"]) != segment_id]
    ov: dict[str, Any] = {"segment": {"id": segment_id}, "enabled": enabled}
    if value is not None:
        ov["value"] = fs_value(value)
    body = {"environment_default": st["environment_default"],
            "segment_overrides": [{k: o[k] for k in ("segment", "enabled", "priority", "value", "variants") if k in o}
                                  for o in overrides] + [ov]}
    a.put_feature_state(env_key, feature_id, body)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=config.env("FLAGSMITH_ADMIN_URL") or config.env("FLAGSMITH_API_URL")
                    or "http://localhost:8001/api/v1/")
    ap.add_argument("--env", default="Development", choices=ENVS, help="whose server-side key to write")
    ap.add_argument("--env-file", default=str(config.ROOT / ".env.local"))
    args = ap.parse_args()

    a = Admin(args.url, Path(args.env_file))
    a.login()
    org = a.organisation()
    project = a.project(org)
    envs = a.environments(project)
    feats, created = a.features(project)

    pilot = ",".join(x.strip() for x in config.env("FLAGSMITH_PHONE_PILOT_FAMILIES").split(",") if x.strip()) \
        or "none"
    seg_pilot = a.segment(project, "phone_pilot", "Families in the phone-call pilot (phone_allowlist on)",
                          "family_id", pilot)
    seg_lang = a.segment(project, "hindi_or_kannada", "Family language is Hindi or Kannada",
                         "language", "hi-IN,kn-IN")

    for name, env in envs.items():
        ek = env["api_key"]
        if name == "Production" and "phone_allowlist" in created:          # pilot only in production
            st = a.feature_state(ek, feats["phone_allowlist"]["id"])
            st["environment_default"]["enabled"] = False
            a.put_feature_state(ek, feats["phone_allowlist"]["id"],
                                {"environment_default": st["environment_default"],
                                 "segment_overrides": st.get("segment_overrides") or []})
        upsert_override(a, ek, feats["phone_allowlist"]["id"], seg_pilot, True, None)
        upsert_override(a, ek, feats["tts_voice_by_language"]["id"], seg_lang, True, TTS_SEGMENT_VALUE)
    print(f"segments + overrides ensured in {', '.join(envs)}")

    key = a.server_key(envs[args.env]["api_key"])
    env_file = Path(args.env_file)
    set_env_var(env_file, "FLAGSMITH_ENVIRONMENT_KEY", key)
    set_env_var(env_file, "FLAGSMITH_API_URL", args.url.rstrip("/") + "/")
    print(f"wrote FLAGSMITH_ENVIRONMENT_KEY ({args.env}, server-side) and FLAGSMITH_API_URL to {env_file.name}")


if __name__ == "__main__":
    main()
