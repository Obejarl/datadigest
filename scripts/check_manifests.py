"""Cross-check the Kubernetes manifests and docker-compose file.

Schema validation (kubeconform in CI) catches typos in field names; this
catches mistakes that are valid YAML but break at runtime: a Service whose
selector matches no pod, a port that goes nowhere, an env var the app never
reads.

    python scripts/check_manifests.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
K8S = ROOT / "k8s"
sys.path.insert(0, str(ROOT))

from datadigest.config import Settings  # noqa: E402

errors: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def load_resources() -> list[dict]:
    kustomization = yaml.safe_load((K8S / "kustomization.yaml").read_text())
    docs = []
    for name in kustomization["resources"]:
        path = K8S / name
        if name == "secret.yaml" and not path.exists():
            path = K8S / "secret.example.yaml"  # the real one is gitignored
        check(path.exists(), f"kustomization lists missing file {name}")
        if path.exists():
            docs += [d for d in yaml.safe_load_all(path.read_text()) if d]
    return docs


def pod_spec(doc: dict) -> dict | None:
    kind = doc["kind"]
    if kind in ("Deployment", "StatefulSet"):
        return doc["spec"]["template"]["spec"]
    if kind == "Job":
        return doc["spec"]["template"]["spec"]
    if kind == "CronJob":
        return doc["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    return None


def main() -> int:
    docs = load_resources()
    by_kind: dict[str, dict[str, dict]] = {}
    for d in docs:
        by_kind.setdefault(d["kind"], {})[d["metadata"]["name"]] = d

    settings_fields = {name.upper() for name in Settings.model_fields}
    config_keys = set(by_kind["ConfigMap"]["datadigest-config"]["data"])
    secret_keys = set(by_kind["Secret"]["datadigest-secret"]["stringData"])
    # POSTGRES_PASSWORD is read by the postgres container, not by our app.
    unknown = (config_keys | secret_keys) - settings_fields - {"POSTGRES_PASSWORD"}
    check(not unknown, f"env vars the app never reads: {sorted(unknown)}")

    workloads = {}
    for kind in ("Deployment", "StatefulSet"):
        for name, d in by_kind.get(kind, {}).items():
            selector = d["spec"]["selector"]["matchLabels"]
            labels = d["spec"]["template"]["metadata"]["labels"]
            check(selector.items() <= labels.items(), f"{kind}/{name}: selector {selector} != labels {labels}")
            workloads[name] = d

    for d in docs:
        spec = pod_spec(d)
        if spec is None:
            continue
        for c in spec["containers"]:
            for ref in c.get("envFrom", []):
                if "configMapRef" in ref:
                    check(ref["configMapRef"]["name"] in by_kind["ConfigMap"], f"unknown ConfigMap in {d['kind']}")
                if "secretRef" in ref:
                    check(ref["secretRef"]["name"] in by_kind["Secret"], f"unknown Secret in {d['kind']}")
            if c["image"].startswith("datadigest"):
                check(c.get("imagePullPolicy") == "IfNotPresent",
                      f"{d['kind']}/{d['metadata']['name']}: local image needs imagePullPolicy IfNotPresent")
            if d["kind"] != "Job" and d["kind"] != "CronJob":
                check("resources" in c and "requests" in c["resources"],
                      f"{d['kind']}/{d['metadata']['name']}: missing resource requests")

    for name, svc in by_kind.get("Service", {}).items():
        selector = svc["spec"]["selector"]
        targets = [w for w in workloads.values()
                   if selector.items() <= w["spec"]["template"]["metadata"]["labels"].items()]
        check(len(targets) == 1, f"Service/{name} selector {selector} matches {len(targets)} workloads")
        if targets:
            ports = {p["containerPort"] for c in targets[0]["spec"]["template"]["spec"]["containers"]
                     for p in c.get("ports", [])}
            for p in svc["spec"]["ports"]:
                check(p.get("targetPort", p["port"]) in ports, f"Service/{name} targets a port no container opens")

    for name, hpa in by_kind.get("HorizontalPodAutoscaler", {}).items():
        target = hpa["spec"]["scaleTargetRef"]
        check(target["name"] in by_kind.get(target["kind"], {}), f"HPA/{name} targets missing {target}")
        container = workloads[target["name"]]["spec"]["template"]["spec"]["containers"][0]
        check("cpu" in container["resources"]["requests"], f"HPA/{name}: target has no CPU request")

    secret_url = by_kind["Secret"]["datadigest-secret"]["stringData"]["DATABASE_URL"]
    check("@postgres:5432/" in secret_url and "postgres" in by_kind["Service"],
          "DATABASE_URL must point at the postgres Service")
    redis_url = by_kind["ConfigMap"]["datadigest-config"]["data"]["REDIS_URL"]
    check("//redis:6379" in redis_url and "redis" in by_kind["Service"], "REDIS_URL must point at the redis Service")

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    for name in ("postgres", "redis", "migrate", "api", "worker"):
        check(name in compose["services"], f"docker-compose is missing service {name}")

    print(f"checked {len(docs)} Kubernetes objects and docker-compose.yml")
    for e in errors:
        print("ERROR:", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
