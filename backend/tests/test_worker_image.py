"""The model worker's image and its Cloud Run deploy agree with the worker code and the setup script."""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def fetch_weights_models() -> dict[str, str]:
    tree = ast.parse((REPO / "workers/gpu/fetch_weights.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "MODELS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("MODELS not found")


class WorkerImageTests(unittest.TestCase):
    def test_every_model_the_worker_loads_is_baked_into_the_image(self):
        from workers.gpu.app import LIGHTING_MODEL
        self.assertEqual(fetch_weights_models(), {"lighting": LIGHTING_MODEL})

    def test_the_image_runs_offline_from_its_baked_weights(self):
        docker = (REPO / "workers/Dockerfile").read_text()
        self.assertLess(docker.index("fetch_weights.py"), docker.index("HF_HUB_OFFLINE=1"))
        self.assertIn("workers.gpu.app:create_app", docker)

    def test_cloud_run_deploy_is_one_l4_without_zonal_redundancy_that_scales_to_zero(self):
        run = (REPO / ".github/workflows/deploy-worker.yml").read_text()
        for flag in ("--gpu 1", "--gpu-type nvidia-l4", "--no-gpu-zonal-redundancy", "--min-instances 0",
                     "--max-instances 1", "--no-cpu-throttling", "--cpu 4", "--memory 16Gi"):
            self.assertIn(flag, run)
        self.assertIn("if: vars.GCP_PROJECT_ID != ''", run)  # does nothing until the project is set up

    def test_deploy_uses_the_accounts_registry_and_secret_the_setup_script_creates(self):
        setup = (REPO / "deploy/gcp/setup.sh").read_text()
        run = (REPO / ".github/workflows/deploy-worker.yml").read_text()
        for name in ("renovai-worker@", "renovai-worker-token", "/renovai/models"):
            self.assertIn(name, run)
        for name in ("renovai-worker@", "renovai-deployer@", "renovai-worker-token", "repositories create renovai"):
            self.assertIn(name, setup)
        self.assertTrue(re.search(r"assertion.ref == 'refs/heads/main'", setup))


if __name__ == "__main__":
    unittest.main()
