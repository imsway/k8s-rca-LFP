"""Scenario base classes for fault injection via flagd feature flags."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path

NAMESPACE = "otel-demo"
FLAGD_CONFIGMAP = "flagd-config"
FLAGD_CONFIG_KEY = "demo.flagd.json"
PROTO_CONFIGMAP = "demo-proto"  # holds pb/demo.proto from open-telemetry/opentelemetry-demo


def _admin_env() -> dict:
    env = {**subprocess.os.environ}
    env.pop("KUBECONFIG", None)
    return env


def kubectl(*args: str, check: bool = True) -> str:
    result = subprocess.run(["kubectl", *args], capture_output=True, text=True, env=_admin_env())
    if check and result.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


class BaseScenario(ABC):
    name: str
    description: str

    root_cause_service: str
    root_cause_type: str
    ground_truth_summary: str

    @abstractmethod
    def inject(self) -> None:
        """Apply the failure. Must be idempotent-safe to call once per run."""

    @abstractmethod
    def teardown(self) -> None:
        """Revert the failure, restoring baseline behavior."""

    def get_incident_description(self) -> str:
        raise NotImplementedError

    def wait_for_ready(self, label_selector: str, timeout_s: int = 120) -> None:
        kubectl(
            "wait", "--for=condition=Ready", "pod",
            "-l", label_selector, "-n", NAMESPACE, f"--timeout={timeout_s}s",
        )

    def wait(self, seconds: int) -> None:
        time.sleep(seconds)

    def grpc_call(self, target: str, method: str, payload: dict, timeout_s: int = 30) -> str:
        """Direct gRPC call via a throwaway grpcurl pod."""
        self.ensure_proto_configmap()
        pod_name = "grpcurl-oneshot"
        manifest = {
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": pod_name, "namespace": NAMESPACE},
            "spec": {
                "restartPolicy": "Never",
                "containers": [{
                    "name": "grpcurl", "image": "fullstorydev/grpcurl:latest",
                    "command": [
                        "/bin/grpcurl", "-plaintext", "-import-path=/protos", "-proto=demo.proto",
                        "-d", json.dumps(payload), target, method,
                    ],
                    "volumeMounts": [{"name": "proto", "mountPath": "/protos"}],
                }],
                "volumes": [{"name": "proto", "configMap": {"name": PROTO_CONFIGMAP}}],
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pod.json"
            path.write_text(json.dumps(manifest))
            kubectl("delete", "pod", pod_name, "-n", NAMESPACE, "--ignore-not-found=true")
            kubectl("apply", "-f", str(path))
        try:
            kubectl("wait", "--for=jsonpath={.status.phase}=Succeeded", f"pod/{pod_name}",
                    "-n", NAMESPACE, f"--timeout={timeout_s}s", check=False)
            time.sleep(1)  # let the log stream flush
            return kubectl("logs", pod_name, "-n", NAMESPACE)
        finally:
            kubectl("delete", "pod", pod_name, "-n", NAMESPACE, "--ignore-not-found=true", check=False)

    def ensure_proto_configmap(self) -> None:
        proto_path = Path(__file__).parent / "demo.proto"
        with tempfile.TemporaryDirectory() as tmp:
            yaml = kubectl(
                "create", "configmap", PROTO_CONFIGMAP, "-n", NAMESPACE,
                f"--from-file=demo.proto={proto_path}", "--dry-run=client", "-o", "yaml",
            )
            proc = subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml, capture_output=True, text=True, env=_admin_env())
            if proc.returncode != 0:
                raise RuntimeError(f"kubectl apply failed:\n{proc.stderr}")


class FlagdScenario(BaseScenario):
    """Scenario that toggles a flagd feature flag. Edits the ConfigMap then
    restarts flagd (flagd reads flags from an init-copied file, not live)."""

    flag_name: str
    injected_variant: str
    baseline_variant: str = "off"

    def _set_variant(self, variant: str) -> None:
        raw = kubectl("get", "configmap", FLAGD_CONFIGMAP, "-n", NAMESPACE, "-o", "json")
        configmap = json.loads(raw)
        config = json.loads(configmap["data"][FLAGD_CONFIG_KEY])
        if self.flag_name not in config["flags"]:
            raise KeyError(f"Flag '{self.flag_name}' not found in {FLAGD_CONFIGMAP}.")
        config["flags"][self.flag_name]["defaultVariant"] = variant

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / FLAGD_CONFIG_KEY
            path.write_text(json.dumps(config, indent=2))
            yaml = kubectl(
                "create", "configmap", FLAGD_CONFIGMAP, "-n", NAMESPACE,
                f"--from-file={FLAGD_CONFIG_KEY}={path}", "--dry-run=client", "-o", "yaml",
            )
            proc = subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml, capture_output=True, text=True, env=_admin_env())
            if proc.returncode != 0:
                raise RuntimeError(f"kubectl apply failed:\n{proc.stderr}")

        kubectl("rollout", "restart", "deployment/flagd", "-n", NAMESPACE)
        kubectl("rollout", "status", "deployment/flagd", "-n", NAMESPACE, "--timeout=120s")

    def inject(self) -> None:
        self._set_variant(self.injected_variant)

    def teardown(self) -> None:
        self._set_variant(self.baseline_variant)
