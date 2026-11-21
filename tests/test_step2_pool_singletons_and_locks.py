"""Step 2 Milestone 2 unit tests: lock-order safety, pool.streams snapshots, TRC-017, and pool singletons."""

import json
import os
import shutil
import tempfile
import threading
import unittest
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI

from dashboard.camera_pool import CameraPool
from dashboard.dependencies import bind_app_state, clear_app_state
from dashboard.services.camera_config_store import CameraConfigStore
from dashboard.services.camera_pool_queries import snapshot_pool_streams
from dashboard.services.processing_mode_service import ProcessingModeService
from dashboard.services.stream_recording import StreamRecordingController


class _NoopWriter:
    """Minimal in-memory video writer stub for lock-stress tests."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.is_open = True

    def write(self, _frame) -> bool:
        return True

    def release(self) -> None:
        self.is_open = False

    def snapshot(self) -> dict:
        return {"frames_written": 1, "width": 32, "height": 32, "fps": 10.0}


class TestStep2PoolSingletonsAndLocks(unittest.TestCase):
    """Verify P0-2 lock safety, TRC-017 payload hardening, and P0-5 pool singletons."""

    def test_processing_mode_and_recording_no_ab_ba_deadlock(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        svc = ProcessingModeService(mode="full_realtime")
        rec = StreamRecordingController(
            "cam_01", output_dir=tmp, writer_factory=_NoopWriter, mode_service_getter=lambda: svc
        )
        self.addCleanup(rec.finalize_if_active)

        class _Stub:
            is_running, is_armed, subscriber_count, _is_hibernating = True, False, 0, False

            @property
            def is_recording(self) -> bool:
                return rec.is_recording

        pool = SimpleNamespace(streams={"cam_01": _Stub()}, _lock=threading.RLock())
        stop, frame = threading.Event(), np.zeros((32, 32, 3), dtype=np.uint8)
        t1 = threading.Thread(target=lambda: [svc.get_state(pool) for _ in range(60) if not stop.is_set()], daemon=True)
        t2 = threading.Thread(
            target=lambda: [
                (rec.start(filename=f"f_{i}.mp4"), rec.write_frame(frame), rec.stop())
                for i in range(30) if not stop.is_set()
            ],
            daemon=True,
        )
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)
        stop.set()
        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())

    def test_snapshot_pool_streams_is_thread_safe_under_mutations(self) -> None:
        pool = SimpleNamespace(streams={"cam_a": object()}, _lock=threading.RLock())
        errors: list[Exception] = []

        def _mutator() -> None:
            for i in range(100):
                with pool._lock:
                    pool.streams[f"cam_{i}"] = object()
                    pool.streams.pop(f"cam_{i}", None)

        def _reader() -> None:
            try:
                for _ in range(100):
                    for _cid in snapshot_pool_streams(pool):
                        pass
            except Exception as exc:
                errors.append(exc)

        t1, t2 = threading.Thread(target=_mutator), threading.Thread(target=_reader)
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        t2.join(timeout=3.0)
        self.assertEqual(errors, [])

    def test_trc_017_camera_config_store_unwraps_and_filters_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "cameras.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"cameras": [{"id": "c1", "source": "0", "enabled": False}, "bad", {"no_id": 1}]}, f)
            loaded, seeded = CameraConfigStore(cfg_path).load_cameras()
            self.assertFalse(seeded)
            self.assertEqual(list(loaded.keys()), ["c1"])

            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"cameras": []}, f)
            empty_loaded, empty_seeded = CameraConfigStore(cfg_path).load_cameras()
            self.assertFalse(empty_seeded)
            self.assertEqual(empty_loaded, {})

    def test_pool_singletons_survive_single_stream_restart_and_bind_app_state(self) -> None:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg_path = os.path.join(tmp, "cameras.json")
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump([{"id": "cam_1", "name": "C1", "source": "synthetic", "enabled": True}], f)
        pool = CameraPool(config_file=cfg_path, db_path=os.path.join(tmp, "t.db"), autostart=False)
        self.addCleanup(pool.stop_all)
        self.assertIsNotNone(pool.event_bus)
        self.assertIs(pool.world_graph._event_bus, pool.event_bus)
        self.assertIs(pool.streams["cam_1"].confidence_engine, pool.confidence_engine)
        self.assertIs(pool.streams["cam_1"].event_bus, pool.event_bus)

        pool._coordinator.restart_stream("cam_1", pool.camera_configs["cam_1"])
        self.assertTrue(pool.event_bus._running)
        self.assertIs(pool.streams["cam_1"].event_bus, pool.event_bus)

        app = FastAPI()
        bind_app_state(
            app, camera_pool=pool, world_graph=pool.world_graph,
            event_bus=pool.event_bus, confidence_engine=pool.confidence_engine,
            event_fts_index=pool.event_fts_index,
        )
        self.addCleanup(lambda: clear_app_state(app))
        self.assertIs(app.state.world_graph, pool.world_graph)
        self.assertIs(app.state.event_bus, pool.event_bus)
        self.assertIs(app.state.event_fts_index, pool.event_fts_index)


if __name__ == "__main__":
    unittest.main()
